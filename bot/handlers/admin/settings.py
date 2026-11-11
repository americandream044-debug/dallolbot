"""Runtime settings with persistent SQLite-backed toggles."""
from __future__ import annotations

import html
from aiogram import Router
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.db.repo import Repo
from bot.middlewares.admin_only import require_admin
from bot.services.reaction_service import ALLOWED_REACTIONS
from bot.ui.keyboards import back_home_keyboard, settings_keyboard
from bot.ui.theme import terminal_header

router = Router(name="admin_settings")
TOGGLES = {"subscription_required", "effects", "auto_reaction", "notify_new_ticket", "weekly_report"}


class SettingsStates(StatesGroup):
    report_time = State()
    ai_cap = State()
    spam = State()
    welcome = State()
    cost_rate = State()


@router.callback_query(lambda c: c.data == "admin:settings")
async def settings_home(callback: CallbackQuery, settings: Settings, repo: Repo, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await state.clear()
    values = await repo.get_settings()
    usage = await repo.ai_usage_today()
    rate = float(values.get("ai_cost_per_1k_chars_usd", "0") or 0)
    estimated_cost = (usage['input_chars'] + usage['output_chars']) / 1000 * rate
    approx_tokens = (usage['input_chars'] + usage['output_chars']) // 4
    cost_text = f"${estimated_cost:.4f}" if rate > 0 else "tarif koeffitsienti kiritilmagan"
    await callback.answer()
    await callback.message.edit_text(
        f"{terminal_header('SYSTEM SETTINGS')}\n\n🧠 AI bugun: <b>{usage['requests']}</b> so‘rov · ~{approx_tokens} token\n"
        f"💵 Taxminiy xarajat: <b>{cost_text}</b>\n"
        f"Effektlar: {'ON' if values.get('effects') == '1' else 'OFF'}\nObuna nazorati: {'ON' if values.get('subscription_required') == '1' else 'OFF'}\n"
        f"Avto-reaksiya: {values.get('reaction_emoji','🔥')}\nHaftalik hisobot: {values.get('weekly_report_time','20:00')}",
        reply_markup=settings_keyboard(values),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("settings:toggle:"))
async def toggle_setting(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    key = callback.data.split(":")[2]
    if key not in TOGGLES:
        await callback.answer("Sozlama topilmadi.", show_alert=True)
        return
    old = await repo.get_setting(key, "0")
    value = "0" if old == "1" else "1"
    await repo.set_setting(key, value)
    await repo.audit(callback.from_user.id, "setting_toggled", f"{key}={value}")
    await callback.answer(f"{key}: {'ON' if value == '1' else 'OFF'}")
    await callback.message.edit_reply_markup(reply_markup=settings_keyboard(await repo.get_settings()))


@router.callback_query(lambda c: c.data == "settings:post_style")
async def cycle_post_style(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    values = ["Terminal", "Card", "Minimal", "Script"]
    current = await repo.get_setting("default_post_style", "Card")
    next_value = values[(values.index(current) + 1) % len(values)] if current in values else values[0]
    await repo.set_setting("default_post_style", next_value)
    await repo.audit(callback.from_user.id, "default_post_style", next_value)
    await callback.answer(f"Uslub: {next_value}")
    await callback.message.edit_reply_markup(reply_markup=settings_keyboard(await repo.get_settings()))


@router.callback_query(lambda c: c.data == "settings:post_font")
async def cycle_post_font(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    values = ["bold", "sans", "bolditalic", "script", "mono", "smallcaps"]
    current = await repo.get_setting("default_heading_font", "bold")
    next_value = values[(values.index(current) + 1) % len(values)] if current in values else values[0]
    await repo.set_setting("default_heading_font", next_value)
    await repo.audit(callback.from_user.id, "default_heading_font", next_value)
    await callback.answer(f"Shrift: {next_value}")
    await callback.message.edit_reply_markup(reply_markup=settings_keyboard(await repo.get_settings()))


@router.callback_query(lambda c: c.data == "settings:report_day")
async def choose_report_day(callback: CallbackQuery, settings: Settings) -> None:
    if not await require_admin(callback, settings):
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    for day, label in (("mon", "Dushanba"), ("tue", "Seshanba"), ("wed", "Chorshanba"), ("thu", "Payshanba"), ("fri", "Juma"), ("sat", "Shanba"), ("sun", "Yakshanba")):
        b.button(text=label, callback_data=f"settings:set_report_day:{day}")
    b.button(text="⬅️ Orqaga", callback_data="admin:settings")
    b.adjust(2, 2, 2, 1)
    await callback.answer()
    await callback.message.edit_text("Haftalik hisobot kunini tanlang:", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("settings:set_report_day:"))
async def save_report_day(callback: CallbackQuery, settings: Settings, repo: Repo, scheduler) -> None:
    if not await require_admin(callback, settings):
        return
    day = callback.data.split(":")[3]
    if day not in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}:
        await callback.answer("Kun noto‘g‘ri.", show_alert=True)
        return
    await repo.set_setting("weekly_report_day", day)
    time_value = await repo.get_setting("weekly_report_time", "20:00")
    hour, minute = [int(x) for x in time_value.split(":", 1)]
    if scheduler.scheduler.get_job("weekly_report"):
        scheduler.scheduler.reschedule_job("weekly_report", trigger=CronTrigger(day_of_week=day, hour=hour, minute=minute, timezone=ZoneInfo(settings.timezone)))
    await repo.audit(callback.from_user.id, "weekly_report_day_changed", day)
    await callback.answer("Hisobot kuni saqlandi.")
    await callback.message.edit_text("🟢 Haftalik hisobot kuni yangilandi.", reply_markup=back_home_keyboard("admin:settings"))


@router.callback_query(lambda c: c.data == "settings:cost_rate")
async def cost_rate_start(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await state.set_state(SettingsStates.cost_rate)
    await callback.answer()
    await callback.message.edit_text("1000 belgi uchun taxminiy USD koeffitsientini kiriting (0 = hisoblamaslik). Narx model va provider tarifiga qarab o‘zgaradi:", reply_markup=back_home_keyboard("admin:settings"))


@router.message(SettingsStates.cost_rate)
async def cost_rate_save(message: Message, state: FSMContext, repo: Repo) -> None:
    raw = (message.text or "").strip().replace(",", ".")
    try:
        value = float(raw)
        if value < 0 or value > 100:
            raise ValueError
    except ValueError:
        await message.answer("0 dan 100 gacha son kiriting, masalan 0.002.")
        return
    await repo.set_setting("ai_cost_per_1k_chars_usd", str(value))
    await state.clear()
    await message.answer("🟢 Xarajat koeffitsienti saqlandi. Ko‘rsatilgan qiymat taxminiy bahodir.", reply_markup=back_home_keyboard("admin:settings"))


@router.callback_query(lambda c: c.data == "settings:reaction")
async def choose_reaction(callback: CallbackQuery, settings: Settings) -> None:
    if not await require_admin(callback, settings):
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    for emoji in ALLOWED_REACTIONS:
        b.button(text=emoji, callback_data=f"settings:set_reaction:{emoji}")
    b.button(text="⬅️ Orqaga", callback_data="admin:settings")
    b.adjust(3, 3, 1)
    await callback.answer()
    await callback.message.edit_text("Avto-reaksiya uchun emoji tanlang:", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("settings:set_reaction:"))
async def set_reaction(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    emoji = callback.data.split(":", 2)[2]
    if emoji not in ALLOWED_REACTIONS:
        await callback.answer("Emoji ruxsat etilmagan.", show_alert=True)
        return
    await repo.set_setting("reaction_emoji", emoji)
    await repo.audit(callback.from_user.id, "reaction_emoji_changed", emoji)
    values = await repo.get_settings()
    usage = await repo.ai_usage_today()
    await callback.answer("Emoji saqlandi.")
    await callback.message.edit_text(f"{terminal_header('SYSTEM SETTINGS')}\n\n🧠 AI bugun: <b>{usage['requests']}</b> so‘rov", reply_markup=settings_keyboard(values))


@router.callback_query(lambda c: c.data == "settings:report_time")
async def report_time_start(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await state.set_state(SettingsStates.report_time)
    await callback.answer()
    await callback.message.edit_text("Haftalik hisobot vaqtini HH:MM formatida yuboring (masalan 20:00). Kun: yakshanba.", reply_markup=back_home_keyboard("admin:settings"))


@router.message(SettingsStates.report_time)
async def report_time_save(message: Message, state: FSMContext, repo: Repo, scheduler, settings: Settings) -> None:
    value = (message.text or "").strip()
    try:
        hour, minute = [int(x) for x in value.split(":", 1)]
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError
    except ValueError:
        await message.answer("Vaqt HH:MM ko‘rinishida bo‘lsin, masalan 20:00.")
        return
    normalized = f"{hour:02d}:{minute:02d}"
    await repo.set_setting("weekly_report_time", normalized)
    job = scheduler.scheduler.get_job("weekly_report")
    if job:
        scheduler.scheduler.reschedule_job("weekly_report", trigger=CronTrigger(day_of_week=await repo.get_setting("weekly_report_day", "sun"), hour=hour, minute=minute, timezone=ZoneInfo(settings.timezone)))
    await repo.audit(message.from_user.id, "weekly_report_time_changed", normalized)
    await state.clear()
    await message.answer("🟢 Haftalik hisobot vaqti saqlandi. Scheduler sozlamasi keyingi ishga tushishda qayta yuklanadi.", reply_markup=back_home_keyboard("admin:settings"))


@router.callback_query(lambda c: c.data == "settings:ai_cap")
async def ai_cap_start(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await state.set_state(SettingsStates.ai_cap)
    await callback.answer()
    await callback.message.edit_text("Kunlik AI so‘rov limitini yuboring (0 = cheksiz, tavsiya: 20–100):", reply_markup=back_home_keyboard("admin:settings"))


@router.message(SettingsStates.ai_cap)
async def ai_cap_save(message: Message, state: FSMContext, repo: Repo) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) > 10000:
        await message.answer("0 dan 10000 gacha butun son yuboring.")
        return
    await repo.set_setting("daily_ai_cap", raw)
    await repo.audit(message.from_user.id, "daily_ai_cap_changed", raw)
    await state.clear()
    await message.answer(f"🟢 Kunlik AI limiti: <b>{raw}</b>.", reply_markup=back_home_keyboard("admin:settings"))


@router.callback_query(lambda c: c.data == "settings:spam")
async def spam_start(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await state.set_state(SettingsStates.spam)
    await callback.answer()
    await callback.message.edit_text("Anti-spam intervalini soniyada yuboring (5–300):", reply_markup=back_home_keyboard("admin:settings"))


@router.message(SettingsStates.spam)
async def spam_save(message: Message, state: FSMContext, repo: Repo) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or not 5 <= int(raw) <= 300:
        await message.answer("5–300 oralig‘ida butun son yuboring.")
        return
    await repo.set_setting("anti_spam_seconds", raw)
    await state.clear()
    await message.answer(f"🟢 Anti-spam: {raw} soniya.", reply_markup=back_home_keyboard("admin:settings"))


@router.callback_query(lambda c: c.data == "settings:welcome")
async def welcome_start(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await state.set_state(SettingsStates.welcome)
    await callback.answer()
    await callback.message.edit_text("Oddiy foydalanuvchilar uchun welcome matnini yuboring (800 belgigacha):", reply_markup=back_home_keyboard("admin:settings"))


@router.message(SettingsStates.welcome)
async def welcome_save(message: Message, state: FSMContext, repo: Repo) -> None:
    value = (message.text or "").strip()
    if not value or len(value) > 800:
        await message.answer("Welcome matni 1–800 belgi bo‘lsin.")
        return
    await repo.set_setting("welcome_text", html.escape(value))
    await state.clear()
    await message.answer("🟢 Welcome matni saqlandi.", reply_markup=back_home_keyboard("admin:settings"))
