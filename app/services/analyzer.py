"""
负责协调需求拆解、文件检索、以及最终的结构化结果组装。
"""
import json
import os
import tempfile
import logging
from pathlib import Path
from typing import Dict, List, Optional

from app.llm.client import LLMClient
from app.services.retrieval import CodeSnippet, RetrievalService
from app.services.testgen import TestGenerator


class Analyzer:
    """核心分析器，包含需求拆解与候选匹配流程。"""

    def __init__(self, llm_client: Optional[LLMClient] = None, retrieval: Optional[RetrievalService] = None):
        self.llm = llm_client or LLMClient()
        self.retrieval = retrieval or RetrievalService()
        # 通过环境变量控制是否启用动态验证（加分项）
        self.enable_verification = os.getenv("ENABLE_TEST_RUN", "false").lower() == "true"
        self.testgen = TestGenerator(enable_run=self.enable_verification)

    async def run(self, problem_description: str, zip_path: Path) -> Dict:
        """
        完整执行流程：解压 → 扫描 → 需求拆解 → 搜索候选 → LLM 甄别 → 组装结果。
        回传字典供 report builder 序列化。
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self.retrieval.extract_zip(zip_path, root)
            files = self.retrieval.scan_files(root)

            features = await self._split_features(problem_description)
            candidates_map = self.retrieval.search_features(features, files)

            feature_analysis = []
            for feature in features:
                chosen_locations = await self._select_with_llm(feature, candidates_map.get(feature, []))
                feature_analysis.append(
                    {
                        "feature_description": feature,
                        "implementation_location": chosen_locations,
                    }
                )

            execution_plan = await self._suggest_execution_plan(root)

            result: Dict[str, object] = {
                "feature_analysis": feature_analysis,
                "execution_plan_suggestion": execution_plan,
            }

            # 若启用验证，生成动态测试并执行
            if self.enable_verification:
                result["functional_verification"] = self.testgen.generate(root, result)

            return result

    async def _split_features(self, description: str) -> List[str]:
        """
        优先用 LLM 拆解需求；失败或不可用时回退规则拆分。
        """
        try:
            messages = [
                {
                    "role": "system",
                    "content": "你是需求拆分助手，将需求文本拆分为功能点，覆盖主要功能，避免过度细分，输出 JSON 数组字符串。",
                },
                {"role": "user", "content": description},
            ]
            data = await self.llm.chat(messages, enable_reasoning=False)
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            features = json.loads(content) if content else []
            if isinstance(features, list) and features:
                return [str(f).strip() for f in features if str(f).strip()]
        except Exception:
            pass
        # 回退：规则拆分
        return self._split_features_rule(description)

    def _split_features_rule(self, description: str) -> List[str]:
        """规则拆分：按行；若单行则按句号/分号拆分。"""
        lines = [ln.strip("- *\t") for ln in description.splitlines() if ln.strip()]
        if lines:
            return lines
        parts = [p.strip() for p in description.replace("；", ";").replace("。", ".").split(".") if p.strip()]
        return parts or [description]

    async def _select_with_llm(self, feature: str, candidates: List[CodeSnippet]) -> List[Dict]:
        """
        调用 LLM 在候选中挑选最相关的实现点。
        若 LLM 不可用或出错，则回退直接返回候选的前几个。
        """
        if not candidates:
            return []

        candidate_lines = []
        for idx, c in enumerate(candidates, start=1):
            ctx = c.context.replace("\n", " ")
            ctx = ctx[:400]  # 控制长度
            candidate_lines.append(
                f"{idx}) file: {c.file} lines: {c.lines} func: {c.function or 'N/A'} ctx: {ctx}"
            )
        user_prompt = "\n".join(
            [
                f"Feature: {feature}",
                "Candidates:",
                *candidate_lines,
                "只允许在候选列表中选择相关实现点；若无匹配返回空。",
            ]
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "你是代码审查助手，根据给定功能描述在候选列表中挑选最相关的实现位置。"
                    "优先选择源代码文件中的实现（如 .ts/.js/.py 的 service/resolver/controller 方法），"
                    "避免选择 schema/测试/文档/配置。"
                    "返回 JSON：{\"chosen\": [{\"file\":..., \"function\":..., \"lines\":...}]}，"
                    "若无匹配，返回 {\"chosen\": []}，不得臆造候选之外的文件。"
                ),
            },
            {"role": "user", "content": user_prompt},
        ]

        try:
            data = await self.llm.chat(messages, enable_reasoning=False)
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            parsed = json.loads(content) if content else {}
            chosen = parsed.get("chosen", [])
            normalized: List[Dict] = []
            for item in chosen:
                normalized.append(
                    {
                        "file": item.get("file"),
                        "function": item.get("function"),
                        "lines": item.get("lines"),
                    }
                )
            if normalized:
                return normalized
        except Exception:
            pass

        # 回退：直接取前 2 个候选
        fallback: List[Dict] = []
        for c in candidates[:2]:
            fallback.append(
                {
                    "file": c.file,
                    "function": c.function,
                    "lines": c.lines,
                }
            )
        return fallback

    async def _suggest_execution_plan(self, root: Path) -> str:
        """根据探测到的文件给出启动建议，优先尝试 LLM 总结，失败回退规则。"""
        hint = self._collect_project_hint(root)
        logger = logging.getLogger("ai_agent.analyze")
        logger.info("execution plan hint collected: %s", "yes" if hint else "no")

        # 尝试 LLM 生成一句话启动说明
        if hint:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a start-up helper. Return one concise plain-text sentence with install/start commands "
                        "and API endpoints/ports if known. No markdown, no code fences, no bullet lists."
                    ),
                },
                {"role": "user", "content": hint},
            ]
            try:
                data = await self.llm.chat(messages, enable_reasoning=False)
                if isinstance(data, dict):
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if content:
                        cleaned = content.replace("```", "").replace("**", "").strip()
                        cleaned = " ".join(cleaned.split())
                        return cleaned
            except Exception:
                logger.warning("execution plan LLM failed, fallback to rules", exc_info=True)

        # 规则回退
        if (root / "package.json").exists():
            pkg_text = (root / "package.json").read_text(encoding="utf-8")
            if "start:dev" in pkg_text:
                return "npm install && npm run start:dev"
            if "start" in pkg_text:
                return "npm install && npm run start"
            if "dev" in pkg_text:
                return "npm install && npm run dev"
            return "npm install && npm start"
        if (root / "requirements.txt").exists():
            return "pip install -r requirements.txt && uvicorn app.main:app --reload"
        if (root / "docker-compose.yml").exists():
            return "docker compose up"
        if (root / "Dockerfile").exists():
            return "docker build -t app . && docker run -p 8000:8000 app"
        return "请参考项目说明启动服务"

    def _collect_project_hint(self, root: Path) -> str:
        """收集 package.json、README、schema 等线索，支持单子目录包裹和递归查找。"""
        hints = []
        project_root = self._detect_project_root(root)

        pkg_path = project_root / "package.json"
        if pkg_path.exists():
            try:
                pkg_text = pkg_path.read_text(encoding="utf-8")
                hints.append(f"package.json 内容: {pkg_text[:2000]}")
            except Exception:
                pass
        readme_path = project_root / "README.md"
        if readme_path.exists():
            try:
                readme_text = readme_path.read_text(encoding="utf-8")
                hints.append(f"README 节选: {readme_text[:2000]}")
            except Exception:
                pass
        if (project_root / "schema.gql").exists() or (project_root / "schema.graphql").exists():
            hints.append("检测到 GraphQL schema，可能是 GraphQL API，常见端点 /graphql，端口多为 3000/4000")
        if (project_root / "docker-compose.yml").exists():
            hints.append("存在 docker-compose.yml，可用 docker compose up 启动")
        if (project_root / "Dockerfile").exists():
            hints.append("存在 Dockerfile，可用 docker build / docker run 启动")
        return "\n".join(hints)

    def _detect_project_root(self, root: Path) -> Path:
        """处理解压后只有单子目录的情况，或递归查找首个 package/README/docker 文件。"""
        # 如果根下有 package.json 等，直接用根
        direct_hits = ["package.json", "README.md", "docker-compose.yml", "Dockerfile"]
        if any((root / f).exists() for f in direct_hits):
            return root
        # 若根下只有一个子目录，则深入
        children = [p for p in root.iterdir() if p.is_dir()]
        if len(children) == 1:
            sub = children[0]
            if any((sub / f).exists() for f in direct_hits):
                return sub
        # 递归查找首个命中的 package.json，找不到则返回根
        for path in root.rglob("package.json"):
            return path.parent
        return root
