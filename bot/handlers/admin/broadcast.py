"""Opt-in user broadcast with audience segments, cancellation, and rate limits."""
from __future__ import annotations

import asyncio
import html
import time

from aiogram import Bot, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import Settings
from bot.db.repo import Repo
from bot.middlewares.admin_only import require_admin
from bot.ui.keyboards import back_home_keyboard, confirm_keyboard
from bot.ui.theme import terminal_header, progress_bar

router = Router(name="admin_broadcast")
_cancel_events: dict[int, asyncio.Event] = {}


class BroadcastStates(StatesGroup):
    compose = State()
    choose_source = State()


def _get_media(message: Message) -> tuple[str | None, str | None, str]:
    if message.photo:
        return "photo", message.photo[-1].file_id, message.caption or ""
    if message.video:
        return "video", message.video.file_id, message.caption or ""
    if message.document:
        return "document", message.document.file_id, message.caption or ""
    return None, None, message.text or ""


@router.callback_query(lambda c: c.data == "admin:broadcast")
async def broadcast_entry(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await state.clear()
    await state.set_state(BroadcastStates.compose)
    await callback.answer()
    await callback.message.edit_text(f"{terminal_header('BROADCAST CONSOLE')}\n\nYuboriladigan matnni yoki foto/video/hujjat + caption yuboring. Keyin auditoriyani tanlaysiz.", reply_markup=back_home_keyboard())


@router.message(BroadcastStates.compose)
async def broadcast_compose(message: Message, state: FSMContext) -> None:
    media_type, file_id, text = _get_media(message)
    if not text.strip() and not file_id:
        await message.answer("Matn yoki media yuboring.")
        return
    if len(text) > 3500:
        await message.answer("Matn 3500 belgidan oshmasligi kerak.")
        return
    await state.update_data(text=text, media_type=media_type, file_id=file_id)
    await state.set_state(None)
    b = InlineKeyboardBuilder()
    for label, segment in (("👥 Barcha", "all"), ("🟢 Faol · 7 kun", "active7"), ("🆕 Yangi · 7 kun", "new7"), ("🌙 Faol emas · 30+ kun", "inactive30"), ("🔗 Manba bo‘yicha", "source")):
        b.button(text=label, callback_data=f"broadcast:segment:{segment}")
    b.button(text="❌ Bekor", callback_data="admin:home")
    b.adjust(1)
    await message.answer(f"<b>PREVIEW</b>\n\n{html.escape(text[:1000])}\n\nAuditoriyani tanlang:", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("broadcast:segment:"))
async def choose_segment(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    segment = callback.data.split(":")[2]
    if segment == "source":
        await state.set_state(BroadcastStates.choose_source)
        await callback.answer()
        await callback.message.edit_text("Qaysi referral manbasiga yuborilsin? Source code yuboring:")
        return
    await state.update_data(segment=segment, source=None)
    data = await state.get_data()
    ids = await repo.get_segment_users(segment)
    await state.update_data(total=len(ids))
    await callback.answer()
    label = {"all": "barcha", "active7": "7 kunda faol", "new7": "7 kunda yangi", "inactive30": "30 kundan ortiq faol bo‘lmagan"}.get(segment, segment)
    await callback.message.edit_text(f"📢 Auditoriya: <b>{label}</b>\nQabul qiluvchilar: <b>{len(ids)}</b>\n\nYuborishni tasdiqlaysizmi?", reply_markup=confirm_keyboard("broadcast:confirm", "admin:broadcast"))


@router.message(BroadcastStates.choose_source)
async def source_segment(message: Message, state: FSMContext, repo: Repo) -> None:
    source = (message.text or "").strip()
    if not source or len(source) > 64:
        await message.answer("Source code 1–64 belgi bo‘lsin.")
        return
    ids = await repo.get_segment_users("source", source)
    await state.update_data(segment="source", source=source, total=len(ids))
    await state.set_state(None)
    await message.answer(f"Manba: <code>{html.escape(source)}</code>\nQabul qiluvchilar: <b>{len(ids)}</b>\nTasdiqlash uchun:", reply_markup=confirm_keyboard("broadcast:confirm", "admin:broadcast"))


@router.callback_query(lambda c: c.data == "broadcast:confirm")
async def confirm_broadcast(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo, bot: Bot) -> None:
    if not await require_admin(callback, settings):
        return
    data = await state.get_data()
    segment = str(data.get("segment", "all"))
    source = data.get("source")
    text = str(data.get("text", ""))
    media_type = data.get("media_type")
    file_id = data.get("file_id")
    users = await repo.get_segment_users(segment, source)
    broadcast_id = await repo.create_broadcast(text, segment + (f":{source}" if source else ""), len(users), media_type, file_id)
    cancel = asyncio.Event()
    _cancel_events[broadcast_id] = cancel
    await callback.answer("Broadcast boshlandi.")
    await callback.message.edit_text(f"📢 <b>BROADCAST #{broadcast_id}</b>\n<pre>{progress_bar(0)}</pre>\n0 / {len(users)}", reply_markup=InlineKeyboardBuilder().button(text="⛔ To‘xtatish", callback_data=f"broadcast:cancel:{broadcast_id}").as_markup())
    status = callback.message
    sent = failed = blocked = 0
    started = time.monotonic()
    last_progress_edit = 0.0

    async def deliver(user_id: int) -> None:
        if media_type == "photo" and file_id:
            await bot.send_photo(user_id, file_id, caption=html.escape(text)[:1024])
        elif media_type == "video" and file_id:
            await bot.send_video(user_id, file_id, caption=html.escape(text)[:1024])
        elif media_type == "document" and file_id:
            await bot.send_document(user_id, file_id, caption=html.escape(text)[:1024])
        else:
            await bot.send_message(user_id, html.escape(text))

    for index, user_id in enumerate(users, 1):
        if cancel.is_set():
            break
        try:
            await deliver(user_id)
            sent += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(float(exc.retry_after) + 0.2)
            try:
                await deliver(user_id)
                sent += 1
            except TelegramForbiddenError:
                blocked += 1
                await repo.db.execute("UPDATE users SET is_blocked=1 WHERE id=?", (user_id,))
            except Exception:
                failed += 1
        except TelegramForbiddenError:
            blocked += 1
            await repo.db.execute("UPDATE users SET is_blocked=1 WHERE id=?", (user_id,))
        except TelegramBadRequest:
            failed += 1
        except Exception:
            failed += 1
        now_progress = time.monotonic()
        if (now_progress - last_progress_edit >= 1.0 or index == len(users)):
            last_progress_edit = now_progress
            pct = int(index / max(1, len(users)) * 100)
            elapsed = max(0.1, time.monotonic() - started)
            try:
                await status.edit_text(f"📢 <b>BROADCAST #{broadcast_id}</b>\n<pre>{progress_bar(pct)}</pre>\nJami: {index}/{len(users)}\n🟢 {sent} · 🔴 {failed} · 🚫 {blocked}\nTezlik: {index/elapsed:.1f} msg/s", reply_markup=InlineKeyboardBuilder().button(text="⛔ To‘xtatish", callback_data=f"broadcast:cancel:{broadcast_id}").as_markup())
            except Exception:
                pass
        # Telegram's practical bot-to-user throughput is kept under 25 messages per second.
        await asyncio.sleep(0.041)
    cancelled = cancel.is_set()
    await repo.update_broadcast(broadcast_id, sent, failed, blocked, cancelled)
    await repo.audit(callback.from_user.id, "broadcast_finished", f"id={broadcast_id}; sent={sent}; failed={failed}; blocked={blocked}; cancelled={cancelled}")
    _cancel_events.pop(broadcast_id, None)
    await state.clear()
    await status.edit_text(f"{'⛔' if cancelled else '🟢'} <b>BROADCAST #{broadcast_id} YAKUNLANDI</b>\nJami: {len(users)}\n✅ Yuborildi: {sent}\n🔴 Xato: {failed}\n🚫 Bloklagan: {blocked}\n{'Bekor qilingan.' if cancelled else '[ DEPLOYED ]'}", reply_markup=back_home_keyboard())


@router.callback_query(lambda c: c.data and c.data.startswith("broadcast:cancel:"))
async def cancel_broadcast(callback: CallbackQuery, settings: Settings) -> None:
    if not await require_admin(callback, settings):
        return
    broadcast_id = int(callback.data.split(":")[2])
    event = _cancel_events.get(broadcast_id)
    if event:
        event.set()
        await callback.answer("To‘xtatish so‘rovi qabul qilindi.")
    else:
        await callback.answer("Broadcast allaqachon yakunlangan.", show_alert=False)
