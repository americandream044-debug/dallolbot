"""Admin-only prompt generator, prompt improver, and saved prompt library."""
from __future__ import annotations

import html
from pathlib import Path

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.ai.client import AIProviderError
from bot.config import Settings
from bot.db.repo import Repo
from bot.middlewares.admin_only import require_admin
from bot.services.ai_service import AIService
from bot.ui.fx import run_with_loading
from bot.ui.keyboards import back_home_keyboard, categories_keyboard, prompt_actions_keyboard, pagination_keyboard
from bot.ui.theme import terminal_header

router = Router(name="admin_ai_prompts")

CATEGORIES = {"code": "Kod", "text": "Matn", "image": "Rasm", "business": "Biznes", "study": "O‘qish", "other": "Boshqa"}


class PromptStates(StatesGroup):
    waiting_task = State()
    result = State()
    waiting_title = State()
    waiting_search = State()
    waiting_edit_title = State()


def _result_card(prompt: str) -> str:
    return f"{terminal_header('PROMPT ENGINEER')}\n\n<pre>{html.escape(prompt[:3500])}</pre>"


@router.callback_query(lambda c: c.data == "admin:ai")
async def ai_entry(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(f"{terminal_header('AI PROMPT GENERATOR')}\n\nAvval prompt yo‘nalishini tanlang:", reply_markup=categories_keyboard())


@router.callback_query(lambda c: c.data and c.data.startswith("ai:cat:"))
async def choose_category(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    category_key = callback.data.split(":", 2)[2]
    if category_key not in CATEGORIES:
        await callback.answer("Kategoriya topilmadi.", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await state.update_data(category=CATEGORIES[category_key])
    await state.set_state(PromptStates.waiting_task)
    await callback.message.edit_text(
        f"{terminal_header('INPUT / TASK')}\n\n<b>{CATEGORIES[category_key]}</b> kategoriyasi uchun vazifani yozing.\n\nMasalan: Python’da Telegram bot yaratish uchun mukammal prompt tuzing.\nBekor qilish: /cancel",
        reply_markup=back_home_keyboard("admin:ai"),
    )


@router.message(PromptStates.waiting_task)
async def receive_task(message: Message, state: FSMContext, settings: Settings, repo: Repo) -> None:
    task = (message.text or message.caption or "").strip()
    if not task:
        await message.answer("Vazifani matn ko‘rinishida yuboring.")
        return
    if len(task) > 2500:
        await message.answer("Vazifa 2500 belgidan oshmasligi kerak.")
        return
    data = await state.get_data()
    category = str(data.get("category", "Boshqa"))
    status = await message.answer("<pre>⠋ AI CORE / INITIALIZING...</pre>")
    effects = await repo.get_setting("effects", "1") == "1"
    try:
        result = await run_with_loading(status, AIService(settings, repo).prompt(category, task), effects)
    except Exception as exc:
        await status.edit_text(f"🔴 <b>AI xatosi</b>\n{html.escape(str(exc)[:300])}", reply_markup=back_home_keyboard("admin:ai"))
        return
    await state.update_data(task=task, prompt=result)
    await state.set_state(PromptStates.result)
    await status.edit_text(_result_card(result), reply_markup=prompt_actions_keyboard())
    await repo.audit(message.from_user.id, "ai_prompt_generated", category)


async def _transform(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo, instruction: str, title: str) -> None:
    if not await require_admin(callback, settings):
        return
    data = await state.get_data()
    prompt = str(data.get("prompt", ""))
    if not prompt:
        await callback.answer("Prompt topilmadi. Qaytadan boshlang.", show_alert=True)
        return
    await callback.answer()
    status = await callback.message.edit_text("<pre>⠋ PROMPT MATRIX / PROCESSING...</pre>")
    effects = await repo.get_setting("effects", "1") == "1"
    try:
        output = await run_with_loading(status, AIService(settings, repo).generate(
            "Siz tajribali prompt muhandisisiz. Javobni o‘zbek tilida yozing, faqat natijani bering.",
            f"{instruction}\n\nPROMPT:\n{prompt}", 0.55,
        ), effects)
    except Exception as exc:
        await status.edit_text(f"🔴 {html.escape(str(exc)[:300])}", reply_markup=prompt_actions_keyboard())
        return
    await state.update_data(prompt=output)
    await status.edit_text(_result_card(output), reply_markup=prompt_actions_keyboard())


@router.callback_query(lambda c: c.data == "ai:regen")
async def regenerate(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    data = await state.get_data()
    task = str(data.get("task", ""))
    category = str(data.get("category", "Boshqa"))
    if not task:
        await callback.answer("Vazifa topilmadi.", show_alert=True)
        return
    await callback.answer()
    status = await callback.message.edit_text("<pre>⠋ YANGI PROMPT YARATILMOQDA...</pre>")
    try:
        result = await run_with_loading(status, AIService(settings, repo).prompt(category, task), await repo.get_setting("effects", "1") == "1")
        await state.update_data(prompt=result)
        await status.edit_text(_result_card(result), reply_markup=prompt_actions_keyboard())
    except Exception as exc:
        await status.edit_text(f"🔴 {html.escape(str(exc)[:250])}", reply_markup=prompt_actions_keyboard())


@router.callback_query(lambda c: c.data == "ai:improve")
async def improve(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    await _transform(callback, settings, state, repo, "Promptni kuchaytiring va oxirida 3 bandli 'Nimalar yaxshilandi' izohini yozing.", "improve")


@router.callback_query(lambda c: c.data == "ai:shorten")
async def shorten(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    await _transform(callback, settings, state, repo, "Promptni asosiy talablarni saqlagan holda 40 foizga qisqartiring.", "shorten")


@router.callback_query(lambda c: c.data == "ai:english")
async def english(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    await _transform(callback, settings, state, repo, "Promptni aniq va tabiiy ingliz tiliga tarjima qiling.", "english")


@router.callback_query(lambda c: c.data == "ai:save")
async def save_prompt(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    data = await state.get_data()
    prompt = str(data.get("prompt", ""))
    if not prompt:
        await callback.answer("Saqlash uchun prompt topilmadi.", show_alert=True)
        return
    await state.set_state(PromptStates.waiting_title)
    await callback.answer()
    await callback.message.edit_text("💾 Prompt uchun qisqa nom yuboring:", reply_markup=back_home_keyboard("admin:ai"))


@router.message(PromptStates.waiting_title)
async def save_prompt_title(message: Message, state: FSMContext, repo: Repo) -> None:
    title = (message.text or "").strip()
    if not title or len(title) > 120:
        await message.answer("Nom 1–120 belgi oralig‘ida bo‘lsin.")
        return
    data = await state.get_data()
    prompt_id = await repo.create_prompt(title, str(data.get("category", "Boshqa")), str(data.get("prompt", "")))
    await state.set_state(PromptStates.result)
    await message.answer(f"🟢 <b>[ SAVED ]</b> Prompt kutubxonaga saqlandi. ID: <code>#{prompt_id}</code>", reply_markup=prompt_actions_keyboard())
    await repo.audit(message.from_user.id, "prompt_saved", f"id={prompt_id}")


async def _render_prompt_library(message: Message, repo: Repo, query: str = "", page: int = 0) -> None:
    rows = await repo.list_prompts(query=query, limit=10, offset=page * 10)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    lines = [terminal_header("PROMPT LIBRARY"), "", f"Qidiruv: <code>{html.escape(query or 'barchasi')}</code> · Sahifa {page+1}"]
    for row in rows:
        lines.append(f"{'⭐' if row['is_favorite'] else '📄'} <b>#{row['id']}</b> {html.escape(row['title'])}")
        builder.button(text=f"#{row['id']} {str(row['title'])[:24]}", callback_data=f"ai:view:{row['id']}")
    if page > 0:
        builder.button(text="⬅️ Oldingi", callback_data=f"ai:page:{page-1}")
    if len(rows) == 10:
        builder.button(text="➡️ Keyingi", callback_data=f"ai:page:{page+1}")
    builder.button(text="🔎 Qidirish", callback_data="ai:search")
    builder.button(text="🏠 Menyu", callback_data="admin:home")
    builder.adjust(1)
    await message.edit_text("\n".join(lines) if rows else "Kutubxonada mos prompt topilmadi.", reply_markup=builder.as_markup())


@router.callback_query(lambda c: c.data == "ai:library")
async def prompt_library(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    await callback.answer()
    await _render_prompt_library(callback.message, repo)


@router.callback_query(lambda c: c.data == "ai:search")
async def prompt_search_start(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await state.set_state(PromptStates.waiting_search)
    await callback.answer()
    await callback.message.edit_text("Kutubxonadan qidiriladigan kalit so‘z yoki iborani yuboring:", reply_markup=back_home_keyboard("ai:library"))


@router.message(PromptStates.waiting_search)
async def prompt_search_result(message: Message, state: FSMContext, repo: Repo) -> None:
    query = (message.text or "").strip()
    if not query or len(query) > 100:
        await message.answer("Qidiruv 1–100 belgi bo‘lsin.")
        return
    await state.update_data(prompt_query=query)
    await state.set_state(PromptStates.result)
    rows = await repo.list_prompts(query=query, limit=10)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    for row in rows:
        b.button(text=f"#{row['id']} {str(row['title'])[:28]}", callback_data=f"ai:view:{row['id']}")
    b.button(text="🔎 Boshqa qidiruv", callback_data="ai:search")
    b.button(text="⬅️ Kutubxona", callback_data="ai:library")
    b.adjust(1)
    lines = [f"{terminal_header('SEARCH / PROMPTS')}", ""] + [f"• #{r['id']} · {html.escape(r['title'])}" for r in rows]
    await message.answer("\n".join(lines) if rows else "Mos prompt topilmadi.", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("ai:page:"))
async def prompt_page(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    page = max(0, int(callback.data.split(":")[2]))
    query = str((await state.get_data()).get("prompt_query", ""))
    await callback.answer()
    await _render_prompt_library(callback.message, repo, query, page)


@router.callback_query(lambda c: c.data and c.data.startswith("ai:view:"))
async def view_saved_prompt(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    try:
        prompt_id = int(callback.data.split(":")[2])
    except (ValueError, IndexError):
        await callback.answer("Noto‘g‘ri ID.", show_alert=True)
        return
    row = await repo.get_prompt(prompt_id)
    if not row:
        await callback.answer("Prompt topilmadi.", show_alert=True)
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="⭐ Sevimli / olib tashlash", callback_data=f"ai:favorite:{prompt_id}")
    b.button(text="✏️ Nomini tahrirlash", callback_data=f"ai:edit_title:{prompt_id}")
    b.button(text="🗑 O'chirish", callback_data=f"ai:delete_confirm:{prompt_id}")
    b.button(text="📢 Kanalga post", callback_data=f"ai:post_saved:{prompt_id}")
    b.button(text="⬅️ Kutubxona", callback_data="ai:library")
    b.adjust(2, 1, 1)
    await callback.answer()
    await callback.message.edit_text(f"<b>{html.escape(row['title'])}</b>\n🏷 {html.escape(row['category'])}\n\n<pre>{html.escape(row['text'][:3300])}</pre>", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("ai:favorite:"))
async def favorite_prompt(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    prompt_id = int(callback.data.split(":")[2])
    row = await repo.get_prompt(prompt_id)
    if row:
        await repo.update_prompt(prompt_id, is_favorite=0 if row["is_favorite"] else 1)
    await callback.answer("Holat yangilandi.")


@router.callback_query(lambda c: c.data and c.data.startswith("ai:edit_title:"))
async def edit_prompt_title_start(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    prompt_id = int(callback.data.split(":")[2])
    if not await repo.get_prompt(prompt_id):
        await callback.answer("Prompt topilmadi.", show_alert=True)
        return
    await state.clear()
    await state.update_data(prompt_id=prompt_id)
    await state.set_state(PromptStates.waiting_edit_title)
    await callback.answer()
    await callback.message.edit_text("Prompt uchun yangi nom yuboring (120 belgigacha):", reply_markup=back_home_keyboard("ai:library"))


@router.message(PromptStates.waiting_edit_title)
async def edit_prompt_title_save(message: Message, state: FSMContext, repo: Repo) -> None:
    title = (message.text or "").strip()
    if not title or len(title) > 120:
        await message.answer("Nom 1–120 belgi oralig‘ida bo‘lsin.")
        return
    prompt_id = int((await state.get_data()).get("prompt_id", 0))
    await repo.update_prompt(prompt_id, title=title)
    await state.clear()
    await message.answer(f"🟢 #{prompt_id} prompt nomi yangilandi: <b>{html.escape(title)}</b>", reply_markup=back_home_keyboard("ai:library"))


@router.callback_query(lambda c: c.data and c.data.startswith("ai:delete_confirm:"))
async def delete_prompt_confirm(callback: CallbackQuery, settings: Settings) -> None:
    if not await require_admin(callback, settings):
        return
    prompt_id = int(callback.data.split(":")[2])
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="✅ Ha, o‘chirish", callback_data=f"ai:delete:{prompt_id}")
    b.button(text="❌ Bekor", callback_data=f"ai:view:{prompt_id}")
    b.adjust(2)
    await callback.answer()
    await callback.message.edit_text(f"⚠️ <code>#{prompt_id}</code> promptni o‘chirishni tasdiqlaysizmi?", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("ai:delete:"))
async def delete_prompt(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    prompt_id = int(callback.data.split(":")[2])
    await repo.delete_prompt(prompt_id)
    await callback.answer("Prompt o‘chirildi.")
    await _render_prompt_library(callback.message, repo)


@router.callback_query(lambda c: c.data and c.data.startswith("ai:post_saved:"))
async def saved_prompt_to_post(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    prompt_id = int(callback.data.split(":")[2])
    row = await repo.get_prompt(prompt_id)
    if not row:
        await callback.answer("Prompt topilmadi.", show_alert=True)
        return
    from bot.services.post_service import PostService
    from bot.config import Settings as Config
    body = f"<b>{html.escape(row['title'])}</b>\n\n<pre>{html.escape(row['text'][:800])}</pre>\n\n#Prompt #DasturlashAI"
    post_id = await repo.create_post(str(row['title']), body, "Card", "bold")
    await callback.answer("Qoralama yaratildi.")
    await callback.message.edit_text(f"📢 Prompt post uchun qoralama yaratildi: <code>#{post_id}</code>", reply_markup=back_home_keyboard("admin:home"))
