"""
负责处理 /analyze 请求，校验输入并调用服务逻辑。
"""
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status, Form
from fastapi.responses import JSONResponse

from app.services.analyzer import Analyzer
from app.services.report import ReportBuilder

router = APIRouter()
logger = logging.getLogger("ai_agent.analyze")

# 简单限制：避免异常巨大的压缩包占满资源
MAX_ZIP_SIZE_MB = 50


def _ensure_zip_size(file: UploadFile) -> None:
    """粗略检查上传文件大小（file.spool_max_size 无法直接判断，这里使用临时保存）。"""
    with tempfile.TemporaryFile() as tmp:
        size = 0
        chunk = file.file.read(1024 * 1024)
        while chunk:
            size += len(chunk)
            if size > MAX_ZIP_SIZE_MB * 1024 * 1024:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"code_zip 超过 {MAX_ZIP_SIZE_MB}MB 上限",
                )
            tmp.write(chunk)
            chunk = file.file.read(1024 * 1024)
        # 重置文件指针供后续使用
        file.file.seek(0)


def get_analyzer() -> Analyzer:
    """依赖注入，方便未来替换 Analyzer 实现。"""
    return Analyzer()


def get_report_builder() -> ReportBuilder:
    return ReportBuilder()


@router.post("/analyze")
async def analyze(
    problem_description: str = Form(..., description="功能需求描述"),
    code_zip: UploadFile = File(..., description="包含源代码的 zip"),
    analyzer: Analyzer = Depends(get_analyzer),
    report_builder: ReportBuilder = Depends(get_report_builder),
):
    """接收 multipart/form-data，先校验，再调用核心分析逻辑。"""
    logger.info("开始分析请求，文件名=%s", code_zip.filename)

    if not problem_description.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="problem_description 不可为空")
    if not code_zip.filename or not code_zip.filename.endswith(".zip"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="code_zip 必须为 zip 文件")

    _ensure_zip_size(code_zip)

    # 使用临时文件保存上传内容，避免一次性读入内存
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        shutil.copyfileobj(code_zip.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        logger.info("已保存上传 zip 至临时文件 %s，开始分析", tmp_path)
        analysis_result = await analyzer.run(problem_description=problem_description, zip_path=tmp_path)
        response_payload = report_builder.build(analysis_result)
        logger.info("分析完成，返回成功结果")
        return JSONResponse(content=response_payload)
    except HTTPException:
        raise
    except Exception as exc:  # 保底错误处理，防止堆栈外泄
        logger.exception("分析过程发生未预期错误")
        raise HTTPException(status_code=500, detail=f"分析过程发生错误: {exc}")
    finally:
        tmp_path.unlink(missing_ok=True)
