"""Application repository: SQL is kept out of Telegram handlers."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any

from bot.db.database import Database


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Repo:
    """Thin repository with focused methods used by handlers and services."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def upsert_user(self, user_id: int, username: str | None, first_name: str, source: str | None = None) -> None:
        await self.db.execute(
            """INSERT INTO users(id,username,first_name,source,joined_at,last_seen)
               VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
               username=excluded.username, first_name=excluded.first_name,
               last_seen=excluded.last_seen, source=COALESCE(users.source, excluded.source)""",
            (user_id, username, first_name or "", source, utc_now(), utc_now()),
        )

    async def touch_user(self, user_id: int) -> None:
        await self.db.execute("UPDATE users SET last_seen=? WHERE id=?", (utc_now(), user_id))

    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM users WHERE id=?", (user_id,))

    async def search_users(self, term: str, limit: int = 20) -> list[dict[str, Any]]:
        value = term.strip().lstrip("@")
        if value.isdigit():
            return await self.db.fetchall("SELECT * FROM users WHERE id=? LIMIT ?", (int(value), limit))
        return await self.db.fetchall(
            "SELECT * FROM users WHERE username LIKE ? OR first_name LIKE ? ORDER BY last_seen DESC LIMIT ?",
            (f"%{value}%", f"%{value}%", limit),
        )

    async def set_user_ban(self, user_id: int, banned: bool) -> None:
        await self.db.execute("UPDATE users SET is_banned=? WHERE id=?", (int(banned), user_id))

    async def set_user_note(self, user_id: int, note: str) -> None:
        await self.db.execute("UPDATE users SET note=? WHERE id=?", (note, user_id))

    async def is_banned(self, user_id: int) -> bool:
        row = await self.db.fetchone("SELECT is_banned FROM users WHERE id=?", (user_id,))
        return bool(row and row["is_banned"])

    async def count_users(self) -> int:
        row = await self.db.fetchone("SELECT COUNT(*) AS n FROM users")
        return int(row["n"] if row else 0)

    async def get_setting(self, key: str, default: str = "") -> str:
        row = await self.db.fetchone("SELECT value FROM settings WHERE key=?", (key,))
        return str(row["value"]) if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self.db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    async def get_settings(self) -> dict[str, str]:
        rows = await self.db.fetchall("SELECT key,value FROM settings")
        return {str(row["key"]): str(row["value"]) for row in rows}

    async def add_event(self, user_id: int | None, event_type: str, payload: dict[str, Any] | None = None) -> None:
        await self.db.execute(
            "INSERT INTO events(user_id,type,payload,ts) VALUES(?,?,?,?)",
            (user_id, event_type, json.dumps(payload or {}, ensure_ascii=False), datetime.now(timezone.utc).timestamp()),
        )

    async def audit(self, admin_id: int, action: str, details: str = "") -> None:
        await self.db.execute("INSERT INTO audit_log(admin_id,action,details,ts) VALUES(?,?,?,?)", (admin_id, action, details[:1000], utc_now()))
        await self.add_event(admin_id, "admin_action", {"action": action, "details": details[:300]})

    async def create_ticket(self, user_id: int) -> int:
        return await self.db.execute("INSERT INTO tickets(user_id,status,created_at) VALUES(?,'new',?)", (user_id, utc_now()))

    async def get_open_ticket(self, user_id: int) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM tickets WHERE user_id=? AND status!='closed' ORDER BY id DESC LIMIT 1", (user_id,))

    async def count_user_tickets_today(self, user_id: int) -> int:
        row = await self.db.fetchone("SELECT COUNT(*) AS n FROM tickets WHERE user_id=? AND date(created_at)=date('now')", (user_id,))
        return int(row["n"] if row else 0)

    async def add_ticket_message(self, ticket_id: int, sender: str, content_type: str, text: str = "", file_id: str | None = None) -> int:
        return await self.db.execute(
            "INSERT INTO ticket_messages(ticket_id,sender,content_type,text,file_id,created_at) VALUES(?,?,?,?,?,?)",
            (ticket_id, sender, content_type, text[:4000], file_id, utc_now()),
        )

    async def get_ticket(self, ticket_id: int) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT t.*,u.username,u.first_name,u.is_banned FROM tickets t JOIN users u ON u.id=t.user_id WHERE t.id=?", (ticket_id,))

    async def list_tickets(self, status: str = "all", limit: int = 15, offset: int = 0, tag: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status != "all":
            clauses.append("t.status=?")
            params.append(status)
        if tag:
            clauses.append("t.tag=?")
            params.append(tag)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.extend((limit, offset))
        return await self.db.fetchall(
            "SELECT t.*,u.username,u.first_name FROM tickets t JOIN users u ON u.id=t.user_id"
            + where + " ORDER BY t.is_starred DESC,t.created_at DESC LIMIT ? OFFSET ?",
            params,
        )

    async def search_tickets(self, term: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search tickets by ticket/user ID, username, first name, or message text."""
        needle = f"%{term.strip().lstrip('@')}%"
        return await self.db.fetchall(
            "SELECT DISTINCT t.id,t.user_id,t.status,t.tag,t.created_at,u.username,u.first_name "
            "FROM tickets t JOIN users u ON u.id=t.user_id "
            "LEFT JOIN ticket_messages tm ON tm.ticket_id=t.id "
            "WHERE CAST(t.id AS TEXT) LIKE ? OR CAST(t.user_id AS TEXT) LIKE ? "
            "OR u.username LIKE ? OR u.first_name LIKE ? OR tm.text LIKE ? "
            "ORDER BY t.is_starred DESC,t.created_at DESC LIMIT ?",
            (needle, needle, needle, needle, needle, limit),
        )

    async def ticket_history(self, ticket_id: int, limit: int = 30) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT * FROM ticket_messages WHERE ticket_id=? ORDER BY id DESC LIMIT ?", (ticket_id, limit))

    async def update_ticket(self, ticket_id: int, **fields: Any) -> None:
        allowed = {"status", "tag", "is_starred", "closed_at", "first_reply_at"}
        values = [(key, value) for key, value in fields.items() if key in allowed]
        if not values:
            return
        sql = ",".join(f"{key}=?" for key, _ in values)
        await self.db.execute(f"UPDATE tickets SET {sql} WHERE id=?", [v for _, v in values] + [ticket_id])

    async def ticket_metrics(self) -> dict[str, Any]:
        counts = await self.db.fetchall("SELECT status,COUNT(*) AS n FROM tickets GROUP BY status")
        response = await self.db.fetchone("SELECT AVG((julianday(first_reply_at)-julianday(created_at))*86400) AS seconds FROM tickets WHERE first_reply_at IS NOT NULL")
        return {"counts": {r["status"]: r["n"] for r in counts}, "avg_first_reply_seconds": round(response["seconds"] or 0) if response else 0}

    async def create_prompt(self, title: str, category: str, text: str) -> int:
        return await self.db.execute("INSERT INTO prompts(title,category,text,created_at) VALUES(?,?,?,?)", (title[:120], category, text, utc_now()))

    async def list_prompts(self, query: str = "", limit: int = 10, offset: int = 0) -> list[dict[str, Any]]:
        if query:
            return await self.db.fetchall("SELECT * FROM prompts WHERE title LIKE ? OR text LIKE ? ORDER BY is_favorite DESC,id DESC LIMIT ? OFFSET ?", (f"%{query}%", f"%{query}%", limit, offset))
        return await self.db.fetchall("SELECT * FROM prompts ORDER BY is_favorite DESC,id DESC LIMIT ? OFFSET ?", (limit, offset))

    async def get_prompt(self, prompt_id: int) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM prompts WHERE id=?", (prompt_id,))

    async def update_prompt(self, prompt_id: int, **fields: Any) -> None:
        allowed = {"title", "text", "is_favorite"}
        values = [(k, v) for k, v in fields.items() if k in allowed]
        if values:
            await self.db.execute("UPDATE prompts SET " + ",".join(f"{k}=?" for k, _ in values) + " WHERE id=?", [v for _, v in values] + [prompt_id])

    async def delete_prompt(self, prompt_id: int) -> None:
        await self.db.execute("DELETE FROM prompts WHERE id=?", (prompt_id,))

    async def create_post(self, title: str, body_html: str, style: str, font: str, status: str = "draft", scheduled_at: str | None = None, tag: str = "umumiy", media_type: str | None = None, media_file_id: str | None = None) -> int:
        return await self.db.execute(
            "INSERT INTO posts(title,body_html,style,font,status,scheduled_at,tag,media_type,media_file_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (title[:180], body_html, style, font, status, scheduled_at, tag, media_type, media_file_id, utc_now()),
        )

    async def get_post(self, post_id: int) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM posts WHERE id=?", (post_id,))

    async def update_post(self, post_id: int, **fields: Any) -> None:
        allowed = {"title", "body_html", "style", "font", "status", "scheduled_at", "recurrence", "channel_message_id", "published_at", "views_manual", "media_type", "media_file_id", "tag", "buttons_json", "poll_question", "poll_options_json", "poll_message_id"}
        values = [(k, v) for k, v in fields.items() if k in allowed]
        if values:
            await self.db.execute("UPDATE posts SET " + ",".join(f"{k}=?" for k, _ in values) + " WHERE id=?", [v for _, v in values] + [post_id])

    async def delete_post(self, post_id: int) -> None:
        await self.db.execute("DELETE FROM posts WHERE id=?", (post_id,))

    async def list_posts(self, status: str | None = None, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        if status:
            return await self.db.fetchall("SELECT * FROM posts WHERE status=? ORDER BY id DESC LIMIT ? OFFSET ?", (status, limit, offset))
        return await self.db.fetchall("SELECT * FROM posts ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))

    async def scheduled_posts(self) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT * FROM posts WHERE (status='scheduled' AND scheduled_at IS NOT NULL) OR recurrence IS NOT NULL ORDER BY COALESCE(scheduled_at,created_at)")

    async def post_by_message_id(self, message_id: int) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM posts WHERE channel_message_id=?", (message_id,))

    async def save_reaction_snapshot(self, post_id: int, counts: dict[str, int]) -> None:
        await self.db.execute("INSERT INTO reaction_snapshots(post_id,emoji_counts_json,taken_at) VALUES(?,?,?)", (post_id, json.dumps(counts, ensure_ascii=False), utc_now()))

    async def record_ai_usage(self, input_chars: int, output_chars: int) -> None:
        day = datetime.now(timezone.utc).date().isoformat()
        await self.db.execute(
            "INSERT INTO ai_usage(day,requests,input_chars,output_chars) VALUES(?,1,?,?) ON CONFLICT(day) DO UPDATE SET requests=requests+1,input_chars=input_chars+excluded.input_chars,output_chars=output_chars+excluded.output_chars",
            (day, input_chars, output_chars),
        )
        await self.add_event(None, "ai_call", {"input_chars": input_chars, "output_chars": output_chars})

    async def ai_usage_today(self) -> dict[str, int]:
        day = datetime.now(timezone.utc).date().isoformat()
        row = await self.db.fetchone("SELECT * FROM ai_usage WHERE day=?", (day,))
        return {k: int(row[k]) for k in ("requests", "input_chars", "output_chars")} if row else {"requests": 0, "input_chars": 0, "output_chars": 0}

    async def get_stats(self) -> dict[str, Any]:
        row = await self.db.fetchone("""SELECT
          (SELECT COUNT(*) FROM users) total_users,
          (SELECT COUNT(*) FROM users WHERE date(joined_at)=date('now')) today_users,
          (SELECT COUNT(*) FROM users WHERE julianday(joined_at)>=julianday('now','-7 day')) week_users,
          (SELECT COUNT(*) FROM users WHERE julianday(joined_at)>=julianday('now','-30 day')) month_users,
          (SELECT COUNT(*) FROM tickets WHERE status!='closed') open_tickets,
          (SELECT COUNT(*) FROM posts WHERE status='scheduled' OR recurrence IS NOT NULL) scheduled_posts,
          (SELECT COUNT(*) FROM users WHERE julianday(last_seen)>=julianday('now','-1 day')) dau,
          (SELECT COUNT(*) FROM users WHERE julianday(last_seen)>=julianday('now','-7 day')) wau,
          (SELECT COUNT(*) FROM users WHERE julianday(last_seen)>=julianday('now','-30 day')) mau""")
        return row or {}

    async def get_analytics(self) -> dict[str, Any]:
        users = await self.db.fetchall("SELECT date(joined_at) day,COUNT(*) n FROM users WHERE julianday(joined_at)>=julianday('now','-30 day') GROUP BY date(joined_at) ORDER BY day")
        sources = await self.db.fetchall("SELECT COALESCE(NULLIF(source,''),'direct') source,COUNT(*) n FROM users GROUP BY COALESCE(NULLIF(source,''),'direct') ORDER BY n DESC LIMIT 12")
        raw_activity = await self.db.fetchall("SELECT ts FROM events WHERE ts>=unixepoch('now','-30 day')")
        try:
            local_zone = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tashkent"))
        except ZoneInfoNotFoundError:
            local_zone = timezone.utc
        hour_counts: dict[tuple[int, int], int] = {}
        for event in raw_activity:
            local_time = datetime.fromtimestamp(float(event["ts"]), tz=timezone.utc).astimezone(local_zone)
            slot = (int(local_time.strftime("%w")), local_time.hour)
            hour_counts[slot] = hour_counts.get(slot, 0) + 1
        hours = [{"weekday": weekday, "hour": hour, "n": count} for (weekday, hour), count in hour_counts.items()]
        joins = await self.db.fetchall("SELECT date(datetime(ts,'unixepoch')) day,type,COUNT(*) n FROM events WHERE type IN ('channel_join','channel_leave') AND ts>=unixepoch('now','-30 day') GROUP BY day,type ORDER BY day")
        posts = await self.db.fetchall("""SELECT p.id,p.title,p.style,p.tag,p.published_at,p.views_manual,
            COALESCE(r.taken_at,'') snapshot_at,COALESCE(r.emoji_counts_json,'{}') reactions
            FROM posts p LEFT JOIN reaction_snapshots r ON r.id=(
              SELECT MAX(r2.id) FROM reaction_snapshots r2 WHERE r2.post_id=p.id
            ) WHERE p.status='published' ORDER BY p.published_at DESC LIMIT 100""")
        return {"users_daily": users, "sources": sources, "active_hours": hours, "joins_leaves": joins, "posts": posts, "tickets": await self.ticket_metrics()}

    async def get_segment_users(self, segment: str, source: str | None = None) -> list[int]:
        if segment == "active7":
            sql, params = "SELECT id FROM users WHERE julianday(last_seen)>=julianday('now','-7 day') AND is_banned=0 AND is_blocked=0", ()
        elif segment == "new7":
            sql, params = "SELECT id FROM users WHERE julianday(joined_at)>=julianday('now','-7 day') AND is_banned=0 AND is_blocked=0", ()
        elif segment == "inactive30":
            sql, params = "SELECT id FROM users WHERE julianday(last_seen)<julianday('now','-30 day') AND is_banned=0 AND is_blocked=0", ()
        elif segment == "source" and source:
            sql, params = "SELECT id FROM users WHERE source=? AND is_banned=0 AND is_blocked=0", (source,)
        else:
            sql, params = "SELECT id FROM users WHERE is_banned=0 AND is_blocked=0", ()
        rows = await self.db.fetchall(sql, params)
        return [int(r["id"]) for r in rows]

    async def create_broadcast(self, text: str, segment: str, total: int, media_type: str | None = None, file_id: str | None = None) -> int:
        return await self.db.execute("INSERT INTO broadcasts(text,segment,total,media_type,file_id,created_at) VALUES(?,?,?,?,?,?)", (text, segment, total, media_type, file_id, utc_now()))

    async def update_broadcast(self, broadcast_id: int, sent: int, failed: int, blocked: int, cancelled: bool) -> None:
        await self.db.execute("UPDATE broadcasts SET sent=?,failed=?,blocked=?,cancelled=? WHERE id=?", (sent, failed, blocked, int(cancelled), broadcast_id))

    async def export_rows(self, table: str, limit: int = 10000) -> list[dict[str, Any]]:
        allowed = {"users", "tickets", "posts", "events"}
        if table not in allowed:
            raise ValueError("Noma'lum eksport turi")
        return await self.db.fetchall(f"SELECT * FROM {table} ORDER BY 1 DESC LIMIT ?", (limit,))

    async def cleanup(self, days: int = 90) -> dict[str, int]:
        events = await self.db.execute("DELETE FROM events WHERE ts<unixepoch('now',?)", (f"-{days} day",))
        drafts = await self.db.execute("DELETE FROM posts WHERE status='draft' AND julianday(created_at)<julianday('now',?)", (f"-{days} day",))
        return {"events_deleted": events, "old_drafts_deleted": drafts}

    async def audit_tail(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))

    async def create_referral(self, code: str, label: str) -> None:
        await self.db.execute("INSERT INTO referral_links(code,label,created_at) VALUES(?,?,?)", (code, label[:120], utc_now()))

    async def referral_stats(self) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT r.code,r.label,r.created_at,COUNT(u.id) users FROM referral_links r LEFT JOIN users u ON u.source=r.code GROUP BY r.code ORDER BY r.created_at DESC")


    async def create_template(self, name: str, body_html: str, style: str, font: str) -> int:
        return await self.db.execute("INSERT INTO templates(name,body_html,style,font) VALUES(?,?,?,?)", (name[:120], body_html, style, font))

    async def list_templates(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT * FROM templates ORDER BY id DESC LIMIT ?", (limit,))

    async def get_template(self, template_id: int) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM templates WHERE id=?", (template_id,))

    async def create_quick_reply(self, title: str, text: str) -> int:
        return await self.db.execute("INSERT INTO quick_replies(title,text) VALUES(?,?)", (title[:80], text[:1000]))

    async def list_quick_replies(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT * FROM quick_replies ORDER BY id DESC LIMIT ?", (limit,))

    async def get_quick_reply(self, quick_id: int) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM quick_replies WHERE id=?", (quick_id,))

    async def delete_quick_reply(self, quick_id: int) -> None:
        await self.db.execute("DELETE FROM quick_replies WHERE id=?", (quick_id,))

    async def recent_similar_posts(self, title: str, days: int = 14) -> list[dict[str, Any]]:
        words = [w for w in title.lower().split() if len(w) > 3][:5]
        if not words:
            return []
        query = " OR ".join("lower(title) LIKE ?" for _ in words)
        params = [f"%{w}%" for w in words] + [f"-{days} day"]
        return await self.db.fetchall(f"SELECT id,title,published_at FROM posts WHERE status='published' AND ({query}) AND published_at>=datetime('now',?) ORDER BY published_at DESC LIMIT 5", params)
