"""
LLM 客户端抽象：接入 OpenRouter，支持 reasoning 开关，预设模型 x-ai/grok-4.1-fast:free。
请务必透过环境变量设置 API Key，不要将密钥写入代码。
"""
import os
from typing import Any, Dict, List, Optional

import httpx


class LLMClient:
    """简单包装，支持 OpenRouter 接口，可替换供应商与模型。"""

    def __init__(
        self,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
    ):
        self.model_name = model_name or os.getenv("OPENROUTER_MODEL", "x-ai/grok-4.1-fast:free")
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.endpoint = endpoint or os.getenv("OPENROUTER_ENDPOINT", "https://openrouter.ai/api/v1/chat/completions")

    async def chat(self, messages: List[Dict[str, Any]], enable_reasoning: bool = True) -> Dict[str, Any]:
        """
        调用聊天接口，返回完整 JSON。messages 为 [{role, content, ...}]。
        若需保留 reasoning_details，呼叫者可自行传入先前的 assistant message。
        """
        if not self.api_key:
            raise RuntimeError("缺少 OPENROUTER_API_KEY 环境变量，无法呼叫模型")

        payload = {
            "model": self.model_name,
            "messages": messages,
            "reasoning": {"enabled": enable_reasoning},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(self.endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def complete_simple(self, prompt: str) -> str:
        """
        兼容先前接口：单纯用 prompt 呼叫并返回字串内容，便于渐进接入。
        """
        messages = [{"role": "user", "content": prompt}]
        data = await self.chat(messages, enable_reasoning=False)
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")
