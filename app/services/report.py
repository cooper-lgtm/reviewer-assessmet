"""
将 Analyzer 的结果整理为统一 JSON 格式，并使用 pydantic 校验。
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ValidationError


class ImplementationLocation(BaseModel):
    file: str
    function: Optional[str] = None
    lines: str
    summary: Optional[str] = None


class FeatureItem(BaseModel):
    feature_description: str
    implementation_location: List[ImplementationLocation]


class FunctionalVerification(BaseModel):
    generated_test_code: str
    execution_result: Dict[str, Any]


class Report(BaseModel):
    feature_analysis: List[FeatureItem]
    execution_plan_suggestion: str
    functional_verification: Optional[FunctionalVerification] = None


class ReportBuilder:
    """负责将分析结果封装为标准输出格式。"""

    def build(self, analysis_result: Dict[str, Any]) -> Dict[str, Any]:
        try:
            report = Report(**analysis_result)
        except ValidationError as exc:
            # 若缺字段，尝试自动补足为最少集合
            sanitized = {
                "feature_analysis": analysis_result.get("feature_analysis", []),
                "execution_plan_suggestion": analysis_result.get("execution_plan_suggestion", "请参考项目启动说明"),
                "functional_verification": analysis_result.get("functional_verification"),
            }
            report = Report(**sanitized)
        return report.model_dump()
