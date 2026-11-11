"""Uzbek-language interface text."""
import html

from bot.ui.theme import BANNER, terminal_header


def welcome(name: str, custom: str) -> str:
    return f"<pre>{BANNER}</pre>\n{terminal_header('WELCOME')}\n{html.escape(name)} · {html.escape(custom)}"


def subscription_text(channel: str) -> str:
    return (
        f"{terminal_header('SUBSCRIPTION REQUIRED')}\n\n"
        "🔒 Botdan foydalanish uchun avval kanalga obuna bo‘ling.\n"
        f"<code>@{channel.lstrip('@')}</code>"
    )


def main_menu_text(stats: dict) -> str:
    return (
        f"<pre>{BANNER}</pre>\n"
        f"{terminal_header('ADMIN CONTROL CENTER')}\n"
        "<pre>━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Foydalanuvchilar : {stats.get('total_users', 0)}\n"
        f"🆕 Bugun             : {stats.get('today_users', 0)}\n"
        f"💬 Ochiq murojaatlar : {stats.get('open_tickets', 0)}\n"
        f"🕒 Rejalashtirilgan  : {stats.get('scheduled_posts', 0)}\n"
        f"🛰 DAU               : {stats.get('dau', 0)}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 CORE: ONLINE    🟣 AI: READY</pre>"
        "Bo‘limni tanlang:"
    )


def admin_denied() -> str:
    return "Buyruq topilmadi"
