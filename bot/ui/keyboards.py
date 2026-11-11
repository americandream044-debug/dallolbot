"""Inline keyboards for public and administrator flows."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def subscription_keyboard(channel_url: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📢 Kanalga o'tish", url=channel_url)
    b.button(text="✅ Tekshirish", callback_data="sub:check")
    b.adjust(1)
    return b.as_markup()


def user_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💬 Adminga yozish", callback_data="support:new")
    return b.as_markup()


def admin_menu_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    rows = [
        ("🧠 AI Prompt", "admin:ai"), ("✍️ Post yozish", "admin:post"),
        ("🕒 Rejalashtirish", "admin:schedule"), ("💬 Murojaatlar", "admin:tickets"),
        ("📊 Tahlil", "admin:analytics"), ("📢 Broadcast", "admin:broadcast"),
        ("👥 Foydalanuvchilar", "admin:users"), ("🛠 Asboblar", "admin:tools"),
        ("⚙️ Sozlamalar", "admin:settings"),
    ]
    for label, data in rows:
        b.button(text=label, callback_data=data)
    b.adjust(2, 2, 2, 2, 1)
    return b.as_markup()


def back_home_keyboard(back: str = "admin:home") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ Orqaga", callback_data=back)
    b.button(text="🏠 Menyu", callback_data="admin:home")
    b.adjust(2)
    return b.as_markup()


def categories_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for label, key in (("💻 Kod", "code"), ("✍️ Matn", "text"), ("🎨 Rasm", "image"), ("📊 Biznes", "business"), ("🎓 O'qish", "study"), ("🧩 Boshqa", "other")):
        b.button(text=label, callback_data=f"ai:cat:{key}")
    b.button(text="🏠 Menyu", callback_data="admin:home")
    b.adjust(2, 2, 2, 1)
    return b.as_markup()


def prompt_actions_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for label, data in (("🔄 Qayta yaratish", "ai:regen"), ("📈 Kuchaytirish", "ai:improve"), ("✂️ Qisqartirish", "ai:shorten"), ("🌐 Inglizcha", "ai:english"), ("📢 Kanalga joylash", "ai:post"), ("💾 Saqlash", "ai:save"), ("📚 Kutubxona", "ai:library"), ("🏠 Menyu", "admin:home")):
        b.button(text=label, callback_data=data)
    b.adjust(2, 2, 2, 2)
    return b.as_markup()


def styles_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for label, value in (("🖥 Terminal", "Terminal"), ("🗂 Card", "Card"), ("▫️ Minimal", "Minimal"), ("📝 Script", "Script")):
        b.button(text=label, callback_data=f"post:style:{value}")
    b.button(text="⬅️ Orqaga", callback_data="admin:post")
    b.adjust(2, 2, 1)
    return b.as_markup()


def fonts_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for label, value in (("𝐁𝐨𝐥𝐝", "bold"), ("𝗦𝗮𝗻𝘀", "sans"), ("𝑩𝒐𝒍𝒅𝑰𝒕𝒂𝒍𝒊𝒄", "bolditalic"), ("𝓢𝓬𝓻𝓲𝓹𝓽", "script"), ("𝙼𝚘𝚗𝚘", "mono"), ("sᴍᴀʟʟ ᴄᴀᴘs", "smallcaps")):
        b.button(text=label, callback_data=f"post:font:{value}")
    b.adjust(2, 2, 2)
    return b.as_markup()


def preview_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for label, data in (
        ("✅ Hozir joylash", "post:publish"), ("🕒 Rejalashtirish", "post:schedule"),
        ("✏️ Tahrirlash", "post:edit"), ("🔁 Qayta yozish", "post:rewrite"),
        ("🧰 Asboblar", "post:tools"), ("🔗 Tugmalar", "post:buttons"),
        ("📊 So‘rovnoma", "post:poll"), ("🗑 Bekor", "post:cancel"),
    ):
        b.button(text=label, callback_data=data)
    b.adjust(2, 2, 2, 2)
    return b.as_markup()


def confirm_keyboard(yes: str, no: str = "admin:home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=yes),
        InlineKeyboardButton(text="❌ Bekor", callback_data=no),
    ]])


def pagination_keyboard(prefix: str, page: int, has_next: bool = True) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if page > 0:
        b.button(text="⬅️", callback_data=f"{prefix}:page:{page-1}")
    if has_next:
        b.button(text="➡️", callback_data=f"{prefix}:page:{page+1}")
    b.button(text="🏠 Menyu", callback_data="admin:home")
    b.adjust(2, 1)
    return b.as_markup()


def settings_keyboard(values: dict[str, str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    toggles = (
        ("subscription_required", "🔐 Majburiy obuna"), ("effects", "✨ Effektlar"),
        ("auto_reaction", "🔥 Avto-reaksiya"), ("notify_new_ticket", "🔔 Yangi murojaat xabari"),
        ("weekly_report", "📊 Haftalik hisobot"),
    )
    for key, title in toggles:
        state = "ON 🟢" if values.get(key, "0") == "1" else "OFF ⚫"
        b.button(text=f"{title}: {state}", callback_data=f"settings:toggle:{key}")
    b.button(text=f"Reaksiya: {values.get('reaction_emoji','🔥')}", callback_data="settings:reaction")
    b.button(text=f"Hisobot kuni: {values.get('weekly_report_day','sun')}", callback_data="settings:report_day")
    b.button(text=f"Hisobot vaqti: {values.get('weekly_report_time','20:00')}", callback_data="settings:report_time")
    b.button(text=f"AI kunlik limiti: {values.get('daily_ai_cap','30')}", callback_data="settings:ai_cap")
    b.button(text=f"AI narx koeff.: {values.get('ai_cost_per_1k_chars_usd','0')} USD/1k belgi", callback_data="settings:cost_rate")
    b.button(text=f"Anti-spam: {values.get('anti_spam_seconds','30')} soniya", callback_data="settings:spam")
    b.button(text=f"Post uslubi: {values.get('default_post_style','Card')}", callback_data="settings:post_style")
    b.button(text=f"Sarlavha shrifti: {values.get('default_heading_font','bold')}", callback_data="settings:post_font")
    b.button(text="👋 Welcome matni", callback_data="settings:welcome")
    b.button(text="🏠 Menyu", callback_data="admin:home")
    b.adjust(1)
    return b.as_markup()


def ticket_card_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="↩️ Javob", callback_data=f"ticket:reply:{ticket_id}")
    b.button(text="🤖 AI javob", callback_data=f"ticket:ai:{ticket_id}")
    b.button(text="🏷 Teg", callback_data=f"ticket:tag:{ticket_id}")
    b.button(text="⏳ Jarayonda", callback_data=f"ticket:status:{ticket_id}:in_progress")
    b.button(text="✅ Yopish", callback_data=f"ticket:status:{ticket_id}:closed")
    b.button(text="⭐ Muhim", callback_data=f"ticket:star:{ticket_id}")
    b.button(text="🚫 Ban", callback_data=f"ticket:ban:{ticket_id}")
    b.button(text="⚡ Tez javob", callback_data=f"ticket:quick:{ticket_id}")
    b.button(text="⬅️ Ro'yxat", callback_data="admin:tickets")
    b.adjust(2, 2, 2, 2, 1)
    return b.as_markup()
