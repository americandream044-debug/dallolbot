"""Scheduling UI, recurring calendar suggestions, and daily content queue."""
from __future__ import annotations

import html
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram import Bot
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import Settings
from bot.db.repo import Repo
from bot.middlewares.admin_only import require_admin
from bot.services.ai_service import AIService
from bot.services.analytics_service import AnalyticsService
from bot.services.post_service import PostService
from bot.services.scheduler_service import SchedulerService
from bot.ui.fx import run_with_loading
from bot.ui.keyboards import back_home_keyboard
from bot.ui.theme import terminal_header

router = Router(name="admin_scheduler")


class ScheduleStates(StatesGroup):
    waiting_time = State()
    waiting_post_edit = State()
    waiting_queue_time = State()
    waiting_recurring = State()
    waiting_calendar_edit = State()


@router.callback_query(lambda c: c.data == "admin:schedule")
async def schedule_home(callback: CallbackQuery, settings: Settings, repo: Repo, scheduler: SchedulerService, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await callback.answer()
    await state.clear()
    rows = await repo.db.fetchall("SELECT * FROM posts WHERE status='scheduled' OR recurrence IS NOT NULL ORDER BY COALESCE(scheduled_at,created_at) DESC LIMIT 12")
    b = InlineKeyboardBuilder()
    b.button(text="➕ Qoralamani rejalashtirish", callback_data="schedule:choose_draft")
    b.button(text="🔁 Takroriy post", callback_data="schedule:recurring")
    b.button(text="🗓 Haftalik AI reja", callback_data="schedule:calendar")
    b.button(text="📦 Kontent navbati", callback_data="schedule:queue")
    b.button(text="🕘 Eng yaxshi vaqt", callback_data="schedule:best_time")
    for row in rows:
        b.button(text=f"#{row['id']} · {str(row['title'])[:28]}", callback_data=f"schedule:view:{row['id']}")
    b.button(text="🏠 Menyu", callback_data="admin:home")
    b.adjust(1)
    lines = [terminal_header("SCHEDULER / CONTENT CALENDAR"), "", f"Faol rejalashtirish: <b>{len(scheduler.scheduler.get_jobs())}</b> job", ""]
    for row in rows:
        lines.append(f"🕒 <code>#{row['id']}</code> {html.escape(row['title'])} — <code>{html.escape(str(row.get('scheduled_at') or row.get('recurrence') or ''))}</code>")
    if not rows:
        lines.append("Hozircha rejalashtirilgan post yo‘q.")
    await callback.message.edit_text("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data == "schedule:choose_draft")
async def choose_draft(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    await callback.answer()
    rows = await repo.list_posts(status="draft", limit=15)
    b = InlineKeyboardBuilder()
    for row in rows:
        b.button(text=f"#{row['id']} · {str(row['title'])[:35]}", callback_data=f"schedule:pick:{row['id']}")
    b.button(text="⬅️ Orqaga", callback_data="admin:schedule")
    b.adjust(1)
    await callback.message.edit_text("Rejalashtirish uchun qoralamani tanlang:", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("schedule:pick:"))
async def pick_draft(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    post_id = int(callback.data.split(":")[2])
    if not await repo.get_post(post_id):
        await callback.answer("Qoralama topilmadi.", show_alert=True)
        return
    await state.clear()
    await state.update_data(post_id=post_id)
    await state.set_state(ScheduleStates.waiting_time)
    await callback.answer()
    await callback.message.edit_text("Sana va vaqt: <code>YYYY-MM-DD HH:MM</code>\nMasalan: <code>2026-11-14 18:00</code> (Asia/Tashkent).", reply_markup=back_home_keyboard("admin:schedule"))


@router.message(ScheduleStates.waiting_time)
async def schedule_time_received(message: Message, state: FSMContext, settings: Settings, repo: Repo, scheduler: SchedulerService) -> None:
    try:
        run_at = datetime.strptime((message.text or "").strip(), "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(settings.timezone))
        if run_at <= datetime.now(ZoneInfo(settings.timezone)):
            raise ValueError
    except ValueError:
        await message.answer("Vaqt noto‘g‘ri yoki o‘tib ketgan. <code>YYYY-MM-DD HH:MM</code> ko‘rinishida yuboring.")
        return
    post_id = int((await state.get_data()).get("post_id", 0))
    if not post_id:
        await message.answer("Qoralama ID topilmadi. Qaytadan boshlang.")
        await state.clear()
        return
    await scheduler.schedule_post(post_id, run_at)
    await repo.audit(message.from_user.id, "schedule_created", f"post={post_id}; at={run_at.isoformat()}")
    await state.clear()
    await message.answer(f"🟢 <b>[ SCHEDULED ]</b> #{post_id}\n<code>{run_at:%Y-%m-%d %H:%M}</code>", reply_markup=back_home_keyboard())


@router.callback_query(lambda c: c.data == "schedule:recurring")
async def recurring_choose(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    await callback.answer()
    drafts = await repo.list_posts(status="draft", limit=20)
    b = InlineKeyboardBuilder()
    for row in drafts:
        b.button(text=f"#{row['id']} · {str(row['title'])[:30]}", callback_data=f"schedule:recurring_pick:{row['id']}")
    b.button(text="⬅️ Orqaga", callback_data="admin:schedule")
    b.adjust(1)
    await callback.message.edit_text("Takroriy post uchun qoralama tanlang:", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("schedule:recurring_pick:"))
async def recurring_pick(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    post_id = int(callback.data.split(":")[2])
    if not await repo.get_post(post_id):
        await callback.answer("Qoralama topilmadi.", show_alert=True)
        return
    await state.clear()
    await state.update_data(post_id=post_id)
    await state.set_state(ScheduleStates.waiting_recurring)
    await callback.answer()
    await callback.message.edit_text("Takrorlanish vaqtini yuboring:\n• Har kuni: <code>daily 09:00</code>\n• Har hafta: <code>weekly mon 18:30</code>\nHafta kuni: mon, tue, wed, thu, fri, sat, sun.", reply_markup=back_home_keyboard("admin:schedule"))


@router.message(ScheduleStates.waiting_recurring)
async def recurring_time_received(message: Message, state: FSMContext, settings: Settings, scheduler: SchedulerService, repo: Repo) -> None:
    parts = (message.text or "").strip().lower().split()
    try:
        if len(parts) == 2 and parts[0] == "daily":
            day, clock = "*", parts[1]
        elif len(parts) == 3 and parts[0] == "weekly" and parts[1] in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}:
            day, clock = parts[1], parts[2]
        else:
            raise ValueError
        hour, minute = [int(x) for x in clock.split(":", 1)]
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError
    except ValueError:
        await message.answer("Format noto‘g‘ri. <code>daily 09:00</code> yoki <code>weekly mon 18:30</code> yuboring.")
        return
    post_id = int((await state.get_data()).get("post_id", 0))
    if not post_id:
        await state.clear()
        await message.answer("Qoralama ID yo‘q. Qaytadan boshlang.")
        return
    await scheduler.schedule_recurring(post_id, day, hour, minute)
    await repo.audit(message.from_user.id, "recurring_post_scheduled", f"post={post_id}; {day} {hour:02d}:{minute:02d}")
    await state.clear()
    await message.answer(f"🟢 Takroriy post rejalashtirildi: #{post_id}\n<code>{'har kuni' if day == '*' else 'har hafta ' + day} {hour:02d}:{minute:02d}</code>", reply_markup=back_home_keyboard("admin:schedule"))


@router.callback_query(lambda c: c.data == "schedule:calendar")
async def ai_calendar(callback: CallbackQuery, settings: Settings, repo: Repo, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await callback.answer()
    status = await callback.message.edit_text("<pre>⠋ AI CONTENT CALENDAR / BUILDING...</pre>")
    try:
        system = (
            "Siz o‘zbek tilidagi Dasturlash & AI Telegram kanali kontent strategistisiz. "
            "Faqat JSON massiv qaytaring; aynan 7 obyekt bo‘lsin. Har obyekt: {day, topic, style}. "
            "day qiymatlari Dushanba...Yakshanba, style qiymatlari Terminal, Card, Minimal, Script. "
            "Mavzular bir-birini takrorlamasin, amaliy va tekshiriladigan bo‘lsin."
        )
        raw = await run_with_loading(status, AIService(settings, repo).generate(
            system,
            "Dasturlash, Python, AI, foydali raqamli vositalar va xavfsiz kiberxavfsizlik savodxonligi mavzularida 7 kunlik reja tuzing.",
            0.65,
        ), await repo.get_setting("effects", "1") == "1")
        import json
        try:
            plan = json.loads(raw[raw.find("["):raw.rfind("]") + 1])
        except (ValueError, json.JSONDecodeError):
            plan = []
            for line in raw.splitlines():
                line = line.strip(" -*•0123456789.)")
                if len(line) > 15:
                    plan.append({"day": f"Kun {len(plan)+1}", "topic": line[:180], "style": "Card"})
        plan = [
            {"day": str(item.get("day", f"Kun {i+1}"))[:20], "topic": str(item.get("topic", ""))[:180], "style": str(item.get("style", "Card")) if str(item.get("style", "Card")) in {"Terminal", "Card", "Minimal", "Script"} else "Card"}
            for i, item in enumerate(plan[:7]) if isinstance(item, dict) and str(item.get("topic", "")).strip()
        ]
        if len(plan) < 7:
            raise ValueError("AI 7 ta mavzu qaytarmadi. Rejani qayta yarating.")
        await state.update_data(calendar_plan=plan)
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        b = InlineKeyboardBuilder()
        b.button(text="✅ Rejani tasdiqlash va navbatga qo‘shish", callback_data="schedule:calendar:approve")
        b.button(text="✏️ Rejani tahrirlash", callback_data="schedule:calendar:edit")
        b.button(text="🔁 Qayta yaratish", callback_data="schedule:calendar")
        b.button(text="⬅️ Orqaga", callback_data="admin:schedule")
        b.adjust(1)
        lines = [terminal_header("AI WEEKLY CALENDAR"), ""]
        lines.extend(f"{i+1}. <b>{html.escape(item['day'])}</b> · {html.escape(item['style'])}\n{html.escape(item['topic'])}" for i, item in enumerate(plan))
        await status.edit_text("\n\n".join(lines), reply_markup=b.as_markup())
    except Exception as exc:
        await status.edit_text(f"🔴 {html.escape(str(exc)[:250])}", reply_markup=back_home_keyboard("admin:schedule"))


@router.callback_query(lambda c: c.data == "schedule:calendar:edit")
async def ai_calendar_edit_start(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await state.set_state(ScheduleStates.waiting_calendar_edit)
    await callback.answer()
    await callback.message.edit_text("7 ta mavzuni alohida qatorda yuboring. Format: <code>Mavzu | Terminal</code>. Uslublar: Terminal, Card, Minimal, Script.", reply_markup=back_home_keyboard("admin:schedule"))


@router.message(ScheduleStates.waiting_calendar_edit)
async def ai_calendar_edit_save(message: Message, state: FSMContext) -> None:
    from typing import Any
    rows = [line.strip() for line in (message.text or "").splitlines() if line.strip()]
    if len(rows) != 7:
        await message.answer("Aynan 7 qator yuboring: mavzu va uslub.")
        return
    plan: list[dict[str, Any]] = []
    styles = {"Terminal", "Card", "Minimal", "Script"}
    for index, line in enumerate(rows):
        parts = [part.strip() for part in line.split("|", 1)]
        topic = parts[0][:180]
        style = parts[1] if len(parts) > 1 and parts[1] in styles else "Card"
        if not topic:
            await message.answer("Mavzu bo‘sh bo‘lmasin.")
            return
        plan.append({"day": f"Kun {index+1}", "topic": topic, "style": style})
    await state.update_data(calendar_plan=plan)
    await state.set_state(None)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="✅ Tasdiqlash va navbatga qo‘shish", callback_data="schedule:calendar:approve")
    b.button(text="⬅️ Orqaga", callback_data="admin:schedule")
    b.adjust(1)
    await message.answer("\n\n".join(f"{i+1}. <b>{html.escape(x['style'])}</b> · {html.escape(x['topic'])}" for i, x in enumerate(plan)), reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data == "schedule:calendar:approve")
async def ai_calendar_approve(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo, scheduler: SchedulerService, bot: Bot) -> None:
    if not await require_admin(callback, settings):
        return
    plan = (await state.get_data()).get("calendar_plan", [])
    if len(plan) != 7:
        await callback.answer("Tasdiqlash uchun 7 mavzuli reja topilmadi.", show_alert=True)
        return
    await callback.answer("Postlar yaratilmoqda...")
    status = await callback.message.edit_text("<pre>⠋ GENERATING 7 POSTS / QUEUE BUILD...</pre>")
    try:
        service = PostService(bot, settings, repo)
        best = await AnalyticsService(repo).best_hours()
        hour = int(best[0]["hour"]) if best else 18
        now = datetime.now(ZoneInfo(settings.timezone))
        first_run = (now + timedelta(days=1)).replace(hour=hour, minute=0, second=0, microsecond=0)
        created_ids: list[int] = []
        for index, item in enumerate(plan):
            variants = await AIService(settings, repo).write_post_variants(item["topic"])
            body = variants[0]
            post_id = await service.save_draft(body, item["style"], "bold", title=item["topic"])
            await scheduler.schedule_post(post_id, first_run + timedelta(days=index))
            created_ids.append(post_id)
        await repo.audit(callback.from_user.id, "ai_calendar_approved", f"post_ids={created_ids}")
        await state.clear()
        await status.edit_text(f"🟢 <b>[ CALENDAR DEPLOYED ]</b>\n7 ta post yaratildi va kuniga bittadan navbatga qo‘shildi.\nBirinchi vaqt: <code>{first_run:%Y-%m-%d %H:%M}</code>\nPostlar: <code>{', '.join('#'+str(x) for x in created_ids)}</code>", reply_markup=back_home_keyboard("admin:schedule"))
    except Exception as exc:
        await status.edit_text(f"🔴 Reja to‘liq yaratilmagan bo‘lishi mumkin: {html.escape(str(exc)[:250])}\nQoralamalarni Postlar bo‘limidan tekshiring.", reply_markup=back_home_keyboard("admin:schedule"))


@router.callback_query(lambda c: c.data == "schedule:best_time")
async def best_time(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    await callback.answer()
    hours = await AnalyticsService(repo).best_hours()
    if not hours:
        text = "Hozircha yetarli faollik ma'lumoti yo‘q. Bir necha kunlik event to‘plang."
    else:
        text = "\n".join(f"• Haftaning {int(x['weekday'])+1}-kuni, soat {int(x['hour']):02d}:00 — {x['n']} faollik" for x in hours)
    await callback.message.edit_text(f"{terminal_header('BEST PUBLISH TIME')}\n\n{html.escape(text)}\n\nBu tavsiya foydalanuvchi faolligi bo‘yicha taxminiy ko‘rsatkich.", reply_markup=back_home_keyboard("admin:schedule"))


@router.callback_query(lambda c: c.data == "schedule:queue")
async def queue_start(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    await callback.answer()
    drafts = await repo.list_posts(status="draft", limit=20)
    b = InlineKeyboardBuilder()
    for row in drafts:
        b.button(text=f"➕ #{row['id']} {str(row['title'])[:28]}", callback_data=f"schedule:queue_add:{row['id']}")
    b.button(text="✅ Navbatni vaqt bilan ishga tushirish", callback_data="schedule:queue_run")
    b.button(text="⬅️ Orqaga", callback_data="admin:schedule")
    b.adjust(1)
    await state.update_data(queue_ids=[])
    await callback.message.edit_text("Kontent navbati: qoralamalarni tanlang. Tanlangan postlar navbatga qo‘shiladi.", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("schedule:queue_add:"))
async def queue_add(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    post_id = int(callback.data.split(":")[2])
    data = await state.get_data()
    ids = list(data.get("queue_ids", []))
    if post_id not in ids:
        ids.append(post_id)
    await state.update_data(queue_ids=ids)
    await callback.answer(f"Navbatda: {len(ids)} ta")


@router.callback_query(lambda c: c.data == "schedule:queue_run")
async def queue_run(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    data = await state.get_data()
    ids = list(data.get("queue_ids", []))
    if not ids:
        await callback.answer("Avval qoralama tanlang.", show_alert=True)
        return
    await state.set_state(ScheduleStates.waiting_queue_time)
    await callback.answer()
    await callback.message.edit_text(f"Navbatda {len(ids)} ta post bor. Birinchi post uchun sana-vaqtni yuboring: <code>YYYY-MM-DD HH:MM</code>. Keyingilari har 24 soatda rejalashtiriladi.")


@router.message(ScheduleStates.waiting_queue_time)
async def queue_time_received(message: Message, state: FSMContext, settings: Settings, scheduler: SchedulerService, repo: Repo) -> None:
    data = await state.get_data()
    ids = list(data.get("queue_ids", []))
    try:
        start = datetime.strptime((message.text or "").strip(), "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(settings.timezone))
        if start <= datetime.now(ZoneInfo(settings.timezone)) or not ids:
            raise ValueError
    except ValueError:
        await message.answer("Kelajakdagi birinchi sana-vaqtni yuboring: <code>YYYY-MM-DD HH:MM</code>.")
        return
    for index, post_id in enumerate(ids):
        await scheduler.schedule_post(int(post_id), start + timedelta(days=index))
    await repo.audit(message.from_user.id, "content_queue_scheduled", f"post_ids={ids}")
    await state.clear()
    await message.answer(f"🟢 {len(ids)} ta qoralama navbatga qo‘shildi. Birinchi post: <code>{start:%Y-%m-%d %H:%M}</code>.", reply_markup=back_home_keyboard())


@router.callback_query(lambda c: c.data and c.data.startswith("schedule:view:"))
async def view_scheduled(callback: CallbackQuery, settings: Settings, repo: Repo, scheduler: SchedulerService) -> None:
    if not await require_admin(callback, settings):
        return
    post_id = int(callback.data.split(":")[2])
    post = await repo.get_post(post_id)
    if not post:
        await callback.answer("Post topilmadi.", show_alert=True)
        return
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Post matnini tahrirlash", callback_data=f"schedule:edit:{post_id}")
    b.button(text="⏱ Vaqtni o‘zgartirish", callback_data=f"schedule:reschedule:{post_id}")
    b.button(text="🗑 Rejani bekor qilish", callback_data=f"schedule:delete:{post_id}")
    b.button(text="⬅️ Orqaga", callback_data="admin:schedule")
    b.adjust(1)
    await callback.answer()
    await callback.message.edit_text(f"<b>#{post_id} {html.escape(post['title'])}</b>\nHolat: {post['status']}\nVaqt: <code>{html.escape(str(post.get('scheduled_at') or post.get('recurrence') or ''))}</code>", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("schedule:edit:"))
async def edit_scheduled_start(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    post_id = int(callback.data.split(":")[2])
    post = await repo.get_post(post_id)
    if not post or post.get("status") not in {"scheduled", "draft", "failed"}:
        await callback.answer("Faqat rejalashtirilgan/qoralama post tahrirlanadi.", show_alert=True)
        return
    await state.clear()
    await state.update_data(post_id=post_id)
    await state.set_state(ScheduleStates.waiting_post_edit)
    await callback.answer()
    await callback.message.edit_text(f"#{post_id} uchun yangi matnni Telegram HTML formatida yuboring (4096 belgi, media caption bo‘lsa 1024).", reply_markup=back_home_keyboard("admin:schedule"))


@router.message(ScheduleStates.waiting_post_edit)
async def edit_scheduled_save(message: Message, state: FSMContext, repo: Repo) -> None:
    from bot.services.post_service import extract_title, sanitize_telegram_html
    post_id = int((await state.get_data()).get("post_id", 0))
    post = await repo.get_post(post_id)
    raw = (message.text or message.caption or "").strip()
    limit = 1024 if post and post.get("media_type") else 4096
    if not post or not raw or len(raw) > limit:
        await message.answer(f"Matn 1–{limit} belgi oralig‘ida bo‘lsin.")
        return
    safe = sanitize_telegram_html(raw)
    await repo.update_post(post_id, body_html=safe, title=extract_title(safe))
    await repo.audit(message.from_user.id, "scheduled_post_edited", str(post_id))
    await state.clear()
    await message.answer(f"🟢 #{post_id} post matni yangilandi. Rejalashtirish vaqti saqlandi.", reply_markup=back_home_keyboard("admin:schedule"))


@router.callback_query(lambda c: c.data and c.data.startswith("schedule:reschedule:"))
async def reschedule_start(callback: CallbackQuery, settings: Settings, state: FSMContext, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    post_id = int(callback.data.split(":")[2])
    post = await repo.get_post(post_id)
    if not post:
        await callback.answer("Rejadagi post topilmadi.", show_alert=True)
        return
    await state.clear()
    await state.update_data(post_id=post_id)
    await state.set_state(ScheduleStates.waiting_time)
    await callback.answer()
    await callback.message.edit_text(f"#{post_id} uchun yangi vaqtni yuboring: <code>YYYY-MM-DD HH:MM</code> ({settings.timezone}).", reply_markup=back_home_keyboard("admin:schedule"))


@router.callback_query(lambda c: c.data and c.data.startswith("schedule:delete:"))
async def delete_scheduled(callback: CallbackQuery, settings: Settings, repo: Repo, scheduler: SchedulerService) -> None:
    if not await require_admin(callback, settings):
        return
    post_id = int(callback.data.split(":")[2])
    scheduler.remove_job(post_id)
    await repo.update_post(post_id, status="draft", scheduled_at=None, recurrence=None)
    await repo.audit(callback.from_user.id, "schedule_cancelled", str(post_id))
    await callback.answer("Reja bekor qilindi.")
    await callback.message.edit_text(f"🟢 #{post_id} reja bekor qilindi; qoralama saqlandi.", reply_markup=back_home_keyboard("admin:schedule"))
