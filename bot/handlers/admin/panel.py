"""Admin home screen and protected section navigation."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.db.repo import Repo
from bot.middlewares.admin_only import require_admin
from bot.ui.keyboards import admin_menu_keyboard
from bot.ui.texts import main_menu_text

router = Router(name="admin_panel")


async def render_panel(message: Message, repo: Repo) -> None:
    """Render dashboard into the given message, replacing its previous content."""
    stats = await repo.get_stats()
    text = main_menu_text(stats)
    try:
        await message.edit_text(text, reply_markup=admin_menu_keyboard())
    except Exception:
        await message.answer(text, reply_markup=admin_menu_keyboard())


@router.message(Command("admin"))
async def admin_command(message: Message, settings: Settings, repo: Repo, state: FSMContext) -> None:
    if not settings.is_admin(message.from_user.id):
        await message.answer("Buyruq topilmadi")
        return
    await state.clear()
    await render_panel(message, repo)
    await repo.audit(message.from_user.id, "open_admin_panel")


@router.callback_query(lambda c: c.data == "admin:home")
async def home_callback(callback: CallbackQuery, settings: Settings, repo: Repo, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await callback.answer()
    await state.clear()
    await render_panel(callback.message, repo)




@router.message(Command("cancel"))
async def cancel_admin_flow(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Amal bekor qilindi. Admin menyu: /admin")
