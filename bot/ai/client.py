"""Provider-neutral async AI client with bounded retries and timeouts."""
from __future__ import annotations

import asyncio
import random
from typing import Any

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from bot.config import Settings


class AIProviderError(RuntimeError):
    """Raised after all provider attempts have failed."""


_settings: Settings | None = None
_openai: AsyncOpenAI | None = None
_anthropic: AsyncAnthropic | None = None


def configure(settings: Settings) -> None:
    """Configure a shared provider client from validated environment settings."""
    global _settings, _openai, _anthropic
    _settings = settings
    if settings.ai_provider == "openai":
        _openai = AsyncOpenAI(api_key=settings.ai_api_key, timeout=45.0, max_retries=0)
        _anthropic = None
    else:
        _anthropic = AsyncAnthropic(api_key=settings.ai_api_key, timeout=45.0, max_retries=0)
        _openai = None


async def _request(system: str, user: str, temperature: float) -> str:
    if _settings is None:
        raise AIProviderError("AI provayderi ishga tushirilmagan.")
    if _settings.ai_provider == "openai" and _openai:
        response = await _openai.chat.completions.create(
            model=_settings.ai_model,
            temperature=max(0.0, min(1.5, temperature)),
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        content = response.choices[0].message.content or ""
        return content.strip()
    if _settings.ai_provider == "anthropic" and _anthropic:
        response = await _anthropic.messages.create(
            model=_settings.ai_model,
            max_tokens=4096,
            temperature=max(0.0, min(1.0, temperature)),
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "\n".join(block.text for block in response.content if getattr(block, "type", "") == "text").strip()
    raise AIProviderError("AI provayderi sozlamasi topilmadi.")


async def generate(system: str, user: str, temperature: float = 0.7) -> str:
    """Generate text with timeout and exponential backoff (maximum three attempts)."""
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            return await asyncio.wait_for(_request(system, user, temperature), timeout=50.0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                await asyncio.sleep((2 ** attempt) + random.uniform(0.0, 0.3))
    raise AIProviderError("AI hozir javob bera olmadi. API kalit, model va internet ulanishini tekshiring.") from last_error


async def healthcheck() -> tuple[bool, str]:
    """Make a tiny provider request for admin health checks."""
    try:
        text = await generate("Siz test yordamchisiz.", "Faqat OK deb yozing.", 0.0)
        return bool(text), "AI javob berdi" if text else "AI bo'sh javob qaytardi"
    except Exception as exc:
        return False, str(exc)[:180]


async def close() -> None:
    """Close the active SDK connection pool."""
    if _openai:
        await _openai.close()
    if _anthropic:
        await _anthropic.close()
