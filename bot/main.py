"""Bot startup, dependency wiring, channel permission checks, and shutdown."""
from __future__ import annotations

import asyncio
import html
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent
from loguru import logger

from bot.ai import client as ai_client
from bot.config import ConfigError, Settings, load_settings
from bot.db.database import Database
from bot.db.repo import Repo
from bot.handlers.admin import router as admin_router
from bot.handlers.reactions import router as reaction_router
from bot.handlers.start import router as start_router
from bot.handlers.support_user import router as support_router
from bot.middlewares.events_logger import EventsLoggerMiddleware
from bot.middlewares.subscription import SubscriptionMiddleware
from bot.middlewares.throttle import ThrottleMiddleware
from bot.services.analytics_service import AnalyticsService
from bot.services.backup_service import BackupService
from bot.services.post_service import PostService
from bot.services.scheduler_service import SchedulerService
from bot.handlers.admin.analytics import send_weekly_report


BANNER = r"""
╔══════════════════════════════════════════════════════╗
║  DASTURLASH & AI CONTROL BOT                         ║
║  root@dasturlash:~$ boot --secure --async             ║
╚══════════════════════════════════════════════════════╝
"""


async def verify_channel_permissions(bot: Bot, settings: Settings) -> None:
    """Fail fast unless the bot can publish, edit, and delete channel posts."""
    try:
        chat = await bot.get_chat(settings.channel_id)
        member = await bot.get_chat_member(settings.channel_id, bot.id)
        status = getattr(member.status, "value", str(member.status))
        is_owner = status == "creator"
        can_post = is_owner or bool(getattr(member, "can_post_messages", False))
        can_edit = is_owner or bool(getattr(member, "can_edit_messages", False))
        can_delete = is_owner or bool(getattr(member, "can_delete_messages", False))
        if not (status in {"administrator", "creator"} and can_post and can_edit and can_delete):
            raise RuntimeError(
                "Bot kanal administratori emas yoki huquqlari yetarli emas. "
                "@dasturlash_ai kanalida botga Administrator rolini bering va "
                "'Post messages', 'Edit messages', 'Delete messages' ruxsatlarini yoqing."
            )
        logger.info("Channel access verified: {} ({})", chat.title, settings.channel_id)
    except Exception as exc:
        raise RuntimeError(
            f"Kanalga kirish tekshiruvi muvaffaqiyatsiz: {exc}. "
            "Botni kanalga administrator qiling, CHANNEL_ID ni tekshiring va post/edit/delete huquqlarini yoqing."
        ) from exc


async def main() -> None:
    """Create application services, restore jobs, start polling, and shut down cleanly."""
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"[ CONFIG ERROR ] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    Path("logs").mkdir(exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level=settings.log_level, colorize=True)
    logger.add("logs/bot.log", rotation="10 MB", retention="14 days", compression="zip", level=settings.log_level, enqueue=True)
    print(BANNER)

    db = Database(settings.db_path)
    await db.initialize()
    repo = Repo(db)
    ai_client.configure(settings)

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # Runtime dependency injection for handlers and middlewares.
    dp["settings"] = settings
    dp["repo"] = repo

    events = EventsLoggerMiddleware(repo, settings)
    subscription = SubscriptionMiddleware(settings, repo)
    dp.message.outer_middleware(events)
    dp.callback_query.outer_middleware(events)
    dp.message.outer_middleware(subscription)
    dp.callback_query.outer_middleware(subscription)
    dp.message.outer_middleware(ThrottleMiddleware(settings))

    posts = PostService(bot, settings, repo)
    scheduler = SchedulerService(bot, settings, repo, posts)
    analytics = AnalyticsService(repo)
    backup = BackupService(bot, settings)
    dp["posts"] = posts
    dp["scheduler"] = scheduler
    dp["analytics"] = analytics
    dp["backup"] = backup

    # Protected admin features are registered before public fallbacks.
    dp.include_router(admin_router)
    dp.include_router(start_router)
    dp.include_router(support_router)
    dp.include_router(reaction_router)

    @dp.errors()
    async def global_error_handler(event: ErrorEvent) -> bool:
        logger.exception("Unhandled update error: {}", event.exception)
        error_text = html.escape(f"{type(event.exception).__name__}: {str(event.exception)[:250]}")
        for admin_id in settings.admin_ids:
            try:
                await bot.send_message(admin_id, f"🔴 <b>[ SYSTEM ERROR ]</b>\n<code>{error_text}</code>")
            except Exception:
                pass
        return True

    try:
        await verify_channel_permissions(bot, settings)
    except RuntimeError as exc:
        logger.error(str(exc))
        for admin_id in settings.admin_ids:
            try:
                await bot.send_message(admin_id, f"🔴 <b>[ CHANNEL PERMISSION ERROR ]</b>\n{html.escape(str(exc))}")
            except Exception:
                pass
        await ai_client.close()
        await bot.session.close()
        raise SystemExit(3) from exc

    scheduler.start()
    restored = await scheduler.restore()
    logger.info("Restored {} scheduled posts", restored)

    async def weekly_report_job() -> None:
        if await repo.get_setting("weekly_report", "1") == "1":
            await send_weekly_report(bot, settings, repo)

    scheduler.scheduler.add_job(
        backup.send_backup,
        CronTrigger(hour=3, minute=0, timezone=ZoneInfo(settings.timezone)),
        id="daily_backup", replace_existing=True, misfire_grace_time=3600,
    )
    report_time = await repo.get_setting("weekly_report_time", "20:00")
    try:
        report_hour, report_minute = [int(x) for x in report_time.split(":", 1)]
    except (ValueError, TypeError):
        report_hour, report_minute = 20, 0
    report_day = await repo.get_setting("weekly_report_day", "sun")
    if report_day not in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}:
        report_day = "sun"
    scheduler.scheduler.add_job(
        weekly_report_job,
        CronTrigger(day_of_week=report_day, hour=report_hour, minute=report_minute, timezone=ZoneInfo(settings.timezone)),
        id="weekly_report", replace_existing=True, misfire_grace_time=7200,
    )

    me = await bot.get_me()
    logger.info("Bot started as @{}; timezone={}; admins={}", me.username, settings.timezone, len(settings.admin_ids))
    allowed_updates = ["message", "edited_message", "callback_query", "chat_member", "message_reaction_count"]
    try:
        await dp.start_polling(bot, allowed_updates=allowed_updates, close_bot_session=False)
    finally:
        scheduler.shutdown()
        await ai_client.close()
        await bot.session.close()
        logger.info("Bot shutdown completed cleanly")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[ SHUTDOWN ] Bot stopped by operator.")
