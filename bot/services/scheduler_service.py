"""Persistent scheduler facade backed by APScheduler 3.x and the posts table."""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from aiogram import Bot

from bot.config import Settings
from bot.db.repo import Repo
from bot.services.post_service import PostService


class SchedulerService:
    def __init__(self, bot: Bot, settings: Settings, repo: Repo, posts: PostService) -> None:
        self.bot = bot
        self.settings = settings
        self.repo = repo
        self.posts = posts
        self.scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.timezone))

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()

    async def schedule_post(self, post_id: int, run_at: datetime) -> None:
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=ZoneInfo(self.settings.timezone))
        self.remove_job(post_id)
        await self.repo.update_post(post_id, status="scheduled", scheduled_at=run_at.isoformat(), recurrence=None)
        self.scheduler.add_job(self._publish_job, DateTrigger(run_date=run_at), id=f"post_{post_id}", args=[post_id], replace_existing=True, misfire_grace_time=3600)

    async def schedule_recurring(self, post_id: int, day: str, hour: int, minute: int) -> None:
        self.remove_job(post_id)
        trigger = CronTrigger(day_of_week=day, hour=hour, minute=minute, timezone=ZoneInfo(self.settings.timezone))
        self.scheduler.add_job(self._publish_job, trigger, id=f"recurring_{post_id}", args=[post_id], replace_existing=True, misfire_grace_time=3600)
        from bot.db.repo import utc_now
        await self.repo.update_post(post_id, status="scheduled", recurrence=f"{day} {hour:02d}:{minute:02d}", scheduled_at=utc_now())

    async def restore(self) -> int:
        count = 0
        for post in await self.repo.scheduled_posts():
            post_id = int(post["id"])
            recurrence = post.get("recurrence")
            if recurrence:
                try:
                    day, clock = str(recurrence).split(maxsplit=1)
                    hour, minute = [int(x) for x in clock.split(":", 1)]
                    await self.schedule_recurring(post_id, day, hour, minute)
                    count += 1
                    continue
                except (ValueError, TypeError):
                    pass
            try:
                run_at = datetime.fromisoformat(str(post["scheduled_at"]))
                if run_at.tzinfo is None:
                    run_at = run_at.replace(tzinfo=ZoneInfo(self.settings.timezone))
                if run_at.timestamp() < datetime.now(ZoneInfo(self.settings.timezone)).timestamp():
                    run_at = datetime.now(ZoneInfo(self.settings.timezone))
                self.scheduler.add_job(self._publish_job, DateTrigger(run_date=run_at), id=f"post_{post_id}", args=[post_id], replace_existing=True, misfire_grace_time=3600)
                count += 1
            except (ValueError, TypeError):
                await self.repo.update_post(post_id, status="failed")
        return count

    async def _publish_job(self, post_id: int) -> None:
        try:
            message_id = await self.posts.publish(post_id)
            for admin_id in self.settings.admin_ids:
                await self.bot.send_message(admin_id, f"🟢 <b>[ DEPLOYED ✅ ]</b> #{post_id} post kanalga joylandi.\nMessage ID: <code>{message_id}</code>")
        except Exception as exc:
            await self.repo.update_post(post_id, status="failed")
            for admin_id in self.settings.admin_ids:
                try:
                    await self.bot.send_message(admin_id, f"🔴 <b>[ FAIL ]</b> #{post_id} post joylanmadi.\n<code>{str(exc)[:300]}</code>")
                except Exception:
                    pass

    def remove_job(self, post_id: int) -> bool:
        removed = False
        for job_id in (f"post_{post_id}", f"recurring_{post_id}"):
            try:
                self.scheduler.remove_job(job_id)
                removed = True
            except Exception:
                continue
        return removed

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
