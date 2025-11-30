"""
负责协调需求拆解、文件检索、以及最终的结构化结果组装。
"""
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
        完整执行流程：解压 → 扫描 → 需求拆解 → 搜索候选 → 组装结果。
        回传字典供 report builder 序列化。
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self.retrieval.extract_zip(zip_path, root)
            files = self.retrieval.scan_files(root)

            features = self._split_features(problem_description)
            candidates = self.retrieval.search_features(features, files)

            feature_analysis = [
                self._build_feature_item(feature, candidates.get(feature, [])) for feature in features
            ]

            execution_plan = self._suggest_execution_plan(root)

            result: Dict[str, object] = {
                "feature_analysis": feature_analysis,
                "execution_plan_suggestion": execution_plan,
            }

            # 若启用验证，生成动态测试并执行
            if self.enable_verification:
                result["functional_verification"] = self.testgen.generate(root, result)

            return result

    def _split_features(self, description: str) -> List[str]:
        """粗略拆解需求文本，可替换为 LLM 拆分。"""
        lines = [ln.strip("- *\t") for ln in description.splitlines() if ln.strip()]
        if lines:
            return lines
        # 如果没有换行，用句号切割
        parts = [p.strip() for p in description.replace("；", ";").replace("。", ".").split(".") if p.strip()]
        return parts or [description]

    def _build_feature_item(self, feature: str, snippets: List[CodeSnippet]) -> Dict:
        locations = [
            {
                "file": sn.file,
                "function": None,
                "lines": sn.lines,
                "summary": sn.summary,
            }
            for sn in snippets
        ]
        return {"feature_description": feature, "implementation_location": locations}

    def _suggest_execution_plan(self, root: Path) -> str:
        """根据探测到的文件给出启动建议。"""
        if (root / "package.json").exists():
            return "npm install && npm run start"
        if (root / "requirements.txt").exists():
            return "pip install -r requirements.txt && uvicorn app.main:app --reload"
        return "请参考项目说明启动服务"
