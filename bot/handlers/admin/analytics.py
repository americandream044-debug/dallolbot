"""Advanced admin analytics, chart delivery, AI analysis, and CSV exports."""
from __future__ import annotations

import csv
import html
import io
import json
from datetime import datetime, timezone

from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import Settings
from bot.db.repo import Repo
from bot.middlewares.admin_only import require_admin
from bot.services.ai_service import AIService
from bot.services.analytics_service import AnalyticsService
from bot.services.charts import render_dashboard
from bot.ui.fx import run_with_loading
from bot.ui.keyboards import back_home_keyboard
from bot.ui.theme import terminal_header

router = Router(name="admin_analytics")


class AnalyticsStates(StatesGroup):
    waiting_views = State()
    waiting_question = State()


@router.callback_query(lambda c: c.data == "admin:analytics")
async def analytics_home(callback: CallbackQuery, settings: Settings, repo: Repo, bot: Bot, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await callback.answer()
    await state.clear()
    analytics = AnalyticsService(repo)
    data = await analytics.dashboard()
    image = await render_dashboard(data)
    buttons = InlineKeyboardBuilder()
    for label, key in (("👥 Foydalanuvchilar", "analytics:users"), ("♻️ Retention / churn", "analytics:retention"), ("📣 Kontent", "analytics:content"), ("💬 Support", "analytics:support"), ("🧩 Murojaat mavzulari", "analytics:topics"), ("🧠 AI tahlilchi", "analytics:ai"), ("❓ Savol berish", "analytics:ask"), ("📤 CSV eksport", "analytics:export")):
        buttons.button(text=label, callback_data=key)
    buttons.button(text="🏠 Menyu", callback_data="admin:home")
    buttons.adjust(2, 2, 2, 1, 1)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await bot.send_photo(callback.from_user.id, BufferedInputFile(image.getvalue(), filename="analytics_dashboard.png"), caption=f"{terminal_header('ANALYTICS DASHBOARD')}\n\nKo‘rsatkichlar real event va bot ma'lumotlaridan hisoblangan. Telegram Bot API kanal postlarining ko‘rishlar sonini bermaydi.", reply_markup=buttons.as_markup())


@router.callback_query(lambda c: c.data == "analytics:users")
async def users_report(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    data = await AnalyticsService(repo).dashboard()
    stats = data.get("summary", {})
    sources = data.get("sources", [])
    lines = [terminal_header("USER INTELLIGENCE"), "", f"Jami: <b>{stats.get('total_users',0)}</b>", f"Bugun yangi: <b>{stats.get('today_users',0)}</b>", f"7 kun yangi: <b>{stats.get('week_users',0)}</b>", f"30 kun yangi: <b>{stats.get('month_users',0)}</b>", f"DAU / WAU / MAU: <b>{stats.get('dau',0)} / {stats.get('wau',0)} / {stats.get('mau',0)}</b>", "", "<b>Manbalar:</b>"]
    lines += [f"• {html.escape(str(row['source']))}: {row['n']}" for row in sources]
    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=back_home_keyboard("admin:analytics"))


@router.callback_query(lambda c: c.data == "analytics:retention")
async def retention_report(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    data = await AnalyticsService(repo).dashboard()
    service = AnalyticsService(repo)
    retention = await service.retention()
    cohorts = await service.retention_cohorts(8)
    joins = data.get("joins_leaves", [])
    lines = [terminal_header("RETENTION / CHURN"), "", f"Oxirgi yetilgan cohortlar: D1 <b>{retention['d1']}%</b> · D7 <b>{retention['d7']}%</b> · D30 <b>{retention['d30']}%</b>", "", "<b>Cohort jadvali:</b>", "<code>Sana       Users   D1     D7     D30</code>"]
    for cohort in cohorts:
        values = ["—" if cohort[f"d{day}"] is None else f"{cohort[f'd{day}']:.1f}%" for day in (1, 7, 30)]
        lines.append(f"<code>{cohort['day']}  {cohort['total']:>5}  {values[0]:>6} {values[1]:>6} {values[2]:>6}</code>")
    join_count = sum(int(row["n"]) for row in joins if row["type"] == "channel_join")
    leave_count = sum(int(row["n"]) for row in joins if row["type"] == "channel_leave")
    churn_rate = (leave_count / join_count * 100) if join_count else 0.0
    lines += ["", f"30 kun net o‘sish: <b>{join_count - leave_count:+d}</b>", f"Churn (leave / join): <b>{churn_rate:.1f}%</b>", "", "<b>Kanal join / leave (30 kun):</b>"]
    lines += [f"• {html.escape(str(row['day']))} · {html.escape(str(row['type']))}: {row['n']}" for row in joins[-16:]]
    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=back_home_keyboard("admin:analytics"))


@router.callback_query(lambda c: c.data == "analytics:content")
async def content_report(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    data = await repo.get_analytics()
    posts = data.get("posts", [])
    rows = []
    for post in posts:
        try:
            counts = json.loads(post.get("reactions", "{}"))
        except json.JSONDecodeError:
            counts = {}
        total_reactions = sum(int(v) for v in counts.values())
        views = post.get("views_manual")
        er = round(total_reactions / int(views) * 100, 2) if views and int(views) > 0 else None
        rows.append((post, total_reactions, er))
    rows.sort(key=lambda x: x[1], reverse=True)
    lines = [terminal_header("CONTENT PERFORMANCE"), "", "<i>Ko‘rishlar soni Bot API orqali mavjud emas. ER faqat admin kiritgan views bo‘lsa hisoblanadi.</i>", ""]
    for post, reactions, er in rows[:12]:
        lines.append(f"• <code>#{post['id']}</code> {html.escape(post['title'][:40])} — 🔥 {reactions} · ER: {str(er)+'%' if er is not None else 'views kiritilmagan'}")
    style_counts: dict[str, list[int]] = {}
    tag_counts: dict[str, list[int]] = {}
    for post, reactions, _ in rows:
        style_counts.setdefault(str(post.get("style") or "?"), []).append(reactions)
        tag_counts.setdefault(str(post.get("tag") or "?"), []).append(reactions)
    lines += ["", "<b>Uslub bo‘yicha o‘rtacha reaksiya:</b>"]
    lines += [f"• {html.escape(key)}: {sum(vals)/len(vals):.1f}" for key, vals in sorted(style_counts.items())]
    lines += ["", "<b>Teg bo‘yicha o‘rtacha reaksiya:</b>"]
    lines += [f"• {html.escape(key)}: {sum(vals)/len(vals):.1f}" for key, vals in sorted(tag_counts.items())]
    if rows:
        lines += ["", "<b>Top 5:</b>"] + [f"• #{p['id']} · {n} reaksiya" for p, n, _ in rows[:5]]
        lines += ["<b>Past 5:</b>"] + [f"• #{p['id']} · {n} reaksiya" for p, n, _ in rows[-5:]]
    distribution: dict[str, int] = {}
    for post in posts:
        try:
            for emoji, count in json.loads(post.get("reactions", "{}")).items():
                distribution[emoji] = distribution.get(emoji, 0) + int(count)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    if distribution:
        lines += ["", "<b>Emoji taqsimoti:</b>"] + [f"• {html.escape(k)}: {v}" for k, v in sorted(distribution.items(), key=lambda item: item[1], reverse=True)[:8]]
    from collections import defaultdict
    hour_scores = defaultdict(list)
    day_scores = defaultdict(list)
    for post, reactions, _ in rows:
        published = post.get("published_at")
        if not published:
            continue
        try:
            moment = datetime.fromisoformat(str(published))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            local = moment.astimezone(settings.tz)
            hour_scores[local.hour].append(reactions)
            day_scores[local.strftime("%A")].append(reactions)
        except (ValueError, TypeError):
            continue
    if hour_scores:
        best_hour = max(hour_scores, key=lambda key: sum(hour_scores[key]) / len(hour_scores[key]))
        lines += ["", f"Eng yaxshi post vaqti (o‘rtacha reaksiya): <b>{best_hour:02d}:00</b>"]
    if day_scores:
        best_day = max(day_scores, key=lambda key: sum(day_scores[key]) / len(day_scores[key]))
        lines.append(f"Eng yaxshi hafta kuni: <b>{html.escape(best_day)}</b>")
    b = InlineKeyboardBuilder()
    for post, _, _ in rows[:8]:
        b.button(text=f"👁 Views: #{post['id']}", callback_data=f"analytics:views:{post['id']}")
    b.button(text="⬅️ Orqaga", callback_data="admin:analytics")
    b.adjust(2, 2, 2, 2, 1)
    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("analytics:views:"))
async def ask_manual_views(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    post_id = int(callback.data.split(":")[2])
    await state.clear()
    await state.update_data(post_id=post_id)
    await state.set_state(AnalyticsStates.waiting_views)
    await callback.answer()
    await callback.message.edit_text(f"#{post_id} post uchun kanal statistikangizdan ko‘rishlar sonini kiriting (faqat butun musbat son):", reply_markup=back_home_keyboard("admin:analytics"))


@router.message(AnalyticsStates.waiting_views)
async def save_manual_views(message: Message, state: FSMContext, repo: Repo) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) < 1 or int(raw) > 2_000_000_000:
        await message.answer("1 dan 2 000 000 000 gacha butun son kiriting.")
        return
    post_id = int((await state.get_data()).get("post_id", 0))
    await repo.update_post(post_id, views_manual=int(raw))
    await repo.audit(message.from_user.id, "manual_post_views", f"post={post_id}; views={raw}")
    await state.clear()
    await message.answer(f"🟢 #{post_id} uchun views={raw} saqlandi.", reply_markup=back_home_keyboard("admin:analytics"))


@router.callback_query(lambda c: c.data == "analytics:topics")
async def ticket_topic_clusters(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    import re
    import time
    cached_at = await repo.get_setting("ticket_topics_cached_at", "0")
    cached_text = await repo.get_setting("ticket_topics_cache", "")
    try:
        fresh = time.time() - float(cached_at) < 86400 and bool(cached_text)
    except ValueError:
        fresh = False
    await callback.answer("Keshdan ochilmoqda..." if fresh else "Murojaatlar tahlil qilinmoqda...")
    if fresh:
        await callback.message.edit_text(f"{terminal_header('TICKET TOPIC CLUSTERS')}\n\n{html.escape(cached_text)}\n\n<code>[ CACHE: 24H ]</code>", reply_markup=back_home_keyboard("admin:analytics"))
        return
    rows = await repo.db.fetchall("SELECT text FROM ticket_messages WHERE sender='user' AND text!='' ORDER BY id DESC LIMIT 80")
    messages = []
    for row in rows:
        value = str(row["text"] or "").strip()
        value = re.sub(r"https?://\S+|@\w+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b\d{5,}\b", "[maxfiy ma'lumot]", value)
        if value:
            messages.append(value[:240])
    if not messages:
        await callback.message.edit_text("Murojaat matnlari hali yetarli emas.", reply_markup=back_home_keyboard("admin:analytics"))
        return
    status = await callback.message.edit_text("<pre>⠋ SUPPORT TOPIC CLUSTERING...</pre>")
    try:
        report = await run_with_loading(status, AIService(settings, repo).generate(
            "Siz support analitigisiz. O‘zbek tilida so‘nggi murojaatlarni 5–8 ta mavzuga guruhlang. Har bir mavzu uchun nom, taxminiy son, qisqa tavsif va amaliy tavsiya bering. Foydalanuvchini aniqlashga urinmang; aniq bo‘lmagan sonlarni taxmin deb belgilang.",
            "ANONIMLASHTIRILGAN MUROJAATLAR:\n" + "\n---\n".join(messages), 0.25,
        ), await repo.get_setting("effects", "1") == "1")
        await repo.set_setting("ticket_topics_cache", report[:3500])
        await repo.set_setting("ticket_topics_cached_at", str(time.time()))
        await status.edit_text(f"{terminal_header('TICKET TOPIC CLUSTERS')}\n\n{html.escape(report[:3500])}\n\n<code>[ CACHE: 24H ]</code>", reply_markup=back_home_keyboard("admin:analytics"))
    except Exception as exc:
        await status.edit_text(f"🔴 {html.escape(str(exc)[:250])}", reply_markup=back_home_keyboard("admin:analytics"))


@router.callback_query(lambda c: c.data == "analytics:support")
async def support_report(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    metrics = await repo.ticket_metrics()
    counts = metrics["counts"]
    tags = await repo.db.fetchall("SELECT tag,COUNT(*) n FROM tickets GROUP BY tag ORDER BY n DESC")
    avg = int(metrics["avg_first_reply_seconds"])
    lines = [terminal_header("SUPPORT INTELLIGENCE"), "", f"Yangi: {counts.get('new',0)}", f"Jarayonda: {counts.get('in_progress',0)}", f"Yopilgan: {counts.get('closed',0)}", f"Birinchi javob o‘rtachasi: {avg//3600} soat {(avg%3600)//60} daqiqa", "", "<b>Teglar:</b>"]
    lines += [f"• {html.escape(row['tag'])}: {row['n']}" for row in tags]
    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=back_home_keyboard("admin:analytics"))


@router.callback_query(lambda c: c.data == "analytics:ai")
async def ai_analyst(callback: CallbackQuery, settings: Settings, repo: Repo) -> None:
    if not await require_admin(callback, settings):
        return
    await callback.answer()
    status = await callback.message.edit_text("<pre>⠋ AI ANALYST / AGGREGATING...</pre>")
    try:
        compact = await AnalyticsService(repo).compact_json()
        report = await run_with_loading(status, AIService(settings, repo).generate(
            "Siz Telegram kanal analitigi bo‘yicha maslahatchisiz. O‘zbek lotinida aniq hisobot yozing. 5 ta muhim insight va 3 ta aniq keyingi harakat bo‘lsin. Ko‘rishlar soni berilmagan bo‘lsa, taxmin qilmang.",
            f"Quyidagi agregat statistikani tahlil qiling:\n{compact}", 0.35,
        ), await repo.get_setting("effects", "1") == "1")
        await status.edit_text(f"{terminal_header('AI ANALYST REPORT')}\n\n{html.escape(report[:3500])}", reply_markup=back_home_keyboard("admin:analytics"))
    except Exception as exc:
        await status.edit_text(f"🔴 {html.escape(str(exc)[:250])}", reply_markup=back_home_keyboard("admin:analytics"))


@router.callback_query(lambda c: c.data == "analytics:ask")
async def ai_question_start(callback: CallbackQuery, settings: Settings, state: FSMContext) -> None:
    if not await require_admin(callback, settings):
        return
    await state.set_state(AnalyticsStates.waiting_question)
    await callback.answer()
    await callback.message.edit_text("Statistikaga asoslangan savolingizni yozing. Masalan: Nega bu hafta o‘sish sekinlashdi?", reply_markup=back_home_keyboard("admin:analytics"))


@router.message(AnalyticsStates.waiting_question)
async def ai_question(message: Message, state: FSMContext, settings: Settings, repo: Repo) -> None:
    question = (message.text or "").strip()
    if not question or len(question) > 1000:
        await message.answer("Savol 1–1000 belgi oralig‘ida bo‘lsin.")
        return
    status = await message.answer("<pre>⠋ ANALYST IS THINKING...</pre>")
    try:
        compact = await AnalyticsService(repo).compact_json()
        answer = await run_with_loading(status, AIService(settings, repo).generate(
            "Siz kanal analitikasisiz. Faqat taqdim etilgan statistikaga tayangan holda o‘zbek tilida javob bering. Ma'lumot yetarli bo‘lmasa, buni ayting.",
            f"STATISTIKA:\n{compact}\n\nSAVOL:\n{question}", 0.35,
        ), await repo.get_setting("effects", "1") == "1")
        await status.edit_text(f"{terminal_header('AI ANALYST')}\n\n{html.escape(answer[:3500])}", reply_markup=back_home_keyboard("admin:analytics"))
    except Exception as exc:
        await status.edit_text(f"🔴 {html.escape(str(exc)[:250])}", reply_markup=back_home_keyboard("admin:analytics"))
    await state.clear()


@router.callback_query(lambda c: c.data == "analytics:export")
async def export_menu(callback: CallbackQuery, settings: Settings) -> None:
    if not await require_admin(callback, settings):
        return
    b = InlineKeyboardBuilder()
    for table in ("users", "tickets", "posts", "events"):
        b.button(text=f"📄 {table}.csv", callback_data=f"analytics:export:{table}")
    b.button(text="⬅️ Orqaga", callback_data="admin:analytics")
    b.adjust(2, 2, 1)
    await callback.answer()
    await callback.message.edit_text("CSV eksport turini tanlang:", reply_markup=b.as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("analytics:export:"))
async def export_csv(callback: CallbackQuery, settings: Settings, repo: Repo, bot: Bot) -> None:
    if not await require_admin(callback, settings):
        return
    table = callback.data.split(":")[2]
    if table not in {"users", "tickets", "posts", "events"}:
        await callback.answer("Eksport turi noto‘g‘ri.", show_alert=True)
        return
    rows = await repo.export_rows(table)
    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    else:
        buffer.write("empty\n")
    data = buffer.getvalue().encode("utf-8-sig")
    await bot.send_document(callback.from_user.id, BufferedInputFile(data, filename=f"{table}.csv"), caption=f"🟢 {table} eksporti · {len(rows)} qator")
    await callback.answer("CSV yuborildi.")


async def send_weekly_report(bot: Bot, settings: Settings, repo: Repo) -> None:
    """Send the weekly PNG dashboard and concise AI analysis to each admin."""
    analytics = AnalyticsService(repo)
    data = await analytics.dashboard()
    image = await render_dashboard(data)
    summary = "Haftalik hisobot tayyor. AI tahlilini ochish uchun admin panel → Tahlil → AI tahlilchi bo‘limiga o‘ting."
    try:
        compact = await analytics.compact_json()
        from bot.ai.client import generate
        summary = await generate("Siz o‘zbek tilidagi kanal analitigisiz. 3 ta muhim xulosa va 2 ta aniq tavsiya bering. Ko‘rishlar sonini uydirmang.", compact, 0.3)
    except Exception:
        pass
    for admin_id in settings.admin_ids:
        await bot.send_photo(admin_id, BufferedInputFile(image.getvalue(), filename="weekly_report.png"), caption=f"📊 <b>HAFTALIK HISOBOT</b>\n{html.escape(summary[:800])}")
