"""Channel reaction count update handler."""
from aiogram import Router

from bot.config import Settings
from bot.db.repo import Repo
from bot.services.reaction_service import ReactionService

router = Router(name="reaction_updates")


@router.message_reaction_count()
async def reaction_count_update(event, settings: Settings, repo: Repo, bot) -> None:
    """Persist a reaction-count snapshot for a known channel post."""
    await ReactionService(bot, settings, repo).capture_update(event)
