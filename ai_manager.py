import asyncio
import base64
import json
import os
import tempfile
from typing import Optional

import aiohttp
import google.generativeai as genai

import db
from config import (
    GOOGLE_API_KEY, NVIDIA_API_KEY, OPENROUTER_API_KEY,
    NVIDIA_BASE_URL, OPENROUTER_BASE_URL,
    DEFAULT_MODELS, PROVIDER_ORDER,
)

QUOTA_KEYWORDS = ["quota", "rate limit", "exhausted", "insufficient", "overloaded", "capacity", "billing"]


def _is_quota_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(kw in msg for kw in QUOTA_KEYWORDS)


class AIManager:
    def __init__(self):
        if GOOGLE_API_KEY:
            genai.configure(api_key=GOOGLE_API_KEY)

        # Provider configs for direct HTTP calls (no openai SDK needed)
        self.provider_config = {}
        if NVIDIA_API_KEY:
            self.provider_config["nvidia"] = {
                "base_url": NVIDIA_BASE_URL,
                "api_key": NVIDIA_API_KEY,
                "headers": {},
            }
        if OPENROUTER_API_KEY:
            self.provider_config["openrouter"] = {
                "base_url": OPENROUTER_BASE_URL,
                "api_key": OPENROUTER_API_KEY,
                "headers": {
                    "HTTP-Referer": "https://telegram-personal-assistant",
                    "X-Title": "Personal Assistant Bot",
                },
            }

    def available_providers(self) -> list[str]:
        result = []
        for p in PROVIDER_ORDER:
            if p == "gemini" and GOOGLE_API_KEY:
                result.append(p)
            elif p in self.provider_config:
                result.append(p)
        return result

    async def chat(
        self,
        user_id: int,
        history: list[dict],
        user_message: str,
        system: str = "",
        image_bytes: Optional[bytes] = None,
        image_mime: str = "image/jpeg",
    ) -> tuple[str, str]:
        """Returns (reply_text, provider_used). Auto-switches on quota errors."""
        user = await db.get_user(user_id)
        current = user["current_provider"] if user else PROVIDER_ORDER[0]

        available = self.available_providers()
        if not available:
            raise RuntimeError("No AI providers configured. Please set API keys.")

        ordered = [current] + [p for p in available if p != current]
        full_messages = history + [{"role": "user", "content": user_message}]

        last_error = None
        for provider in ordered:
            if provider not in available:
                continue
            try:
                model = await db.get_user_model(user_id, provider)
                reply, tokens = await self._call(
                    provider, model, full_messages, system, image_bytes, image_mime
                )
                if tokens:
                    await db.add_token_usage(user_id, provider, tokens)
                if provider != current:
                    await db.update_user_provider(user_id, provider)
                return reply, provider
            except Exception as e:
                if _is_quota_error(e):
                    last_error = e
                    continue
                raise

        raise last_error or RuntimeError("All providers failed")

    async def _call(
        self,
        provider: str,
        model: str,
        messages: list[dict],
        system: str,
        image_bytes: Optional[bytes],
        image_mime: str,
    ) -> tuple[str, int]:
        if provider == "gemini":
            return await self._gemini(model, messages, system, image_bytes, image_mime)
        return await self._openai_compat_http(provider, model, messages, system, image_bytes, image_mime)

    async def _gemini(
        self,
        model: str,
        messages: list[dict],
        system: str,
        image_bytes: Optional[bytes],
        image_mime: str,
    ) -> tuple[str, int]:
        gmodel = genai.GenerativeModel(
            model_name=model,
            system_instruction=system if system else None,
        )

        history = []
        for msg in messages[:-1]:
            role = "user" if msg["role"] == "user" else "model"
            if history and history[-1]["role"] == role:
                history[-1]["parts"][0] += "\n" + msg["content"]
            else:
                history.append({"role": role, "parts": [msg["content"]]})

        chat = gmodel.start_chat(history=history)
        last_content = messages[-1]["content"] if messages else ""

        if image_bytes:
            import PIL.Image
            import io
            img = PIL.Image.open(io.BytesIO(image_bytes))
            response = await chat.send_message_async([last_content or "請描述這張圖片", img])
        else:
            response = await chat.send_message_async(last_content)

        tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            tokens = response.usage_metadata.total_token_count or 0
        return response.text, tokens

    async def _openai_compat_http(
        self,
        provider: str,
        model: str,
        messages: list[dict],
        system: str,
        image_bytes: Optional[bytes],
        image_mime: str,
    ) -> tuple[str, int]:
        """Direct HTTP call to OpenAI-compatible APIs using aiohttp (no openai SDK)."""
        cfg = self.provider_config[provider]
        base_url = cfg["base_url"].rstrip("/")
        url = f"{base_url}/chat/completions"

        formatted = []
        if system:
            formatted.append({"role": "system", "content": system})

        for i, msg in enumerate(messages):
            is_last = i == len(messages) - 1
            if is_last and image_bytes and msg["role"] == "user":
                b64 = base64.b64encode(image_bytes).decode()
                formatted.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": msg["content"] or "請描述這張圖片"},
                        {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{b64}"}},
                    ],
                })
            else:
                formatted.append({"role": msg["role"], "content": msg["content"]})

        headers = {
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
            **cfg.get("headers", {}),
        }
        payload = {
            "model": model,
            "messages": formatted,
            "max_tokens": 2048,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    if any(kw in text.lower() for kw in QUOTA_KEYWORDS):
                        raise RuntimeError(f"quota error: {text[:200]}")
                    raise RuntimeError(f"HTTP {resp.status}: {text[:200]}")
                data = await resp.json()

        content = data["choices"][0]["message"]["content"] or ""
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return content, tokens

    async def transcribe(self, audio_path: str) -> str:
        """Transcribe audio using Gemini."""
        if not GOOGLE_API_KEY:
            raise RuntimeError("語音轉錄需要 Google API Key（Gemini 原生支援音訊）")
        return await asyncio.to_thread(self._gemini_transcribe_sync, audio_path)

    def _gemini_transcribe_sync(self, audio_path: str) -> str:
        audio_file = genai.upload_file(audio_path)
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content([
            "請將這段語音轉錄成文字，只輸出轉錄的文字，不加任何解釋。",
            audio_file,
        ])
        try:
            genai.delete_file(audio_file.name)
        except Exception:
            pass
        return response.text


ai_manager = AIManager()
