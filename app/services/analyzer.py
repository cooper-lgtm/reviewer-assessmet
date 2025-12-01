"""
负责协调需求拆解、文件检索、以及最终的结构化结果组装。
"""
import json
import os
import tempfile
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

            execution_plan = self._suggest_execution_plan(root)

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
                f"{idx}) file: {c.file} lines: {c.lines} func: {c.function or 'N/A'} summary: {c.summary} ctx: {ctx}"
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
                    "返回 JSON：{\"chosen\": [{\"file\":..., \"function\":..., \"lines\":..., \"summary\":...}]}，"
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
                        "summary": item.get("summary"),
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
                    "summary": c.summary,
                }
            )
        return fallback

    def _suggest_execution_plan(self, root: Path) -> str:
        """根据探测到的文件给出启动建议。"""
        if (root / "package.json").exists():
            return "npm install && npm run start"
        if (root / "requirements.txt").exists():
            return "pip install -r requirements.txt && uvicorn app.main:app --reload"
        return "请参考项目说明启动服务"
