import os
import re
import time
from typing import List, Dict, Any

import httpx

from kevlarbot.config import logger
from kevlarbot.providers import AI_PROVIDERS, BROWSE_GROUPS, ANTHROPIC_GROUPS


class AIClient:
    def __init__(self):
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self._model_cache: Dict[str, Dict[str, Any]] = {}

    async def close(self):
        await self.http_client.aclose()

    def resolve_provider(self, active_model: str) -> Dict[str, Any]:
        if active_model in AI_PROVIDERS:
            return AI_PROVIDERS[active_model]
        if ":" in active_model:
            group, model_id = active_model.split(":", 1)
            g = BROWSE_GROUPS.get(group)
            if g:
                return {"name": f"{model_id} ({g['label']})", "url": g["chat_url"],
                        "model_id": model_id, "is_free": False, "group": group}
        return AI_PROVIDERS["mimo"]

    def get_fallback_chain(self, active_model: str) -> List[Dict[str, Any]]:
        primary = self.resolve_provider(active_model)
        providers = [primary]
        if primary.get("is_free"):
            fallback_keys = [k for k in AI_PROVIDERS if k != active_model and AI_PROVIDERS[k].get("is_free")]
            for k in fallback_keys:
                providers.append(AI_PROVIDERS[k])
        return providers

    async def get_group_models(self, group: str, api_key: str) -> List[Dict[str, str]]:
        from kevlarbot.config import OR_CACHE_TTL
        g = BROWSE_GROUPS[group]
        now = time.time()
        cached = self._model_cache.get(group, {"data": [], "ts": 0})
        if cached["data"] and now - cached["ts"] < OR_CACHE_TTL:
            return cached["data"]
        try:
            if group in ANTHROPIC_GROUPS:
                headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
            else:
                headers = {"Authorization": f"Bearer {api_key}"}
            resp = await self.http_client.get(g["models_url"], headers=headers)
            resp.raise_for_status()
            items = resp.json().get("data", [])
            models = [{"id": m["id"], "name": m.get("display_name") or m.get("name", m["id"])} for m in items]
            self._model_cache[group] = {"data": models, "ts": now}
            return models
        except Exception as e:
            logger.error(f"{group} model list fetch failed: {self._sanitize_error(e)}")
            return cached["data"]

    async def verify_key(self, group_name: str, api_key: str) -> bool:
        try:
            if group_name in ANTHROPIC_GROUPS:
                headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
                body = {"model": "claude-sonnet-4-20250514", "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}
                resp = await self.http_client.post(
                    BROWSE_GROUPS[group_name]["chat_url"], json=body, headers=headers, timeout=10.0
                )
                return resp.status_code == 200

            if group_name in BROWSE_GROUPS:
                g = BROWSE_GROUPS[group_name]
                headers = {"Authorization": f"Bearer {api_key}"}
                resp = await self.http_client.get(g["models_url"], headers=headers, timeout=10.0)
                return resp.status_code == 200

            provider = next((p for p in AI_PROVIDERS.values() if p.get("group") == group_name), None)
            if not provider:
                return False
            response = await self.http_client.post(
                provider["url"],
                json={"model": provider["model_id"], "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10.0
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Verification error for {group_name}: {self._sanitize_error(e)}")
            return False

    async def chat(self, provider: Dict[str, Any], messages: list, api_key: str, system_prompt: str) -> str:
        is_anthropic = provider.get("group") in ANTHROPIC_GROUPS
        if is_anthropic:
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
            body = {"model": provider["model_id"], "system": system_prompt,
                    "messages": [m for m in messages if m.get("role") != "system"], "max_tokens": 256}
        else:
            headers = {"Authorization": f"Bearer {api_key}"}
            body = {"model": provider["model_id"], "messages": messages, "max_tokens": 256}

        response = await self.http_client.post(provider["url"], json=body, headers=headers)

        if response.status_code == 401:
            raise AuthError(provider.get("group", "unknown"))
        if response.status_code == 429:
            raise RateLimitError(provider["name"])

        response.raise_for_status()
        data = response.json()
        if is_anthropic:
            reply = data["content"][0]["text"]
        else:
            reply = data["choices"][0]["message"]["content"]
        return self._strip_think_tags(reply)

    @staticmethod
    def _strip_think_tags(text: str) -> str:
        return re.sub(r"<think>[\s\S]*?</think>\s*", "", text).strip()

    @staticmethod
    def _sanitize_error(error: Exception) -> str:
        msg = str(error)
        for pattern in ["sk-", "Bearer ", "x-api-key:", "key="]:
            if pattern in msg:
                msg = msg.split(pattern)[0] + pattern + "[REDACTED]"
        return msg[:200]


class AuthError(Exception):
    def __init__(self, group: str):
        self.group = group
        super().__init__(f"Auth failed for {group}")


class RateLimitError(Exception):
    def __init__(self, provider_name: str):
        self.provider_name = provider_name
        super().__init__(f"Rate limited by {provider_name}")
