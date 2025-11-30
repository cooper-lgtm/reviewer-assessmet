"""
测试 Agent API 的基本行为。
"""
import io
import zipfile

import pytest
import httpx
from app.main import app


@pytest.mark.asyncio
async def test_analyze_success():
    """成功路径：提交有效 zip 与描述，应返回 200 且包含预期字段。"""
    # 构造内存 zip
    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, mode="w") as zf:
        zf.writestr("hello.txt", "print('hello')\n")
    mem_zip.seek(0)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        files = {
            "problem_description": (None, "测试功能"),
            "code_zip": ("sample.zip", mem_zip.getvalue(), "application/zip"),
        }
        resp = await client.post("/analyze", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert "feature_analysis" in data
    assert "execution_plan_suggestion" in data


@pytest.mark.asyncio
async def test_analyze_missing_fields():
    """缺少必要字段时应返回 400/422。"""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/analyze", files={"problem_description": (None, "")})
    # FastAPI 对缺少必填 file 会直接返回 422
    assert resp.status_code == 422
