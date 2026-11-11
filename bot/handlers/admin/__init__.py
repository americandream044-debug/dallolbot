"""Protected admin router assembly."""
from aiogram import Router

from bot.middlewares.admin_only import AdminFilter
from bot.handlers.admin import (
    ai_prompts, analytics, broadcast, panel, posts, scheduler_ui, settings, tickets, tools, users,
)

router = Router(name="admin_root")
for child in (panel.router, ai_prompts.router, posts.router, scheduler_ui.router, tickets.router, analytics.router, broadcast.router, users.router, tools.router, settings.router):
    child.message.filter(AdminFilter())
    child.callback_query.filter(AdminFilter())
    router.include_router(child)
