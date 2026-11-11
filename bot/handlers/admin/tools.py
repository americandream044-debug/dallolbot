"""Operational tools: backup, cleanup, audit, health, referrals, quick announcements."""
from __future__ import annotations

import csv
import html
import io
import secrets
import string
from datetime import datetime

from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.ai.client import healthcheck as ai_healthcheck
from bot.config import Settings
from bot.db.database import Database
from bot.db.repo import Repo
from bot.middlewares.admin_only import require_admin
from bot.services.backup_service import BackupService
from bot.ui.keyboards import back_home_keyboard
from bot.ui.theme import terminal_header

router = Router(name="admin_tools")


class ToolStates(StatesGroup):
    referral_label = State()
    announcement = State()


@router.callback_query(lambda c: c.data == "admin:tools")
async def tools_home(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await state.clear()
    b = InlineKeyboardBuilder()
    for label, key in (("💾 Backup", "tools:backup"), ("🧹 Cleanup", "tools:cleanup"), ("📜 Audit log", "tools:audit"), ("🩺 Health check", "tools:health"), ("🔗 Referal havola", "tools:referral"), ("📣 Kanal e'loni", "tools:announcement"), ("📤 CSV eksport", "tools:export")):
        b.button(text=label, callback_data=key)
    b.button(text="🏠 Menyu", callback_data="admin:home")
    b.adjust(2, 2, 2, 1)
    await callback.answer()
    await callback.message.edit_text(f"{terminal_header('OPS / TOOLBOX')}\n\nServer va kanal operatsiyalari:", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data == "tools:backup")
async def backup_now(callback: CallbackQuery, settings: Settings, repo: Repo, bot: Bot) -> None:
    if not await require_admin(callback, settings):
        return
    await callback.answer("Backup tayyorlanmoqda...")
    try:
        await BackupService(bot, settings).send_backup(callback.from_user.id)
        await repo.audit(callback.from_user.id, "manual_backup")
        await callback.message.edit_text("🟢 <b>[ BACKUP COMPLETE ]</b>\nSQLite nusxasi shaxsiy chatga yuborildi.", reply_markup=back_home_keyboard("admin:tools"))
    except Exception as exc:
        await callback.message.edit_text(f"🔴 Backup xatosi: {html.escape(str(exc)[:250])}", reply_markup=back_home_keyboard("admin:tools"))


@router.callback_query(lambda c: c.data == "tools:cleanup")
async def cleanup(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    result = await repo.cleanup(90)
    await repo.audit(callback.from_user.id, "cleanup", str(result))
    await callback.answer("Cleanup bajarildi.")
    await callback.message.edit_text(f"🧹 <b>CLEANUP</b>\nEski eventlar: {result['events_deleted']}\nEski draftlar: {result['old_drafts_deleted']}\nSaqlash muddati: 90 kun.", reply_markup=back_home_keyboard("admin:tools"))


@router.callback_query(lambda c: c.data == "tools:audit")
async def audit_log(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    rows = await repo.audit_tail(20)
    lines = [terminal_header("AUDIT LOG"), ""]
    lines += [f"<code>{html.escape(str(row['ts']))}</code> · <b>{row['admin_id']}</b> · {html.escape(row['action'])} · {html.escape(row['details'][:80])}" for row in rows]
    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=back_home_keyboard("admin:tools"))


@router.callback_query(lambda c: c.data == "tools:health")
async def health_check(callback: CallbackQuery, settings: Settings, repo: Repo, bot: Bot, scheduler) -> None:
    if not await require_admin(callback, settings):
        return
    await callback.answer("Tekshiruv...")
    db_ok = await Database(settings.db_path).integrity_check()
    ai_ok, ai_text = await ai_healthcheck()
    try:
        member = await bot.get_chat_member(settings.channel_id, bot.id)
        status_value = getattr(member.status, "value", str(member.status))
        channel_ok = status_value in {"administrator", "creator"} and bool(getattr(member, "can_post_messages", False))
        channel_text = "Admin + post ruxsati bor" if channel_ok else f"Status={status_value}; post ruxsatini bering"
    except Exception as exc:
        channel_ok, channel_text = False, str(exc)[:140]
    jobs = len(scheduler.scheduler.get_jobs())
    lines = [terminal_header("SYSTEM HEALTH"), "", f"DB: {'🟢' if db_ok == 'ok' else '🔴'} {html.escape(db_ok)}", f"AI: {'🟢' if ai_ok else '🔴'} {html.escape(ai_text)}", f"Channel: {'🟢' if channel_ok else '🔴'} {html.escape(channel_text)}", f"Scheduler jobs: <b>{jobs}</b>", f"Uptime: <code>{datetime.now(settings.tz):%Y-%m-%d %H:%M:%S}</code>"]
    await callback.message.edit_text("\n".join(lines), reply_markup=back_home_keyboard("admin:tools"))


@router.callback_query(lambda c: c.data == "tools:referral")
async def referral_start(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await state.set_state(ToolStates.referral_label)
    await callback.answer()
    await callback.message.edit_text("Referral havola uchun nom yuboring (masalan insta_story1):", reply_markup=back_home_keyboard("admin:tools"))


@router.message(ToolStates.referral_label)
async def referral_create(message: Message, state: FSMContext, repo: Repo, bot: Bot) -> None:
    label = (message.text or "").strip()
    allowed = string.ascii_letters + string.digits + "_"
    if not label or len(label) > 40 or any(ch not in allowed for ch in label):
        await message.answer("Faqat lotin harflari, raqam va _ belgisi; uzunligi 1–40.")
        return
    code = f"{label}_{secrets.token_hex(2)}"
    await repo.create_referral(code, label)
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={code}"
    await repo.audit(message.from_user.id, "referral_created", code)
    await state.clear()
    rows = await repo.referral_stats()
    report = [f"• <code>{html.escape(row['code'])}</code> — {int(row['users'])} foydalanuvchi" for row in rows[:12]]
    await message.answer(
        f"🔗 <b>TRACKED LINK</b>\n<code>{html.escape(link)}</code>\nSource: <code>{code}</code>\n\n<b>Referral statistikasi:</b>\n" + ("\n".join(report) if report else "Hozircha kirishlar yo‘q."),
        reply_markup=back_home_keyboard("admin:tools"),
    )


@router.callback_query(lambda c: c.data == "tools:announcement")
async def announcement_start(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await state.set_state(ToolStates.announcement)
    await callback.answer()
    await callback.message.edit_text("Kanalga AI ishlatmasdan yuboriladigan oddiy matnni kiriting (4096 belgigacha):", reply_markup=back_home_keyboard("admin:tools"))


@router.message(ToolStates.announcement)
async def announcement_send(message: Message, state: FSMContext, settings: Settings, repo: Repo, bot: Bot) -> None:
    text = (message.text or "").strip()
    if not text or len(text) > 4000:
        await message.answer("Matn 1–4000 belgi oralig‘ida bo‘lishi kerak.")
        return
    await state.clear()
    sent = await bot.send_message(settings.channel_id, html.escape(text))
    await repo.add_event(None, "post_published", {"quick_announcement": True, "message_id": sent.message_id})
    await repo.audit(message.from_user.id, "quick_channel_announcement", str(sent.message_id))
    await message.answer(f"🟢 Kanal e'loni yuborildi. Message ID: <code>{sent.message_id}</code>", reply_markup=back_home_keyboard("admin:tools"))


@router.callback_query(lambda c: c.data == "tools:export")
async def tools_export_menu(callback: CallbackQuery, settings: Settings) -> None:
    if not await require_admin(callback, settings):
        return
    b = InlineKeyboardBuilder()
    for table in ("users", "tickets", "posts", "events"):
        b.button(text=f"{table}.csv", callback_data=f"tools:export:{table}")
    b.button(text="⬅️ Orqaga", callback_data="admin:tools")
    b.adjust(2, 2, 1)
    await callback.answer()
    await callback.message.edit_text("Eksport jadvalini tanlang:", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("tools:export:"))
async def tools_export(callback: CallbackQuery, settings: Settings, repo: Repo, bot: Bot) -> None:
    if not await require_admin(callback, settings):
        return
    table = callback.data.split(":")[2]
    if table not in {"users", "tickets", "posts", "events"}:
        await callback.answer("Jadval noto‘g‘ri.", show_alert=True)
        return
    rows = await repo.export_rows(table)
    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    await bot.send_document(callback.from_user.id, BufferedInputFile(buffer.getvalue().encode("utf-8-sig"), filename=f"{table}.csv"), caption=f"{table}: {len(rows)} qator")
    await callback.answer("CSV yuborildi.")
