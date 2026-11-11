"""Business-level AI service: usage cap, prompts, and error translation."""
from __future__ import annotations

from pathlib import Path

from bot.ai import client
from bot.config import Settings
from bot.db.repo import Repo


class AIService:
    def __init__(self, settings: Settings, repo: Repo) -> None:
        self.settings = settings
        self.repo = repo

    async def generate(self, system: str, user: str, temperature: float = 0.7) -> str:
        cap = int(await self.repo.get_setting("daily_ai_cap", "30"))
        usage = await self.repo.ai_usage_today()
        if cap > 0 and usage["requests"] >= cap:
            raise RuntimeError(f"Bugungi AI so‘rovlari limiti ({cap}) tugadi. Limitni Sozlamalar bo‘limida o‘zgartiring.")
        result = await client.generate(system, user, temperature)
        await self.repo.record_ai_usage(len(user), len(result))
        return result

    async def prompt(self, category: str, task: str) -> str:
        system = (Path(__file__).resolve().parents[1] / "prompts" / "prompt_engineer.txt").read_text(encoding="utf-8")
        return await self.generate(system, f"Kategoriya: {category}\nVazifa: {task}", 0.65)

    async def write_post_variants(self, topic: str) -> list[str]:
        system = (Path(__file__).resolve().parents[1] / "prompts" / "post_writer.txt").read_text(encoding="utf-8")
        raw = await self.generate(system, f"Mavzu yoki manba matni:\n{topic}\n\nUchta variantni JSON massivda qaytaring.", 0.85)
        import json
        try:
            data = json.loads(raw[raw.find("["):raw.rfind("]") + 1])
            variants = [str(x) for x in data if str(x).strip()]
        except Exception:
            variants = [part.strip() for part in raw.split("\n\n") if len(part.strip()) > 25]
        return (variants + [raw, raw, raw])[:3]
