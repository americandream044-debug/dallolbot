"""Aggregated analytics and cohort calculations."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from bot.db.repo import Repo


class AnalyticsService:
    def __init__(self, repo: Repo) -> None:
        self.repo = repo

    async def dashboard(self) -> dict[str, Any]:
        stats = await self.repo.get_stats()
        detail = await self.repo.get_analytics()
        return {"summary": stats, **detail}

    async def retention(self) -> dict[str, float]:
        now = datetime.now(timezone.utc)
        result: dict[str, float] = {}
        for days in (1, 7, 30):
            cohort = (now - timedelta(days=days + 1)).date().isoformat()
            target_day = (datetime.fromisoformat(cohort) + timedelta(days=days)).date().isoformat()
            total = await self.repo.db.fetchone("SELECT COUNT(*) n FROM users WHERE date(joined_at)=?", (cohort,))
            active = await self.repo.db.fetchone(
                "SELECT COUNT(DISTINCT u.id) n FROM users u JOIN events e ON e.user_id=u.id WHERE date(u.joined_at)=? AND date(e.ts,'unixepoch')=?",
                (cohort, target_day),
            )
            n_total = int(total["n"] if total else 0)
            n_active = int(active["n"] if active else 0)
            result[f"d{days}"] = round(100 * n_active / n_total, 1) if n_total else 0.0
        return result

    async def retention_cohorts(self, limit: int = 8) -> list[dict[str, Any]]:
        """Return daily cohorts with D1/D7/D30 return rates where mature."""
        today = datetime.now(timezone.utc).date()
        cohorts = await self.repo.db.fetchall(
            "SELECT date(joined_at) day,COUNT(*) total FROM users "
            "WHERE date(joined_at)>=date('now','-45 day') GROUP BY date(joined_at) "
            "ORDER BY day DESC LIMIT ?",
            (max(1, min(31, limit)),),
        )
        result: list[dict[str, Any]] = []
        for cohort in cohorts:
            cohort_day = datetime.fromisoformat(str(cohort["day"])).date()
            entry: dict[str, Any] = {"day": str(cohort["day"]), "total": int(cohort["total"])}
            for days in (1, 7, 30):
                target = cohort_day + timedelta(days=days)
                if target > today:
                    entry[f"d{days}"] = None
                    continue
                active = await self.repo.db.fetchone(
                    "SELECT COUNT(DISTINCT u.id) n FROM users u JOIN events e ON e.user_id=u.id "
                    "WHERE date(u.joined_at)=? AND date(e.ts,'unixepoch')=?",
                    (cohort["day"], target.isoformat()),
                )
                count = int(active["n"] if active else 0)
                entry[f"d{days}"] = round(100 * count / int(cohort["total"]), 1) if cohort["total"] else 0.0
            result.append(entry)
        return result

    async def compact_json(self) -> str:
        data = await self.dashboard()
        data["retention"] = await self.retention()
        return json.dumps(data, ensure_ascii=False, default=str)[:12000]

    async def best_hours(self) -> list[dict[str, Any]]:
        data = await self.repo.get_analytics()
        return sorted(data["active_hours"], key=lambda x: x["n"], reverse=True)[:5]

    async def support_overview(self) -> dict[str, Any]:
        return await self.repo.ticket_metrics()
