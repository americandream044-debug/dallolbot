"""Admin user search, profile, ban controls, notes, segments, and export."""
from __future__ import annotations

import csv
import html
import io

from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import Settings
from bot.db.repo import Repo
from bot.middlewares.admin_only import require_admin
from bot.ui.keyboards import back_home_keyboard
from bot.ui.theme import terminal_header

router = Router(name="admin_users")


class UserStates(StatesGroup):
    search = State()
    note = State()


@router.callback_query(lambda c: c.data == "admin:users")
async def users_home(callback: CallbackQuery, settings: Settings, repo: Repo, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    total = await repo.count_users()
    active = await repo.db.fetchone("SELECT COUNT(*) n FROM users WHERE last_seen>=datetime('now','-7 day') AND is_banned=0")
    banned = await repo.db.fetchone("SELECT COUNT(*) n FROM users WHERE is_banned=1")
    new = await repo.db.fetchone("SELECT COUNT(*) n FROM users WHERE joined_at>=datetime('now','-7 day')")
    b = InlineKeyboardBuilder()
    b.button(text="🔎 Qidirish", callback_data="users:search")
    b.button(text="🚫 Ban qilinganlar", callback_data="users:banned")
    b.button(text="📊 Segmentlar", callback_data="users:segments")
    b.button(text="📤 CSV eksport", callback_data="users:export")
    b.button(text="🏠 Menyu", callback_data="admin:home")
    b.adjust(2, 2, 1)
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        f"{terminal_header('USER MANAGEMENT')}\n\n👥 Jami: <b>{total}</b>\n🟢 Faol (7 kun): <b>{active['n'] if active else 0}</b>\n🆕 Yangi (7 kun): <b>{new['n'] if new else 0}</b>\n🚫 Ban: <b>{banned['n'] if banned else 0}</b>",
        reply_markup=b.as_markup(),
    )


@router.callback_query(lambda c: c.data == "users:search")
async def search_start(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await state.set_state(UserStates.search)
    await callback.answer()
    await callback.message.edit_text("Telegram user ID yoki @username yuboring:", reply_markup=back_home_keyboard("admin:users"))


@router.message(UserStates.search)
async def search_result(message: Message, state: FSMContext, repo: Repo) -> None:
    term = (message.text or "").strip()
    if not term or len(term) > 100:
        await message.answer("Qidiruv qiymati 1–100 belgi bo‘lsin.")
        return
    users = await repo.search_users(term, 20)
    b = InlineKeyboardBuilder()
    lines = [terminal_header("USER SEARCH"), ""]
    for user in users:
        lines.append(f"👤 {html.escape(user['first_name'] or 'User')} · <code>{user['id']}</code> · @{html.escape(user['username'] or 'yo‘q')}")
        b.button(text=f"{user['id']} · {str(user['first_name'])[:22]}", callback_data=f"users:view:{user['id']}")
    b.button(text="⬅️ Orqaga", callback_data="admin:users")
    b.adjust(1)
    await state.clear()
    await message.answer("\n".join(lines) if users else "Foydalanuvchi topilmadi.", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("users:view:"))
async def user_card(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    user_id = int(callback.data.split(":")[2])
    user = await repo.get_user(user_id)
    if not user:
        await callback.answer("Foydalanuvchi topilmadi.", show_alert=True)
        return
    tickets = await repo.db.fetchone("SELECT COUNT(*) n FROM tickets WHERE user_id=?", (user_id,))
    b = InlineKeyboardBuilder()
    b.button(text="🚫 Ban", callback_data=f"users:ban:{user_id}")
    b.button(text="🟢 Unban", callback_data=f"users:unban:{user_id}")
    b.button(text="📝 Izoh", callback_data=f"users:note:{user_id}")
    b.button(text="💬 Murojaatlari", callback_data=f"users:tickets:{user_id}")
    b.button(text="⬅️ Orqaga", callback_data="admin:users")
    b.adjust(2, 2, 1)
    text = (
        f"{terminal_header('USER PROFILE')}\n\n👤 {html.escape(user['first_name'])}\n"
        f"Username: @{html.escape(user['username'] or 'yo‘q')}\nID: <code>{user_id}</code>\n"
        f"Manba: <code>{html.escape(user['source'] or 'direct')}</code>\n"
        f"Ro‘yxatdan: <code>{html.escape(user['joined_at'])}</code>\n"
        f"Oxirgi faollik: <code>{html.escape(user['last_seen'])}</code>\n"
        f"Murojaatlar: <b>{tickets['n'] if tickets else 0}</b>\n"
        f"Holat: {'🚫 BAN' if user['is_banned'] else '🟢 ACTIVE'}\nIzoh: {html.escape(user['note'] or 'yo‘q')}"
    )
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("users:ban:"))
async def ban_user(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    user_id = int(callback.data.split(":")[2])
    await repo.set_user_ban(user_id, True)
    await repo.audit(callback.from_user.id, "user_banned", str(user_id))
    await callback.answer("Foydalanuvchi ban qilindi.")
    await _show_user_again(callback, repo, user_id)


@router.callback_query(lambda c: c.data and c.data.startswith("users:unban:"))
async def unban_user(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    user_id = int(callback.data.split(":")[2])
    await repo.set_user_ban(user_id, False)
    await repo.audit(callback.from_user.id, "user_unbanned", str(user_id))
    await callback.answer("Ban olib tashlandi.")
    await _show_user_again(callback, repo, user_id)


async def _show_user_again(callback: CallbackQuery, repo: Repo, user_id: int) -> None:
    user = await repo.get_user(user_id)
    if user:
        await callback.message.edit_text(f"👤 <b>{html.escape(user['first_name'])}</b>\nID: <code>{user_id}</code>\nHolat: {'🚫 BAN' if user['is_banned'] else '🟢 ACTIVE'}", reply_markup=back_home_keyboard("admin:users"))


@router.callback_query(lambda c: c.data and c.data.startswith("users:note:"))
async def note_start(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    user_id = int(callback.data.split(":")[2])
    await state.clear()
    await state.update_data(user_id=user_id)
    await state.set_state(UserStates.note)
    await callback.answer()
    await callback.message.edit_text(f"<code>{user_id}</code> foydalanuvchisi uchun ichki admin izohini yuboring (500 belgigacha):", reply_markup=back_home_keyboard("admin:users"))


@router.message(UserStates.note)
async def save_note(message: Message, state: FSMContext, repo: Repo) -> None:
    note = (message.text or "").strip()
    if len(note) > 500:
        await message.answer("Izoh 500 belgidan oshmasin.")
        return
    user_id = int((await state.get_data()).get("user_id", 0))
    await repo.set_user_note(user_id, note)
    await repo.audit(message.from_user.id, "user_note_updated", str(user_id))
    await state.clear()
    await message.answer("🟢 Ichki izoh saqlandi.", reply_markup=back_home_keyboard("admin:users"))


@router.callback_query(lambda c: c.data and c.data.startswith("users:tickets:"))
async def user_tickets(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    user_id = int(callback.data.split(":")[2])
    rows = await repo.db.fetchall("SELECT id,status,tag,created_at FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT 15", (user_id,))
    b = InlineKeyboardBuilder()
    for row in rows:
        b.button(text=f"#{row['id']} · {row['status']} · {row['tag']}", callback_data=f"ticket:view:{row['id']}")
    b.button(text="⬅️ Orqaga", callback_data=f"users:view:{user_id}")
    b.adjust(1)
    await callback.answer()
    await callback.message.edit_text("\n".join(f"#{r['id']} · {r['status']} · {r['tag']} · {r['created_at']}" for r in rows) or "Murojaat yo‘q.", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data == "users:banned")
async def banned_users(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    rows = await repo.db.fetchall("SELECT id,username,first_name FROM users WHERE is_banned=1 ORDER BY last_seen DESC LIMIT 30")
    b = InlineKeyboardBuilder()
    for row in rows:
        b.button(text=f"{row['id']} · {str(row['first_name'])[:20]}", callback_data=f"users:view:{row['id']}")
    b.button(text="⬅️ Orqaga", callback_data="admin:users")
    b.adjust(1)
    await callback.answer()
    await callback.message.edit_text("🚫 <b>Ban qilingan foydalanuvchilar</b>\n" + ("\n".join(f"• <code>{r['id']}</code> @{html.escape(r['username'] or 'yo‘q')}" for r in rows) if rows else "Ro‘yxat bo‘sh."), reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data == "users:segments")
async def segment_counts(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    queries = {
        "Barcha": "SELECT COUNT(*) n FROM users WHERE is_banned=0",
        "7 kun faol": "SELECT COUNT(*) n FROM users WHERE last_seen>=datetime('now','-7 day') AND is_banned=0",
        "7 kun yangi": "SELECT COUNT(*) n FROM users WHERE joined_at>=datetime('now','-7 day') AND is_banned=0",
        "30 kun nofaol": "SELECT COUNT(*) n FROM users WHERE last_seen<datetime('now','-30 day') AND is_banned=0",
    }
    lines = [terminal_header("AUDIENCE SEGMENTS"), ""]
    for label, sql in queries.items():
        row = await repo.db.fetchone(sql)
        lines.append(f"• {label}: <b>{row['n'] if row else 0}</b>")
    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=back_home_keyboard("admin:users"))


@router.callback_query(lambda c: c.data == "users:export")
async def export_users(callback: CallbackQuery, settings: Settings, repo: Repo, bot: Bot) -> None:
    if not await require_admin(callback, settings):
        return
    rows = await repo.export_rows("users")
    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    await bot.send_document(callback.from_user.id, BufferedInputFile(buffer.getvalue().encode("utf-8-sig"), filename="users.csv"), caption=f"Foydalanuvchilar: {len(rows)}")
    await callback.answer("CSV yuborildi.")
