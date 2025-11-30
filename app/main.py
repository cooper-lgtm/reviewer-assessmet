"""
FastAPI 应用入口，负责挂载路由与全局配置与基础日志。
"""
import logging
import time
from fastapi import FastAPI, Request

from app.routers import analyze

# 基础日志设定：输出时间、等级、模块、消息
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ai_agent")

app = FastAPI(title="AI Code Feature Mapper", version="0.1.0")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """简单的请求日志，中途出错也能留下痕迹。"""
    start = time.time()
    logger.info("收到请求 %s %s", request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("处理请求时出错")
        raise
    duration_ms = (time.time() - start) * 1000
    logger.info("完成请求 %s %s 状态=%s 耗时=%.1fms", request.method, request.url.path, response.status_code, duration_ms)
    return response


# 挂载分析路由
app.include_router(analyze.router, prefix="", tags=["analyze"])


@app.get("/health")
def health_check():
    """健康检查，便于部署后探活。"""
    return {"status": "ok"}
