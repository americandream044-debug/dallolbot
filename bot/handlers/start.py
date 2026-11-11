"""Public commands and subscription confirmation."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

from bot.config import Settings
from bot.db.repo import Repo
from bot.ui.fx import boot_sequence
from bot.ui.keyboards import subscription_keyboard, user_keyboard
from bot.ui.texts import subscription_text, welcome

router = Router(name="public_start")


@router.message(CommandStart())
async def cmd_start(message: Message, settings: Settings, repo: Repo, state: FSMContext) -> None:
    """Welcome an admin or a subscribed public user."""
    await state.clear()
    parts = (message.text or "").split(maxsplit=1)
    source = parts[1][:64] if len(parts) > 1 else None
    await repo.upsert_user(message.from_user.id, message.from_user.username, message.from_user.first_name or "", source)
    if settings.is_admin(message.from_user.id):
        sent = await message.answer("<pre>[ SYSTEM ] DASTURLASH & AI\n[ INIT  ] Boot sequence...</pre>")
        enabled = await repo.get_setting("effects", "1") == "1"
        await boot_sequence(sent, enabled)
        from bot.handlers.admin.panel import render_panel
        await render_panel(sent, repo)
        return
    custom = await repo.get_setting("welcome_text", "Xush kelibsiz!")
    await message.answer(welcome(message.from_user.first_name or "do'st", custom), reply_markup=user_keyboard())


@router.message(Command("help"))
async def cmd_help(message: Message, settings: Settings, repo: Repo) -> None:
    """Expose only public commands and support entry point."""
    if settings.is_admin(message.from_user.id):
        from bot.handlers.admin.panel import render_panel
        sent = await message.answer("<pre>[ HELP ] Admin konsoliga yo'naltirilmoqda...</pre>")
        await render_panel(sent, repo)
    else:
        await message.answer("<b>Dasturlash & AI</b>\nFaqat /start va /help buyruqlari ochiq. Adminga murojaat yuborish uchun tugmani bosing.", reply_markup=user_keyboard())


@router.message(Command("admin"))
async def hidden_admin_command(message: Message, settings: Settings, repo: Repo) -> None:
    """Keep /admin indistinguishable from an unknown command for non-admins."""
    if not settings.is_admin(message.from_user.id):
        await message.answer("Buyruq topilmadi")
        return
    from bot.handlers.admin.panel import render_panel
    sent = await message.answer("<pre>[ ACCESS GRANTED ]</pre>")
    await render_panel(sent, repo)


@router.callback_query(lambda c: c.data == "sub:check")
async def check_subscription(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    """Return to the public welcome screen after middleware confirmed membership."""
    await callback.answer("Obuna tasdiqlandi ✅")
    custom = await repo.get_setting("welcome_text", "Xush kelibsiz!")
    await callback.message.edit_text(welcome(callback.from_user.first_name or "do'st", custom), reply_markup=user_keyboard())


@router.chat_member()
async def channel_member_event(event: ChatMemberUpdated, settings: Settings, repo: Repo) -> None:
    """Record channel join and leave events for churn reporting."""
    if str(event.chat.id) != str(settings.channel_id):
        return
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    active = {"member", "administrator", "creator"}
    old_active, new_active = old_status in active, new_status in active
    if old_active == new_active:
        return
    event_type = "channel_join" if new_active else "channel_leave"
    await repo.add_event(event.new_chat_member.user.id, event_type, {"username": event.new_chat_member.user.username})

