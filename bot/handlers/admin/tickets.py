"""Admin ticket inbox, replies, tags, status transitions, and AI drafts."""
from __future__ import annotations

import html
from datetime import datetime, timezone

from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import Settings
from bot.db.repo import Repo, utc_now
from bot.middlewares.admin_only import require_admin
from bot.services.ai_service import AIService
from bot.ui.fx import run_with_loading
from bot.ui.keyboards import back_home_keyboard, ticket_card_keyboard
from bot.ui.theme import terminal_header

router = Router(name="admin_tickets")
TAGS = ("savol", "taklif", "shikoyat", "hamkorlik", "reklama")


class TicketStates(StatesGroup):
    waiting_reply = State()
    waiting_search = State()
    quick_title = State()
    quick_text = State()


def _payload(message: Message) -> tuple[str, str, str | None]:
    if message.text:
        return "text", message.text, None
    for kind, attr in (("photo", "photo"), ("voice", "voice"), ("document", "document"), ("video", "video"), ("audio", "audio"), ("animation", "animation")):
        value = getattr(message, attr, None)
        if value:
            return kind, message.caption or "", value[-1].file_id if kind == "photo" else value.file_id
    return "unsupported", "", None


async def _send_user_reply(bot: Bot, chat_id: int, ticket_id: int, kind: str, content: str, file_id: str | None) -> None:
    header = f"💬 <b>Admindan javob · #{ticket_id}</b>\n"
    if kind == "text":
        await bot.send_message(chat_id, header + html.escape(content))
    elif file_id:
        if kind == "photo":
            await bot.send_photo(chat_id, file_id, caption=header + html.escape(content)[:900])
        elif kind == "video":
            await bot.send_video(chat_id, file_id, caption=header + html.escape(content)[:900])
        elif kind == "voice":
            await bot.send_voice(chat_id, file_id, caption=header + html.escape(content)[:900])
        elif kind == "document":
            await bot.send_document(chat_id, file_id, caption=header + html.escape(content)[:900])
        elif kind == "audio":
            await bot.send_audio(chat_id, file_id, caption=header + html.escape(content)[:900])
        elif kind == "animation":
            await bot.send_animation(chat_id, file_id, caption=header + html.escape(content)[:900])


async def _show_ticket(message: Message, repo: Repo, ticket_id: int) -> None:
    ticket = await repo.get_ticket(ticket_id)
    if not ticket:
        await message.edit_text("Murojaat topilmadi.", reply_markup=back_home_keyboard("admin:tickets"))
        return
    history = await repo.ticket_history(ticket_id, 12)
    history.reverse()
    body = [terminal_header(f"TICKET #{ticket_id}"), ""]
    body.append(f"👤 {html.escape(ticket['first_name'] or 'Foydalanuvchi')} @{html.escape(ticket['username'] or 'username yo‘q')}")
    body.append(f"🆔 <code>{ticket['user_id']}</code> · 📌 {html.escape(ticket['status'])} · 🏷 {html.escape(ticket['tag'])}")
    body.append(f"⭐ Muhim: {'ha' if ticket['is_starred'] else 'yo‘q'} · 🗓 {html.escape(ticket['created_at'])}")
    body.append("\n<b>So‘nggi xabarlar:</b>")
    for item in history:
        prefix = "👤 USER" if item["sender"] == "user" else "🛡 ADMIN"
        text = html.escape(item["text"][:400]) if item["text"] else f"[{html.escape(item['content_type'])}]"
        body.append(f"{prefix}: {text}")
    await message.edit_text("\n".join(body), reply_markup=ticket_card_keyboard(ticket_id))


@router.callback_query(lambda c: c.data == "admin:tickets")
async def ticket_inbox(callback: CallbackQuery, settings: Settings, repo: Repo, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await callback.answer()
    await state.clear()
    await _list_tickets(callback.message, repo, "all", 0)


async def _list_tickets(message: Message, repo: Repo, status: str, page: int, tag: str | None = None) -> None:
    rows = await repo.list_tickets(status, 10, page * 10, tag)
    b = InlineKeyboardBuilder()
    b.button(text="🆕 Yangi", callback_data="tickets:filter:new")
    b.button(text="⏳ Jarayonda", callback_data="tickets:filter:in_progress")
    b.button(text="✅ Yopilgan", callback_data="tickets:filter:closed")
    b.button(text="📋 Barchasi", callback_data="tickets:filter:all")
    b.button(text="🏷 Teg bo‘yicha", callback_data="tickets:tags")
    for row in rows:
        marker = "⭐ " if row["is_starred"] else ""
        label = f"{marker}#{row['id']} · {row['first_name'] or row['user_id']} · {row['status']}"
        b.button(text=label[:60], callback_data=f"ticket:view:{row['id']}")
    if page > 0:
        b.button(text="⬅️ Oldingi", callback_data=f"tickets:page:{status}:{page-1}:{tag or 'all'}")
    if len(rows) == 10:
        b.button(text="Keyingi ➡️", callback_data=f"tickets:page:{status}:{page+1}:{tag or 'all'}")
    b.button(text="🔎 Qidirish", callback_data="tickets:search")
    b.button(text="📊 Statistika", callback_data="tickets:metrics")
    b.button(text="🏠 Menyu", callback_data="admin:home")
    b.adjust(2, 2, 1, 1, 2, 1)
    filter_label = status + (f" / {tag}" if tag else "")
    text = f"{terminal_header('SUPPORT INBOX')}\n\nFiltr: <b>{html.escape(filter_label)}</b> · Sahifa: {page+1}\n"
    if rows:
        text += "\n".join(f"• <code>#{r['id']}</code> {html.escape(r['first_name'] or 'Foydalanuvchi')} — {html.escape(r['status'])} / {html.escape(r['tag'])}" for r in rows)
    else:
        text += "Murojaatlar topilmadi."
    await message.edit_text(text, reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("tickets:filter:"))
async def filter_tickets(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    status = callback.data.split(":")[2]
    await callback.answer()
    await _list_tickets(callback.message, repo, status, 0)


@router.callback_query(lambda c: c.data and c.data.startswith("tickets:page:"))
async def ticket_page(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    try:
        _, _, status, page_text, tag = callback.data.split(":", 4)
        page = max(0, min(10000, int(page_text)))
        if status not in {"all", "new", "in_progress", "closed"} or (tag != "all" and tag not in TAGS):
            raise ValueError
    except (ValueError, TypeError):
        await callback.answer("Sahifa tugmasi eskirgan.", show_alert=True)
        return
    await callback.answer()
    await _list_tickets(callback.message, repo, status, page, None if tag == "all" else tag)


@router.callback_query(lambda c: c.data == "tickets:tags")
async def ticket_tag_filters(callback: CallbackQuery, settings: Settings) -> None:
    if not await require_admin(callback, settings):
        return
    b = InlineKeyboardBuilder()
    b.button(text="📋 Barcha teglar", callback_data="tickets:tagfilter:all")
    for tag in TAGS:
        b.button(text=f"🏷 {tag}", callback_data=f"tickets:tagfilter:{tag}")
    b.button(text="⬅️ Inbox", callback_data="admin:tickets")
    b.adjust(2, 2, 2)
    await callback.answer()
    await callback.message.edit_text("Murojaatlarni teg bo‘yicha filtrlash:", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("tickets:tagfilter:"))
async def filter_tickets_by_tag(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    tag = callback.data.split(":", 2)[2]
    if tag != "all" and tag not in TAGS:
        await callback.answer("Teg topilmadi.", show_alert=True)
        return
    await callback.answer()
    await _list_tickets(callback.message, repo, "all", 0, None if tag == "all" else tag)


@router.callback_query(lambda c: c.data and c.data.startswith("ticket:view:"))
async def view_ticket(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    ticket_id = int(callback.data.split(":")[2])
    await callback.answer()
    await _show_ticket(callback.message, repo, ticket_id)


@router.callback_query(lambda c: c.data and c.data.startswith("ticket:reply:"))
async def begin_ticket_reply(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    ticket_id = int(callback.data.split(":")[2])
    await state.clear()
    await state.update_data(ticket_id=ticket_id)
    await state.set_state(TicketStates.waiting_reply)
    await callback.answer()
    await callback.message.edit_text(f"↩️ <b>#{ticket_id}</b> murojaatiga javob matni yoki media yuboring.\nBekor qilish: /cancel", reply_markup=back_home_keyboard("admin:tickets"))


@router.message(TicketStates.waiting_reply)
async def send_ticket_reply(message: Message, state: FSMContext, settings: Settings, repo: Repo, bot: Bot) -> None:
    data = await state.get_data()
    ticket_id = int(data.get("ticket_id", 0))
    ticket = await repo.get_ticket(ticket_id)
    if not ticket:
        await message.answer("Murojaat topilmadi.")
        await state.clear()
        return
    kind, content, file_id = _payload(message)
    if kind == "unsupported" or len(content) > 3500:
        await message.answer("Matn, foto, video, ovoz yoki hujjat yuboring. Matn 3500 belgidan oshmasin.")
        return
    try:
        await _send_user_reply(bot, int(ticket["user_id"]), ticket_id, kind, content, file_id)
    except Exception as exc:
        await message.answer(f"🔴 Foydalanuvchiga yuborilmadi: {html.escape(str(exc)[:250])}")
        return
    await repo.add_ticket_message(ticket_id, "admin", kind, content, file_id)
    if not ticket.get("first_reply_at"):
        await repo.update_ticket(ticket_id, first_reply_at=utc_now(), status="in_progress")
    await repo.audit(message.from_user.id, "ticket_replied", f"ticket={ticket_id}")
    await state.clear()
    await message.answer(f"🟢 <b>[ SENT ]</b> #{ticket_id} murojaatiga javob yuborildi.", reply_markup=back_home_keyboard("admin:tickets"))


@router.callback_query(lambda c: c.data and c.data.startswith("ticket:status:"))
async def ticket_status(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    _, _, ticket_id, status = callback.data.split(":", 3)
    if status not in {"new", "in_progress", "closed"}:
        await callback.answer("Status noto‘g‘ri.", show_alert=True)
        return
    fields = {"status": status}
    if status == "closed":
        fields["closed_at"] = utc_now()
    await repo.update_ticket(int(ticket_id), **fields)
    await repo.audit(callback.from_user.id, "ticket_status", f"ticket={ticket_id}; status={status}")
    await callback.answer("Status yangilandi.")
    await _show_ticket(callback.message, repo, int(ticket_id))


@router.callback_query(lambda c: c.data and c.data.startswith("ticket:tag:"))
async def ticket_tag_menu(callback: CallbackQuery, settings: Settings) -> None:
    if not await require_admin(callback, settings):
        return
    ticket_id = int(callback.data.split(":")[2])
    b = InlineKeyboardBuilder()
    for tag in TAGS:
        b.button(text=tag, callback_data=f"ticket:settag:{ticket_id}:{tag}")
    b.button(text="⬅️ Orqaga", callback_data=f"ticket:view:{ticket_id}")
    b.adjust(2, 2, 1)
    await callback.answer()
    await callback.message.edit_text(f"#{ticket_id} uchun tegni tanlang:", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("ticket:settag:"))
async def set_ticket_tag(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    _, _, ticket_id, tag = callback.data.split(":", 3)
    if tag not in TAGS:
        await callback.answer("Teg noto‘g‘ri.", show_alert=True)
        return
    await repo.update_ticket(int(ticket_id), tag=tag)
    await callback.answer("Teg saqlandi.")
    await _show_ticket(callback.message, repo, int(ticket_id))


@router.callback_query(lambda c: c.data and c.data.startswith("ticket:star:"))
async def toggle_star(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    ticket_id = int(callback.data.split(":")[2])
    ticket = await repo.get_ticket(ticket_id)
    if ticket:
        await repo.update_ticket(ticket_id, is_starred=0 if ticket["is_starred"] else 1)
    await callback.answer("Muhimlik yangilandi.")
    await _show_ticket(callback.message, repo, ticket_id)


@router.callback_query(lambda c: c.data and c.data.startswith("ticket:ban:"))
async def ban_ticket_user(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    ticket_id = int(callback.data.split(":")[2])
    ticket = await repo.get_ticket(ticket_id)
    if ticket:
        await repo.set_user_ban(int(ticket["user_id"]), True)
        await repo.audit(callback.from_user.id, "user_banned_from_ticket", str(ticket["user_id"]))
    await callback.answer("Foydalanuvchi bloklandi.")
    await _show_ticket(callback.message, repo, ticket_id)


@router.callback_query(lambda c: c.data == "tickets:metrics")
async def ticket_metrics(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    metrics = await repo.ticket_metrics()
    counts = metrics["counts"]
    seconds = int(metrics["avg_first_reply_seconds"])
    await callback.answer()
    await callback.message.edit_text(
        f"{terminal_header('SUPPORT METRICS')}\n\n🆕 Yangi: {counts.get('new',0)}\n⏳ Jarayonda: {counts.get('in_progress',0)}\n✅ Yopilgan: {counts.get('closed',0)}\n⏱ O‘rtacha birinchi javob: {seconds//3600} soat {(seconds%3600)//60} daqiqa",
        reply_markup=back_home_keyboard("admin:tickets"),
    )


@router.callback_query(lambda c: c.data == "tickets:search")
async def ticket_search_start(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await state.set_state(TicketStates.waiting_search)
    await callback.answer()
    await callback.message.edit_text("Foydalanuvchi ID, username yoki qidiriladigan matnni yuboring:", reply_markup=back_home_keyboard("admin:tickets"))


@router.message(TicketStates.waiting_search)
async def ticket_search_result(message: Message, state: FSMContext, repo: Repo) -> None:
    term = (message.text or "").strip()
    if not term or len(term) > 100:
        await message.answer("Qidiruv 1–100 belgi bo‘lsin.")
        return
    tickets = await repo.search_tickets(term, 20)
    lines = [terminal_header("SEARCH RESULTS"), ""]
    b = InlineKeyboardBuilder()
    for ticket in tickets:
        username = "@" + ticket["username"] if ticket["username"] else ticket["first_name"] or str(ticket["user_id"])
        lines.append(f"👤 {html.escape(str(username))} · <code>#{ticket['id']}</code> · {html.escape(ticket['status'])} / {html.escape(ticket['tag'])}")
        b.button(text=f"Ticket #{ticket['id']}", callback_data=f"ticket:view:{ticket['id']}")
    b.button(text="⬅️ Inbox", callback_data="admin:tickets")
    b.adjust(1)
    await state.clear()
    await message.answer("\n".join(lines) if len(lines) > 2 else "Natija topilmadi.", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("ticket:quick:"))
async def ticket_quick_menu(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    ticket_id = int(callback.data.split(":")[2])
    ticket = await repo.get_ticket(ticket_id)
    if not ticket:
        await callback.answer("Murojaat topilmadi.", show_alert=True)
        return
    snippets = await repo.list_quick_replies()
    b = InlineKeyboardBuilder()
    for item in snippets:
        b.button(text=f"⚡ {item['title'][:35]}", callback_data=f"ticket:quickuse:{ticket_id}:{item['id']}")
    b.button(text="➕ Yangi tez javob", callback_data=f"ticket:quickadd:{ticket_id}")
    b.button(text="⬅️ Murojaat", callback_data=f"ticket:view:{ticket_id}")
    b.adjust(1)
    await callback.answer()
    await callback.message.edit_text(f"#{ticket_id} uchun tez javob shablonini tanlang:", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("ticket:quickadd:"))
async def ticket_quick_add_start(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    ticket_id = int(callback.data.split(":")[2])
    await state.clear()
    await state.update_data(ticket_id=ticket_id)
    await state.set_state(TicketStates.quick_title)
    await callback.answer()
    await callback.message.edit_text("Tez javob uchun nom yuboring (80 belgigacha):", reply_markup=back_home_keyboard("admin:tickets"))


@router.message(TicketStates.quick_title)
async def ticket_quick_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title or len(title) > 80:
        await message.answer("Nom 1–80 belgi bo‘lsin.")
        return
    await state.update_data(quick_title=title)
    await state.set_state(TicketStates.quick_text)
    await message.answer("Tez javob matnini yuboring (1000 belgigacha):")


@router.message(TicketStates.quick_text)
async def ticket_quick_text(message: Message, state: FSMContext, repo: Repo, bot: Bot) -> None:
    text = (message.text or "").strip()
    if not text or len(text) > 1000:
        await message.answer("Matn 1–1000 belgi bo‘lsin.")
        return
    data = await state.get_data()
    quick_id = await repo.create_quick_reply(str(data.get("quick_title", "Tez javob")), text)
    ticket_id = int(data.get("ticket_id", 0))
    ticket = await repo.get_ticket(ticket_id)
    if ticket:
        await _send_user_reply(bot, int(ticket["user_id"]), ticket_id, "text", text, None)
        await repo.add_ticket_message(ticket_id, "admin", "text", text)
        if not ticket.get("first_reply_at"):
            await repo.update_ticket(ticket_id, first_reply_at=utc_now(), status="in_progress")
    await repo.audit(message.from_user.id, "quick_reply_created_and_sent", f"quick_id={quick_id}; ticket={ticket_id}")
    await state.clear()
    await message.answer(f"🟢 Tez javob #{quick_id} saqlandi va murojaatga yuborildi.", reply_markup=back_home_keyboard("admin:tickets"))


@router.callback_query(lambda c: c.data and c.data.startswith("ticket:quickuse:"))
async def ticket_quick_use(callback: CallbackQuery, settings: Settings, repo: Repo, bot: Bot) -> None:
    if not await require_admin(callback, settings):
        return
    _, _, ticket_text, quick_text = callback.data.split(":", 3)
    ticket_id, quick_id = int(ticket_text), int(quick_text)
    ticket = await repo.get_ticket(ticket_id)
    snippet = await repo.get_quick_reply(quick_id)
    if not ticket or not snippet:
        await callback.answer("Tez javob yoki murojaat topilmadi.", show_alert=True)
        return
    try:
        await _send_user_reply(bot, int(ticket["user_id"]), ticket_id, "text", snippet["text"], None)
    except Exception as exc:
        await callback.answer(f"Yuborilmadi: {str(exc)[:100]}", show_alert=True)
        return
    await repo.add_ticket_message(ticket_id, "admin", "text", snippet["text"])
    if not ticket.get("first_reply_at"):
        await repo.update_ticket(ticket_id, first_reply_at=utc_now(), status="in_progress")
    await repo.audit(callback.from_user.id, "quick_reply_sent", f"quick_id={quick_id}; ticket={ticket_id}")
    await callback.answer("Tez javob yuborildi.")
    await _show_ticket(callback.message, repo, ticket_id)


@router.callback_query(lambda c: c.data and c.data.startswith("ticket:ai:"))
async def ai_draft_reply(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    ticket_id = int(callback.data.split(":")[2])
    history = await repo.ticket_history(ticket_id, 12)
    history_text = "\n".join(f"{row['sender']}: {row['text']}" for row in reversed(history))
    await callback.answer()
    status = await callback.message.edit_text("<pre>⠋ AI SUPPORT DRAFT...</pre>")
    try:
        prompt = await run_with_loading(status, AIService(settings, repo).generate(
            "Siz Dasturlash & AI kanali uchun muloyim, aniq va foydali support operatorisiz. Faqat o‘zbek tilida javob yozing.",
            f"Murojaat tarixi:\n{history_text}\n\nAdmin nomidan qisqa javob loyihasini tayyorlang.", 0.45,
        ), await repo.get_setting("effects", "1") == "1")
        await state.clear()
        await state.update_data(ticket_id=ticket_id)
        await state.set_state(TicketStates.waiting_reply)
        await status.edit_text(f"🤖 <b>AI javob loyihasi</b>\n\n<pre>{html.escape(prompt[:2500])}</pre>\n\nMatnni o‘zgartirib yuborish uchun quyidagi oynaga javob yozing.", reply_markup=back_home_keyboard("admin:tickets"))
    except Exception as exc:
        await status.edit_text(f"🔴 {html.escape(str(exc)[:250])}", reply_markup=back_home_keyboard("admin:tickets"))
