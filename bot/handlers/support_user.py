"""Public support conversation flow with ticket persistence and rate limits."""
from __future__ import annotations

import html
import time
from datetime import datetime, timezone
from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.db.repo import Repo, utc_now
from bot.ui.keyboards import user_keyboard
from bot.ui.theme import terminal_header

router = Router(name="support_user")
_user_last_message: dict[int, float] = {}


class SupportStates(StatesGroup):
    waiting = State()


def _message_payload(message: Message) -> tuple[str, str, str | None]:
    if message.text:
        return "text", message.text, None
    if message.photo:
        return "photo", message.caption or "", message.photo[-1].file_id
    if message.voice:
        return "voice", message.caption or "", message.voice.file_id
    if message.document:
        return "document", message.caption or "", message.document.file_id
    if message.video:
        return "video", message.caption or "", message.video.file_id
    if message.audio:
        return "audio", message.caption or "", message.audio.file_id
    if message.animation:
        return "animation", message.caption or "", message.animation.file_id
    return "unsupported", "", None


async def _send_to_admins(bot: Bot, settings: Settings, ticket_id: int, user_message: Message, kind: str, caption: str, file_id: str | None, username: str | None, first_name: str, source: str | None) -> None:
    mention = f"@{html.escape(username)}" if username else html.escape(first_name or "Foydalanuvchi")
    header = (
        f"💬 <b>YANGI MUROJAAT #{ticket_id}</b>\n"
        f"👤 {mention}\n🆔 <code>{user_message.from_user.id}</code>\n"
        f"📅 {utc_now()}\n🔗 Manba: <code>{html.escape(source or 'direct')}</code>\n"
        "🏷 Teg: savol"
    )
    from bot.ui.keyboards import ticket_card_keyboard
    for admin_id in settings.admin_ids:
        await bot.send_message(admin_id, header, reply_markup=ticket_card_keyboard(ticket_id))
        if kind == "text":
            await bot.send_message(admin_id, f"<blockquote>{html.escape(caption)}</blockquote>")
        elif file_id:
            await bot.copy_message(admin_id, user_message.chat.id, user_message.message_id)


@router.callback_query(lambda c: c.data == "support:new")
async def begin_support(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(SupportStates.waiting)
    await callback.message.edit_text(
        f"{terminal_header('SECURE MESSAGE')}\n\nAdminga yubormoqchi bo‘lgan xabaringizni yozing yoki foto, ovoz, hujjat yoxud video yuboring.\n\nBekor qilish: /cancel"
    )


@router.message(Command("cancel"))
async def cancel_support(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Amal bekor qilindi.", reply_markup=user_keyboard())


@router.message(SupportStates.waiting)
async def receive_support_message(message: Message, state: FSMContext, bot: Bot, settings: Settings, repo: Repo) -> None:
    user_id = message.from_user.id
    now = time.monotonic()
    cooldown = int(await repo.get_setting("anti_spam_seconds", str(settings.support_cooldown)))
    last = _user_last_message.get(user_id, 0.0)
    remaining = max(0, int(cooldown - (now - last))) if last else 0
    latest = await repo.db.fetchone(
        "SELECT tm.created_at FROM ticket_messages tm JOIN tickets t ON t.id=tm.ticket_id WHERE t.user_id=? AND tm.sender='user' ORDER BY tm.id DESC LIMIT 1",
        (user_id,),
    )
    if latest and remaining == 0:
        try:
            last_dt = datetime.fromisoformat(str(latest["created_at"]))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            remaining = max(0, cooldown - int((datetime.now(timezone.utc) - last_dt).total_seconds()))
        except ValueError:
            remaining = 0
    if remaining > 0:
        await message.answer(f"⏳ Yangi xabar yuborishdan oldin {remaining} soniya kuting.")
        return
    if await repo.is_banned(user_id):
        return

    kind, content, file_id = _message_payload(message)
    if kind == "unsupported":
        await message.answer("Bu format qo‘llab-quvvatlanmaydi. Matn, foto, ovoz, hujjat yoki video yuboring.")
        return
    if len(content) > settings.max_message_length:
        await message.answer(f"Xabar juda uzun. Maksimum: {settings.max_message_length} belgi.")
        return

    ticket = await repo.get_open_ticket(user_id)
    if ticket:
        ticket_id = int(ticket["id"])
    else:
        if await repo.count_user_tickets_today(user_id) >= 20:
            await message.answer("Bugun yangi murojaatlar limiti tugadi. Mavjud murojaatingizga javob yozishingiz mumkin.")
            return
        ticket_id = await repo.create_ticket(user_id)
        await repo.add_event(user_id, "ticket_created", {"ticket_id": ticket_id})

    await repo.add_ticket_message(ticket_id, "user", kind, content, file_id)
    if await repo.get_setting("notify_new_ticket", "1") == "1":
        await _send_to_admins(bot, settings, ticket_id, message, kind, content, file_id, message.from_user.username, message.from_user.first_name or "", (await repo.get_user(user_id) or {}).get("source"))
    _user_last_message[user_id] = now
    await state.set_state(SupportStates.waiting)
    await state.update_data(ticket_id=ticket_id)
    await message.answer(f"🟢 <code>[ SENT ]</code> #{ticket_id} raqamli murojaat qabul qilindi.\nAdmin javobini shu bot orqali olasiz. Shu murojaatda davom etishingiz mumkin; yakunlash uchun /cancel.", reply_markup=user_keyboard())


@router.message()
async def public_unknown_message(message: Message, settings: Settings) -> None:
    if settings.is_admin(message.from_user.id):
        return
    if message.text and message.text.startswith("/"):
        await message.answer("Buyruq topilmadi")
    else:
        await message.answer("Adminga xabar yuborish uchun /start tugmasidan foydalaning.", reply_markup=user_keyboard())

@router.callback_query()
async def unknown_callback(callback: CallbackQuery, settings: Settings) -> None:
    """Handle stale or forged callbacks after all public feature callbacks."""
    data = callback.data or ""
    protected = ("admin:", "ai:", "post:", "schedule:", "ticket:", "tickets:", "analytics:", "broadcast:", "users:", "tools:", "settings:")
    if not settings.is_admin(callback.from_user.id) and data.startswith(protected):
        await callback.answer("Buyruq topilmadi", show_alert=False)
    elif settings.is_admin(callback.from_user.id):
        await callback.answer("Bu tugma eskirgan. Menyuni qayta oching.", show_alert=False)
    else:
        await callback.answer()
