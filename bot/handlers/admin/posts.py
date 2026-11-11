"""AI channel-post writer, style/font preview, editing, publishing, and drafts."""
from __future__ import annotations

import html
import json
from urllib.parse import urlparse
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.db.repo import Repo
from bot.middlewares.admin_only import require_admin
from bot.services.ai_service import AIService
from bot.services.post_service import PostService, sanitize_telegram_html, extract_title
from bot.services.scheduler_service import SchedulerService
from bot.ui.fx import run_with_loading
from bot.ui.keyboards import back_home_keyboard, fonts_keyboard, preview_keyboard, styles_keyboard
from bot.ui.theme import terminal_header
from bot.ui.stylizer import stylize

router = Router(name="admin_posts")


class PostStates(StatesGroup):
    waiting_topic = State()
    choosing_variant = State()
    choosing_style = State()
    choosing_font = State()
    preview = State()
    waiting_edit = State()
    waiting_schedule = State()
    waiting_published_edit = State()
    waiting_buttons = State()
    waiting_poll = State()


def _frame(body: str, style: str) -> str:
    body = body.strip()
    if style == "Terminal":
        body = body.replace("\n", "\n<code>&gt; </code>")
        return f"<code>root@dasturlash:~$ publish</code>\n{body}"
    if style == "Card":
        return f"<b>━━━━━━━━━━━━━━━━━━</b>\n{body}\n<b>━━━━━━━━━━━━━━━━━━</b>"
    if style == "Minimal":
        return body
    if style == "Script":
        return f"<i>✦ DASTURLASH & AI ✦</i>\n\n{body}\n\n<i>— bilim • tajriba • natija</i>"
    return body


def _tools_keyboard():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    for label, action in (("🪝 Hook kuchaytirish", "hook"), ("✂️ Qisqartirish", "shorten"), ("➕ Uzaytirish", "extend"), ("#️⃣ Hashtaglar", "hashtags"), ("😀 Emoji tuzatish", "emoji"), ("📏 Uzunlik tekshiruvi", "length")):
        b.button(text=label, callback_data=f"post:tool:{action}")
    b.button(text="⬅️ Preview", callback_data="post:show_preview")
    b.adjust(2, 2, 2, 1)
    return b.as_markup()


@router.callback_query(lambda c: c.data == "admin:post")
async def post_entry(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    await callback.answer()
    await state.clear()
    await state.set_state(PostStates.waiting_topic)
    await callback.message.edit_text(
        f"{terminal_header('CHANNEL POST WRITER')}\n\nPost mavzusini, tayyor matnni yuboring yoki izohli foto jo‘nating. AI 3 xil hook bilan variant tayyorlaydi.\n\nMaksimum manba matni: 3000 belgi.",
        reply_markup=_post_entry_keyboard(),
    )


def _post_entry_keyboard():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="📂 Postlar va qoralamalar", callback_data="post:library")
    b.button(text="📚 Shablonlar", callback_data="post:templates")
    b.button(text="🏠 Menyu", callback_data="admin:home")
    b.adjust(1)
    return b.as_markup()


@router.message(PostStates.waiting_topic)
async def receive_topic(message: Message, state: FSMContext, settings: Settings, repo: Repo) -> None:
    topic = (message.text or message.caption or "").strip()
    media_type = None
    media_file_id = None
    if message.photo:
        media_type, media_file_id = "photo", message.photo[-1].file_id
    elif message.video:
        media_type, media_file_id = "video", message.video.file_id
    elif message.document:
        media_type, media_file_id = "document", message.document.file_id
    if not topic:
        await message.answer("Mavzu yoki foto uchun izoh matnini ham yuboring.")
        return
    if len(topic) > 3000:
        await message.answer("Manba matni 3000 belgidan oshmasligi kerak.")
        return
    status = await message.answer("<pre>⠋ POST ENGINE / BUILDING VARIANTS...</pre>")
    try:
        variants = await run_with_loading(status, AIService(settings, repo).write_post_variants(topic), await repo.get_setting("effects", "1") == "1")
    except Exception as exc:
        await status.edit_text(f"🔴 <b>AI xatosi</b>\n{html.escape(str(exc)[:300])}", reply_markup=back_home_keyboard("admin:post"))
        return
    variants = variants[:3]
    similar = await repo.recent_similar_posts(topic[:180])
    await state.update_data(topic=topic, variants=variants, media_type=media_type, media_file_id=media_file_id, variant_index=0, similar_posts=similar, style=await repo.get_setting("default_post_style", "Card"), font=await repo.get_setting("default_heading_font", "bold"))
    await state.set_state(PostStates.choosing_variant)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    for i, variant in enumerate(variants):
        title = f"Variant {i+1} · {extract_title(variant)[:22]}"
        b.button(text=title[:60], callback_data=f"post:variant:{i}")
    b.button(text="🏠 Menyu", callback_data="admin:home")
    b.adjust(1)
    preview = "\n\n".join(f"<b>VARIANT {i+1}</b>\n<pre>{html.escape(v[:500])}</pre>" for i, v in enumerate(variants))
    warning = "\n\n⚠️ O‘xshash mavzu yaqinda joylangan: " + ", ".join(f"#{x['id']} {html.escape(x['title'][:35])}" for x in similar) if similar else ""
    await status.edit_text(f"{terminal_header('CHOOSE HOOK')}\n\n{preview}{warning}", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("post:variant:"))
async def choose_variant(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    try:
        index = int(callback.data.split(":")[2])
        data = await state.get_data()
        body = data["variants"][index]
    except (ValueError, KeyError, IndexError, TypeError):
        await callback.answer("Variant eskirgan. Mavzuni qaytadan kiriting.", show_alert=True)
        return
    await callback.answer()
    await state.update_data(variant_index=index, raw_body=body)
    await state.set_state(PostStates.choosing_style)
    await callback.message.edit_text("🎨 Post uslubini tanlang:", reply_markup=styles_keyboard())


@router.callback_query(lambda c: c.data and c.data.startswith("post:style:"))
async def choose_style(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    style = callback.data.split(":", 2)[2]
    if style not in {"Terminal", "Card", "Minimal", "Script"}:
        await callback.answer("Uslub topilmadi.", show_alert=True)
        return
    await callback.answer()
    await state.update_data(style=style)
    await state.set_state(PostStates.choosing_font)
    await callback.message.edit_text("🔤 Sarlavha shriftini tanlang:", reply_markup=fonts_keyboard())


@router.callback_query(lambda c: c.data and c.data.startswith("post:font:"))
async def choose_font(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo, bot, scheduler: SchedulerService) -> None:
    if not await require_admin(callback, settings):
        return
    font = callback.data.split(":", 2)[2]
    data = await state.get_data()
    body = str(data.get("raw_body", ""))
    style = str(data.get("style", "Card"))
    formatted = stylize(_frame(body, style), font)
    safe = sanitize_telegram_html(formatted)
    post_id = data.get("post_id")
    post_service = PostService(bot, settings, repo)
    if post_id:
        await repo.update_post(int(post_id), body_html=safe, title=extract_title(safe), style=style, font=font)
    else:
        post_id = await post_service.save_draft(safe, style, font, media_type=data.get("media_type"), media_file_id=data.get("media_file_id"))
    await state.update_data(font=font, body_html=safe, post_id=post_id)
    await state.set_state(PostStates.preview)
    await callback.answer()
    await _show_preview(callback.message, safe, int(post_id), style, font, media=bool(data.get("media_type")))


async def _show_preview(message: Message, body: str, post_id: int, style: str, font: str, media: bool = False) -> None:
    # The preview body mirrors the exact HTML sent to the channel; admin metadata stays in FSM/DB.
    try:
        await message.edit_text(body, reply_markup=preview_keyboard())
    except Exception:
        await message.answer(body, reply_markup=preview_keyboard())


@router.callback_query(lambda c: c.data == "post:tools")
async def show_post_tools(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    data = await state.get_data()
    if not data.get("body_html"):
        await callback.answer("Post matni topilmadi.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text("🧰 <b>POST EDITOR TOOLS</b>\n\nMatnni tanlangan amal bilan qayta ishlang:", reply_markup=_tools_keyboard())


@router.callback_query(lambda c: c.data == "post:show_preview")
async def show_preview_callback(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    data = await state.get_data()
    await callback.answer()
    await _show_preview(callback.message, str(data.get("body_html", "Preview mavjud emas")), int(data.get("post_id", 0)), str(data.get("style", "Card")), str(data.get("font", "bold")), media=bool(data.get("media_type")))


@router.callback_query(lambda c: c.data == "post:publish")
async def publish_post(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo, bot) -> None:
    if not await require_admin(callback, settings):
        return
    data = await state.get_data()
    post_id = data.get("post_id")
    if not post_id:
        await callback.answer("Qoralama topilmadi.", show_alert=True)
        return
    await callback.answer("Kanalga joylanmoqda...")
    try:
        message_id = await PostService(bot, settings, repo).publish(int(post_id))
        await repo.audit(callback.from_user.id, "post_published", f"post_id={post_id}; message_id={message_id}")
        await state.clear()
        await callback.message.edit_text(f"🟢 <b>[ DEPLOYED ✅ ]</b>\nPost kanalga joylandi.\nPost: <code>#{post_id}</code>\nMessage: <code>{message_id}</code>", reply_markup=back_home_keyboard())
    except Exception as exc:
        await callback.message.edit_text(f"🔴 <b>[ FAIL ]</b>\n{html.escape(str(exc)[:350])}", reply_markup=preview_keyboard())


@router.callback_query(lambda c: c.data == "post:schedule")
async def ask_schedule(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await callback.answer()
    await state.set_state(PostStates.waiting_schedule)
    await callback.message.edit_text("🕒 Sana va vaqtni yuboring: <code>2026-11-12 18:30</code>\nBot vaqt zonasi: Asia/Tashkent.", reply_markup=back_home_keyboard("post:show_preview"))


@router.message(PostStates.waiting_schedule)
async def receive_schedule_time(message: Message, state: FSMContext, settings: Settings, repo: Repo, scheduler: SchedulerService) -> None:
    value = (message.text or "").strip()
    try:
        run_at = datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(settings.timezone))
        if run_at <= datetime.now(ZoneInfo(settings.timezone)):
            raise ValueError("Vaqt kelajakda bo‘lishi kerak.")
    except ValueError as exc:
        await message.answer(f"Sana noto‘g‘ri. <code>YYYY-MM-DD HH:MM</code> formatida, kelajak vaqtini yuboring.\n{html.escape(str(exc))}")
        return
    data = await state.get_data()
    post_id = data.get("post_id")
    if not post_id:
        await message.answer("Qoralama topilmadi. Menyudan qayta boshlang.")
        await state.clear()
        return
    await scheduler.schedule_post(int(post_id), run_at)
    await repo.audit(message.from_user.id, "post_scheduled", f"post_id={post_id}; at={run_at.isoformat()}")
    await state.clear()
    await message.answer(f"🟢 <b>[ SCHEDULED ]</b> Post <code>#{post_id}</code>\nVaqt: <code>{run_at:%Y-%m-%d %H:%M}</code>", reply_markup=back_home_keyboard())


@router.callback_query(lambda c: c.data == "post:edit")
async def edit_post_request(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await callback.answer()
    await state.set_state(PostStates.waiting_edit)
    await callback.message.edit_text("✏️ Yangi post matnini HTML formatda yuboring. Faqat Telegram qo‘llaydigan teglar saqlanadi.", reply_markup=back_home_keyboard("post:show_preview"))


@router.message(PostStates.waiting_edit)
async def edit_post_text(message: Message, state: FSMContext, repo: Repo) -> None:
    body = (message.text or "").strip()
    if not body or len(body) > 4096:
        await message.answer("Matn 1–4096 belgi oralig‘ida bo‘lishi kerak.")
        return
    data = await state.get_data()
    safe = sanitize_telegram_html(stylize(_frame(body, str(data.get("style", "Card"))), str(data.get("font", "bold"))))
    post_id = int(data.get("post_id", 0))
    if post_id:
        await repo.update_post(post_id, body_html=safe, title=extract_title(safe))
    await state.update_data(raw_body=body, body_html=safe)
    await state.set_state(PostStates.preview)
    await message.answer(f"{safe}\n\n<code>POST #{post_id}</code>", reply_markup=preview_keyboard())


@router.callback_query(lambda c: c.data == "post:rewrite")
async def rewrite_post(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    data = await state.get_data()
    topic = str(data.get("topic", ""))
    if not topic:
        await callback.answer("Mavzu topilmadi.", show_alert=True)
        return
    await callback.answer()
    status = await callback.message.edit_text("<pre>⠋ POST REWRITE...</pre>")
    try:
        variants = await run_with_loading(status, AIService(settings, repo).write_post_variants(topic), await repo.get_setting("effects", "1") == "1")
        await state.update_data(variants=variants[:3])
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        b = InlineKeyboardBuilder()
        for i, variant in enumerate(variants[:3]):
            b.button(text=f"Variant {i+1}: {extract_title(variant)[:24]}", callback_data=f"post:variant:{i}")
        b.adjust(1)
        await status.edit_text("Yangi variantlardan birini tanlang:\n\n" + "\n\n".join(f"<b>{i+1}.</b> <pre>{html.escape(v[:400])}</pre>" for i, v in enumerate(variants[:3])), reply_markup=b.as_markup())
        await state.set_state(PostStates.choosing_variant)
    except Exception as exc:
        await status.edit_text(f"🔴 {html.escape(str(exc)[:250])}", reply_markup=preview_keyboard())


@router.callback_query(lambda c: c.data and c.data.startswith("post:tool:"))
async def post_tool(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    data = await state.get_data()
    body = str(data.get("body_html", ""))
    if not body:
        await callback.answer("Post matni yo‘q.", show_alert=True)
        return
    action = callback.data.split(":")[2]
    await callback.answer()
    if action == "length":
        limit = 1024 if data.get("media_type") else 4096
        import re
        from html import unescape
        visible_count = len(unescape(re.sub(r"<[^>]+>", "", body)))
        status_text = "🟢 Telegram limiti ichida" if visible_count <= limit else "⚠️ Telegram limitidan oshgan"
        note = "" if data.get("media_type") or visible_count <= 900 else "\n💡 Tavsiya: oddiy post uchun 900 belgigacha."
        await callback.message.edit_text(f"📏 Uzunlik: <code>{visible_count} / {limit}</code>\n{status_text}{note}", reply_markup=_tools_keyboard())
        return
    instructions = {
        "hook": "Faqat birinchi hook/sarlavhani kuchliroq, lekin yolg‘onsiz va aniqroq qiling.",
        "shorten": "Postni mazmunini saqlagan holda 25 foizga qisqartiring.",
        "extend": "Foydali misol bilan postni biroz kengaytiring, 900 belgidan oshirmang.",
        "hashtags": "Post oxiriga mos 2-3 hashtag qo‘shing.",
        "emoji": "Emoji soni va joylashuvini 3-5 ta mos emoji bilan tartiblang.",
    }
    status = await callback.message.edit_text("<pre>⠋ EDITOR TOOL / WORKING...</pre>")
    try:
        result = await run_with_loading(status, AIService(settings, repo).generate("O‘zbek tilidagi Telegram muharririsiz. Faqat to‘liq HTML postni qaytaring.", instructions.get(action, "Postni yaxshilang") + "\n" + body, 0.5), await repo.get_setting("effects", "1") == "1")
        safe = sanitize_telegram_html(stylize(_frame(result, str(data.get("style", "Card"))), str(data.get("font", "bold"))))
        await repo.update_post(int(data.get("post_id", 0)), body_html=safe, title=extract_title(safe))
        await state.update_data(body_html=safe, raw_body=result)
        await status.edit_text(safe, reply_markup=preview_keyboard())
        await state.set_state(PostStates.preview)
    except Exception as exc:
        await status.edit_text(f"🔴 {html.escape(str(exc)[:250])}", reply_markup=_tools_keyboard())


@router.callback_query(lambda c: c.data == "post:buttons")
async def post_buttons_start(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await state.set_state(PostStates.waiting_buttons)
    await callback.answer()
    await callback.message.edit_text("Har qatorda bitta tugma yuboring: <code>Tugma nomi | https://example.com</code>\nMaksimum 4 ta. Bekor qilish uchun /cancel.", reply_markup=back_home_keyboard("post:show_preview"))


@router.message(PostStates.waiting_buttons)
async def post_buttons_save(message: Message, state: FSMContext, repo: Repo) -> None:
    lines = [line.strip() for line in (message.text or "").splitlines() if line.strip()]
    if not lines or len(lines) > 4:
        await message.answer("1–4 qator yuboring. Format: <code>Tugma nomi | https://example.com</code>")
        return
    buttons = []
    for line in lines:
        if "|" not in line:
            await message.answer(f"Format noto‘g‘ri: <code>{html.escape(line[:100])}</code>")
            return
        label, url = [part.strip() for part in line.split("|", 1)]
        parsed = urlparse(url)
        if not label or len(label) > 50 or parsed.scheme not in {"https", "http"} or not parsed.netloc:
            await message.answer("Tugma nomi 1–50 belgi, havola esa http/https URL bo‘lishi kerak.")
            return
        buttons.append({"text": label, "url": url})
    data = await state.get_data()
    post_id = int(data.get("post_id", 0))
    await repo.update_post(post_id, buttons_json=json.dumps(buttons, ensure_ascii=False))
    await state.update_data(buttons=buttons)
    await state.set_state(PostStates.preview)
    await message.answer("🟢 Inline URL tugmalari saqlandi. Preview oynasida davom eting.", reply_markup=preview_keyboard())


@router.callback_query(lambda c: c.data == "post:poll")
async def post_poll_start(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await state.set_state(PostStates.waiting_poll)
    await callback.answer()
    await callback.message.edit_text("So‘rovnoma formatini yuboring: <code>Savol | Variant 1 | Variant 2</code> (2–10 variant). Post chiqqach poll alohida xabar bo‘lib joylanadi.", reply_markup=back_home_keyboard("post:show_preview"))


@router.message(PostStates.waiting_poll)
async def post_poll_save(message: Message, state: FSMContext, repo: Repo) -> None:
    parts = [part.strip() for part in (message.text or "").split("|")]
    if len(parts) < 3 or len(parts) > 11 or any(not p for p in parts):
        await message.answer("Savol va 2–10 ta variant yuboring: <code>Savol | Variant 1 | Variant 2</code>")
        return
    if len(parts[0]) > 300 or any(len(x) > 100 for x in parts[1:]):
        await message.answer("Savol 300, har bir variant 100 belgidan oshmasin.")
        return
    data = await state.get_data()
    post_id = int(data.get("post_id", 0))
    await repo.update_post(post_id, poll_question=parts[0], poll_options_json=json.dumps(parts[1:], ensure_ascii=False))
    await state.update_data(poll_question=parts[0], poll_options=parts[1:])
    await state.set_state(PostStates.preview)
    await message.answer("🟢 So‘rovnoma saqlandi. U postdan keyin kanalga yuboriladi.", reply_markup=preview_keyboard())


@router.callback_query(lambda c: c.data == "post:templates")
async def post_templates(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    rows = await repo.list_templates()
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    for row in rows:
        b.button(text=f"#{row['id']} · {row['name'][:32]}", callback_data=f"post:template_use:{row['id']}")
    b.button(text="⬅️ Post yozish", callback_data="admin:post")
    b.adjust(1)
    lines = [terminal_header("POST TEMPLATES"), ""]
    lines.extend(f"• <code>#{row['id']}</code> {html.escape(row['name'])}" for row in rows)
    if not rows:
        lines.append("Hozircha saqlangan shablon yo‘q. Post kartasidan ‘Shablon sifatida saqlash’ni bosing.")
    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("post:template_use:"))
async def post_template_use(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    template_id = int(callback.data.split(":")[2])
    template = await repo.get_template(template_id)
    if not template:
        await callback.answer("Shablon topilmadi.", show_alert=True)
        return
    post_id = await repo.create_post(template["name"], template["body_html"], template["style"], template["font"], "draft")
    await state.clear()
    await state.update_data(post_id=post_id, body_html=template["body_html"], raw_body=template["body_html"], topic=template["name"], style=template["style"], font=template["font"])
    await state.set_state(PostStates.preview)
    await callback.answer("Yangi qoralama yaratildi.")
    await callback.message.edit_text(f"{terminal_header('TEMPLATE LOADED')}\n\n{template['body_html']}", reply_markup=preview_keyboard())


@router.callback_query(lambda c: c.data == "post:library")
async def post_library(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    for label, status in (("📝 Qoralamalar", "draft"), ("🕒 Rejalashtirilgan", "scheduled"), ("🟢 Joylangan", "published"), ("🔴 Xatoli", "failed")):
        b.button(text=label, callback_data=f"post:list:{status}")
    b.button(text="⬅️ Post yozish", callback_data="admin:post")
    b.button(text="🏠 Menyu", callback_data="admin:home")
    b.adjust(2, 2, 1, 1)
    await callback.answer()
    await callback.message.edit_text(f"{terminal_header('POST LIBRARY')}\n\nQoralama, reja va e’lonlar boshqaruvi:", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("post:list:"))
async def post_list(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    status = callback.data.split(":")[2]
    if status not in {"draft", "scheduled", "published", "failed"}:
        await callback.answer("Filtr noto‘g‘ri.", show_alert=True)
        return
    rows = await repo.list_posts(status=status, limit=20, offset=0)
    await _render_post_list(callback.message, repo, status, 0, rows)
    await callback.answer()


async def _render_post_list(message: Message, repo: Repo, status: str, page: int, rows=None) -> None:
    rows = rows if rows is not None else await repo.list_posts(status=status, limit=20, offset=page * 20)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    for row in rows:
        b.button(text=f"#{row['id']} · {str(row['title'])[:35]}", callback_data=f"post:manage:{row['id']}")
    if page > 0:
        b.button(text="⬅️ Oldingi", callback_data=f"post:page:{status}:{page-1}")
    if len(rows) == 20:
        b.button(text="Keyingi ➡️", callback_data=f"post:page:{status}:{page+1}")
    b.button(text="⬅️ Filtrlar", callback_data="post:library")
    b.adjust(1)
    lines = [terminal_header(f"POSTS / {status.upper()}"), f"Sahifa: {page+1}", ""]
    lines.extend(f"• <code>#{r['id']}</code> {html.escape(r['title'][:60])} · {html.escape(str(r.get('published_at') or r.get('scheduled_at') or r['created_at']))}" for r in rows)
    if not rows:
        lines.append("Bu bo‘lim hozircha bo‘sh.")
    await message.edit_text("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("post:page:"))
async def post_list_page(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    try:
        _, _, status, page_text = callback.data.split(":", 3)
        page = max(0, min(10000, int(page_text)))
        if status not in {"draft", "scheduled", "published", "failed"}:
            raise ValueError
    except (ValueError, TypeError):
        await callback.answer("Sahifa tugmasi eskirgan.", show_alert=True)
        return
    await callback.answer()
    await _render_post_list(callback.message, repo, status, page)


@router.callback_query(lambda c: c.data and c.data.startswith("post:manage:"))
async def post_manage(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    post_id = int(callback.data.split(":")[2])
    post = await repo.get_post(post_id)
    if not post:
        await callback.answer("Post topilmadi.", show_alert=True)
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    if post["status"] == "published":
        b.button(text="✏️ Kanal matnini tahrirlash", callback_data=f"post:published_edit:{post_id}")
        b.button(text="📌 Qayta mahkamlash", callback_data=f"post:repin:{post_id}")
        b.button(text="🗑 Kanal postini o‘chirish", callback_data=f"post:delete_confirm:{post_id}")
    if post["status"] in {"draft", "failed"}:
        b.button(text="📄 Qoralamani davom ettirish", callback_data=f"post:resume:{post_id}")
    b.button(text="📑 Nusxa olish", callback_data=f"post:duplicate:{post_id}")
    b.button(text="💾 Shablon sifatida saqlash", callback_data=f"post:template:{post_id}")
    b.button(text="⬅️ Ro‘yxat", callback_data=f"post:list:{post['status']}")
    b.adjust(1)
    text = f"{terminal_header(f'POST #{post_id}')}\n\n<b>{html.escape(post['title'])}</b>\nHolat: <code>{html.escape(post['status'])}</code>\nUslub: {html.escape(post['style'])} · Shrift: {html.escape(post['font'])}\n\n{post['body_html'][:2200]}"
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("post:resume:"))
async def resume_draft(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    post_id = int(callback.data.split(":")[2])
    post = await repo.get_post(post_id)
    if not post:
        await callback.answer("Qoralama topilmadi.", show_alert=True)
        return
    await state.clear()
    await state.update_data(post_id=post_id, body_html=post["body_html"], raw_body=post["body_html"], style=post["style"], font=post["font"], media_type=post.get("media_type"), media_file_id=post.get("media_file_id"), topic=post["title"])
    await state.set_state(PostStates.preview)
    await callback.answer()
    await callback.message.edit_text(f"{terminal_header('DRAFT RESUMED')}\n\n{post['body_html']}", reply_markup=preview_keyboard())


@router.callback_query(lambda c: c.data and c.data.startswith("post:duplicate:"))
async def duplicate_post(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    post_id = int(callback.data.split(":")[2])
    post = await repo.get_post(post_id)
    if not post:
        await callback.answer("Post topilmadi.", show_alert=True)
        return
    new_id = await repo.create_post(f"{post['title']} (nusxa)", post["body_html"], post["style"], post["font"], "draft", tag=post["tag"], media_type=post.get("media_type"), media_file_id=post.get("media_file_id"))
    await repo.audit(callback.from_user.id, "post_duplicated", f"source={post_id}; copy={new_id}")
    await callback.answer("Nusxa yaratildi.")
    await callback.message.edit_text(f"🟢 Qoralama nusxasi yaratildi: <code>#{new_id}</code>", reply_markup=back_home_keyboard("post:library"))


@router.callback_query(lambda c: c.data and c.data.startswith("post:template:"))
async def save_post_template(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    post_id = int(callback.data.split(":")[2])
    post = await repo.get_post(post_id)
    if not post:
        await callback.answer("Post topilmadi.", show_alert=True)
        return
    await repo.create_template(f"{post['title'][:90]} #{post_id}", post["body_html"], post["style"], post["font"])
    await repo.audit(callback.from_user.id, "post_template_saved", str(post_id))
    await callback.answer("Shablon saqlandi.")


@router.callback_query(lambda c: c.data and c.data.startswith("post:published_edit:"))
async def published_edit_start(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    post_id = int(callback.data.split(":")[2])
    post = await repo.get_post(post_id)
    if not post or post["status"] != "published":
        await callback.answer("Joylangan post topilmadi.", show_alert=True)
        return
    await state.clear()
    await state.update_data(post_id=post_id, media_type=post.get("media_type"))
    await state.set_state(PostStates.waiting_published_edit)
    await callback.answer()
    await callback.message.edit_text(f"#{post_id} uchun yangi Telegram HTML matnini yuboring. Media postida caption 1024 belgi bilan cheklanadi.", reply_markup=back_home_keyboard("post:library"))


@router.message(PostStates.waiting_published_edit)
async def published_edit_save(message: Message, state: FSMContext, settings: Settings, repo: Repo, bot) -> None:
    body = (message.text or message.caption or "").strip()
    data = await state.get_data()
    post_id = int(data.get("post_id", 0))
    limit = 1024 if data.get("media_type") else 4096
    if not body or len(body) > limit:
        await message.answer(f"Matn 1–{limit} belgi bo‘lsin.")
        return
    changed = await PostService(bot, settings, repo).edit_published(post_id, body)
    await state.clear()
    await message.answer("🟢 Kanal posti yangilandi." if changed else "🔴 Postni tahrirlab bo‘lmadi.", reply_markup=back_home_keyboard("post:library"))


@router.callback_query(lambda c: c.data and c.data.startswith("post:repin:"))
async def repin_post(callback: CallbackQuery, settings: Settings, repo: Repo, bot) -> None:
    if not await require_admin(callback, settings):
        return
    post_id = int(callback.data.split(":")[2])
    post = await repo.get_post(post_id)
    if not post or not post.get("channel_message_id"):
        await callback.answer("Kanal xabari topilmadi.", show_alert=True)
        return
    try:
        await bot.pin_chat_message(settings.channel_id, int(post["channel_message_id"]), disable_notification=True)
        await repo.audit(callback.from_user.id, "post_repinned", str(post_id))
        await callback.answer("Post mahkamlandi.")
    except Exception as exc:
        await callback.answer(f"Mahkamlash xatosi: {str(exc)[:120]}", show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("post:delete_confirm:"))
async def delete_post_confirm(callback: CallbackQuery, settings: Settings) -> None:
    if not await require_admin(callback, settings):
        return
    post_id = int(callback.data.split(":")[2])
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="✅ Ha, o‘chirish", callback_data=f"post:delete:{post_id}")
    b.button(text="❌ Bekor", callback_data=f"post:manage:{post_id}")
    b.adjust(2)
    await callback.answer()
    await callback.message.edit_text(f"⚠️ Kanalda <code>#{post_id}</code> postini o‘chirishni tasdiqlaysizmi?", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("post:delete:"))
async def delete_post_confirmed(callback: CallbackQuery, settings: Settings, repo: Repo, bot) -> None:
    if not await require_admin(callback, settings):
        return
    post_id = int(callback.data.split(":")[2])
    try:
        deleted = await PostService(bot, settings, repo).delete_published(post_id)
        await repo.audit(callback.from_user.id, "published_post_deleted", str(post_id))
        await callback.answer("Kanal posti o‘chirildi." if deleted else "Post topilmadi.")
        await callback.message.edit_text(f"{'🟢' if deleted else '⚠️'} #{post_id}: {'o‘chirildi' if deleted else 'topilmadi'}.", reply_markup=back_home_keyboard("post:library"))
    except Exception as exc:
        await callback.answer("O‘chirish amalga oshmadi.", show_alert=True)
        await callback.message.edit_text(f"🔴 {html.escape(str(exc)[:250])}", reply_markup=back_home_keyboard("post:library"))


@router.callback_query(lambda c: c.data == "post:cancel")
async def cancel_post(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    data = await state.get_data()
    post_id = data.get("post_id")
    if post_id:
        await repo.update_post(int(post_id), status="draft")
    await state.clear()
    await callback.answer("Qoralama saqlandi.")
    await callback.message.edit_text("🗑 Amal bekor qilindi. Qoralama saqlanib qoldi.", reply_markup=back_home_keyboard())
