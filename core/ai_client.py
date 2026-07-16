"""
核心 AI 客户端
封装 OpenAI 兼容 API 调用。原生异步（httpx），不阻塞事件循环。
"""

import httpx
from typing import List, Dict, Optional


class AIClient:
    """OpenAI 兼容 API 客户端（异步）。"""

    def __init__(self, config: dict):
        self._api_url = config["ai"]["api_url"]
        self._api_key = config["ai"]["api_key"]
        self._model = config["ai"]["model"]
        self._temperature = config["ai"].get("temperature", 0.4)
        self._max_tokens = config["ai"].get("max_tokens", 300)
        self._client: Optional[httpx.AsyncClient] = None

    async def _ensure_client(self):
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))

    async def chat(self, messages: List[Dict[str, str]]) -> str:
        """
        异步发送消息列表并获取 AI 回复。
        可直接 await，无需 run_in_executor。

        Args:
            messages: [{"role": "system"|"user"|"assistant", "content": "..."}]

        Returns:
            AI 回复的纯文本
        """
        await self._ensure_client()
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens
        }

        try:
            resp = await self._client.post(self._api_url, json=payload, headers=headers)
            data = resp.json()
            if "choices" not in data:
                err_msg = data.get("error", {}).get("message", str(data))
                print(f"[AI错误] API 返回异常: {err_msg}")
                return "（出了点小问题，请稍后再试...）"
            return data["choices"][0]["message"]["content"].strip()
        except httpx.TimeoutException:
            return "（思考时间太长了，请稍后再问我吧...）"
        except httpx.ConnectError:
            return "（API 服务不可达，请检查网络...）"
        except Exception as e:
            print(f"[AI错误] 未知异常: {e}")
            return "（出了点小问题，请稍后再试...）"

    async def close(self):
        """释放异步客户端资源。"""
        if self._client:
            await self._client.aclose()
            self._client = None
