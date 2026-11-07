"""VIP Kino Bot — barcha kod bitta faylda (aiogram 3 + SQLite)."""
from __future__ import annotations

import aiosqlite
import asyncio
import hmac
import html
import logging
import os
import re
import time
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import BaseFilter, Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, CallbackQuery, ChatMemberUpdated, ErrorEvent, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup, TelegramObject
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler

log = logging.getLogger("bot")

# ══════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════
load_dotenv()

TZ = timezone(timedelta(hours=5))  # Toshkent (UTC+5)


def _ids(raw: str) -> tuple[int, ...]:
    return tuple(int(x) for x in raw.replace(" ", "").split(",") if x.lstrip("-").isdigit())


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: tuple[int, ...]
    admin_command: str
    admin_password: str
    db_path: str


def _load() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("❌ .env faylida BOT_TOKEN ko'rsatilmagan.")
    cmd = os.getenv("ADMIN_COMMAND", "").strip().lstrip("/")
    pwd = os.getenv("ADMIN_PASSWORD", "").strip()
    if not cmd or not pwd:
        raise SystemExit("❌ .env faylida ADMIN_COMMAND va ADMIN_PASSWORD ko'rsatilishi shart.")
    db_path = os.getenv("DB_PATH", "data/bot.db")
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    return Config(token, _ids(os.getenv("ADMIN_IDS", "")), cmd, pwd, db_path)


config = _load()


# ══════════════════════════════════════════════════════════════════════
# UTILS
# ══════════════════════════════════════════════════════════════════════
PLANS = {"1m": ("1 OY", 30), "1y": ("1 YIL", 365)}


def esc(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=False)


def money(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def fmt_dt(ts) -> str:
    return datetime.fromtimestamp(int(ts), TZ).strftime("%d.%m.%Y %H:%M")


def fmt_date(ts) -> str:
    return datetime.fromtimestamp(int(ts), TZ).strftime("%d.%m.%Y")


def norm(s: str) -> str:
    s = (s or "").lower().strip()
    for ch in "’ʻ‘`´":
        s = s.replace(ch, "'")
    return s


def fmt_card(number: str) -> str:
    d = re.sub(r"\D", "", number)
    return " ".join(d[i:i + 4] for i in range(0, len(d), 4))


def parse_chat_ref(text: str):
    t = (text or "").strip()
    if t.startswith("@") and len(t) > 4:
        return t
    if re.fullmatch(r"-?\d{5,}", t):
        return int(t)
    m = re.match(r"https?://t\.me/([A-Za-z][A-Za-z0-9_]{3,})/?$", t)
    return "@" + m.group(1) if m else None


def channel_target(link: str):
    m = re.match(r"https?://t\.me/([A-Za-z][A-Za-z0-9_]{3,})/?$", (link or "").strip())
    return "@" + m.group(1) if m else None


# ══════════════════════════════════════════════════════════════════════
# STATES
# ══════════════════════════════════════════════════════════════════════
class UserStates(StatesGroup):
    code = State()
    search = State()


class PayStates(StatesGroup):
    tg_id = State()
    phone = State()
    amount = State()
    check = State()


class AdminAuth(StatesGroup):
    password = State()


class AddMovie(StatesGroup):
    title = State()
    code = State()
    poster = State()
    video = State()
    vip = State()


class DelMovie(StatesGroup):
    code = State()


class EditMovie(StatesGroup):
    code = State()
    value = State()


class AddChannel(StatesGroup):
    ref = State()


class CardStates(StatesGroup):
    number = State()
    owner = State()
    bank = State()


class PriceStates(StatesGroup):
    value = State()


class BlockStates(StatesGroup):
    user_id = State()


class UnblockStates(StatesGroup):
    user_id = State()


class BroadcastStates(StatesGroup):
    content = State()


class SettingStates(StatesGroup):
    value = State()


class GrantStates(StatesGroup):
    user_id = State()
    days = State()


# ══════════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════════
db_SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    first_name TEXT, username TEXT, phone TEXT,
    created_at INTEGER NOT NULL, last_active INTEGER,
    left_bot INTEGER NOT NULL DEFAULT 0,
    views_count INTEGER NOT NULL DEFAULT 0,
    window_start INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS movies(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE COLLATE NOCASE,
    title TEXT NOT NULL, title_lc TEXT NOT NULL,
    poster_id TEXT, video_id TEXT,
    video_type TEXT NOT NULL DEFAULT 'video',
    is_vip INTEGER NOT NULL DEFAULT 0,
    views INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS premium_users(
    user_id INTEGER PRIMARY KEY, plan TEXT,
    activated_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
    reminded3 INTEGER NOT NULL DEFAULT 0,
    reminded1 INTEGER NOT NULL DEFAULT 0,
    expired_notified INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS payments(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL, plan TEXT NOT NULL,
    base_amount INTEGER NOT NULL, amount_due INTEGER NOT NULL,
    amount_paid INTEGER,
    status TEXT NOT NULL DEFAULT 'created',
    tg_id_input TEXT, phone TEXT, check_file_id TEXT, check_type TEXT,
    admin_id INTEGER,
    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_payments_active_amount
    ON payments(amount_due) WHERE status IN ('created','pending');
CREATE INDEX IF NOT EXISTS ix_payments_status ON payments(status);
CREATE TABLE IF NOT EXISTS channels(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL UNIQUE, title TEXT,
    link TEXT NOT NULL, added_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS admins(user_id INTEGER PRIMARY KEY, added_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS statistics(
    date TEXT PRIMARY KEY,
    views INTEGER NOT NULL DEFAULT 0, new_users INTEGER NOT NULL DEFAULT 0,
    payments INTEGER NOT NULL DEFAULT 0, revenue INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS banned_users(
    user_id INTEGER PRIMARY KEY, reason TEXT, banned_by INTEGER, banned_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ads(
    id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, kind TEXT,
    src_chat INTEGER, src_msg INTEGER,
    sent INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS logs(
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
    action TEXT NOT NULL, details TEXT, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS favorites(
    user_id INTEGER NOT NULL, movie_id INTEGER NOT NULL, added_at INTEGER NOT NULL,
    PRIMARY KEY(user_id, movie_id)
);
CREATE TABLE IF NOT EXISTS history(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL, movie_id INTEGER NOT NULL, viewed_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_history_user ON history(user_id, viewed_at);
"""

db_DEFAULTS = {
    "bot_name": "VIP Kino",
    "start_text": (
        "👋 Assalomu alaykum, <b>{name}</b>!\n\n"
        "🎬 <b>{bot}</b> botiga xush kelibsiz.\n"
        "Kino kodini yuboring — kinoni darhol olasiz."
    ),
    "premium_text": "💎 Premium bilan hech qanday cheklovsiz kino tomosha qiling!",
    "ad_text": "",
    "daily_limit": "10",
    "movie_channel": "https://t.me/VIP_kino_ux",
    "card_number": "9860 **** **** ****",
    "card_owner": "Mirzayev Jasur",
    "card_bank": "",
    "price_1m": "8000",
    "price_1y": "29000",
    "reserve_minutes": "60",
}

_db: aiosqlite.Connection
_lock = asyncio.Lock()


# ───────────────────────── yordamchilar ─────────────────────────
def db_now() -> int:
    return int(time.time())


def db_today_key() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


def db_day_start() -> int:
    return int(datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


async def db_init_db() -> None:
    global _db
    _db = await aiosqlite.connect(config.db_path)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA synchronous=NORMAL")
    await _db.executescript(db_SCHEMA)
    for k, v in db_DEFAULTS.items():
        await _db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    await _db.commit()


async def db_close_db() -> None:
    await _db.close()


async def db_fetchone(sql: str, args=()):
    async with _db.execute(sql, args) as cur:
        return await cur.fetchone()


async def db_fetchall(sql: str, args=()):
    async with _db.execute(sql, args) as cur:
        return await cur.fetchall()


async def db_scalar(sql: str, args=()):
    r = await db_fetchone(sql, args)
    return r[0] if r and r[0] is not None else 0


async def db_run(sql: str, args=()):
    cur = await _db.execute(sql, args)
    await _db.commit()
    return cur


# ───────────────────────── sozlamalar / db_log ─────────────────────────
async def db_get_setting(key: str) -> str:
    r = await db_fetchone("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else db_DEFAULTS.get(key, "")


async def db_set_setting(key: str, value: str) -> None:
    await db_run(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


async def db_log(user_id: int | None, action: str, details: str = "") -> None:
    await db_run(
        "INSERT INTO logs(user_id,action,details,created_at) VALUES(?,?,?,?)",
        (user_id, action, details[:1000], db_now()),
    )


async def db_stat_inc(field: str, amount: int = 1) -> None:
    assert field in ("views", "new_users", "payments", "revenue")
    await db_run(
        f"INSERT INTO statistics(date,{field}) VALUES(?,?) "
        f"ON CONFLICT(date) DO UPDATE SET {field}={field}+excluded.{field}",
        (db_today_key(), amount),
    )


# ───────────────────────── foydalanuvchilar ─────────────────────────
async def db_upsert_user(user_id: int, first_name: str, username: str | None) -> bool:
    t = db_now()
    if await db_fetchone("SELECT 1 FROM users WHERE user_id=?", (user_id,)):
        await db_run(
            "UPDATE users SET first_name=?, username=?, last_active=?, left_bot=0 WHERE user_id=?",
            (first_name, username, t, user_id),
        )
        return False
    await db_run(
        "INSERT INTO users(user_id,first_name,username,created_at,last_active) VALUES(?,?,?,?,?)",
        (user_id, first_name, username, t, t),
    )
    await db_stat_inc("new_users")
    return True


async def db_get_user(user_id: int):
    return await db_fetchone("SELECT * FROM users WHERE user_id=?", (user_id,))


async def db_set_left(user_id: int, left: bool) -> None:
    await db_run("UPDATE users SET left_bot=? WHERE user_id=?", (1 if left else 0, user_id))


async def db_set_phone(user_id: int, phone: str) -> None:
    await db_run("UPDATE users SET phone=? WHERE user_id=?", (phone, user_id))


async def db_broadcast_user_ids() -> list[int]:
    rows = await db_fetchall(
        "SELECT user_id FROM users WHERE left_bot=0 "
        "AND user_id NOT IN (SELECT user_id FROM banned_users)"
    )
    return [r[0] for r in rows]


# ───────────────────────── kunlik limit ─────────────────────────
async def db_get_usage(user_id: int) -> tuple[int, int]:
    """(ishlatilgan, yangilanish vaqti)"""
    r = await db_fetchone("SELECT views_count, window_start FROM users WHERE user_id=?", (user_id,))
    if r and r["window_start"] and db_now() - r["window_start"] < 86400:
        return r["views_count"], r["window_start"] + 86400
    return 0, 0


async def db_register_view(user_id: int, movie_id: int) -> None:
    t = db_now()
    r = await db_fetchone("SELECT window_start FROM users WHERE user_id=?", (user_id,))
    if r and r["window_start"] and t - r["window_start"] < 86400:
        await db_run("UPDATE users SET views_count=views_count+1 WHERE user_id=?", (user_id,))
    else:
        await db_run("UPDATE users SET views_count=1, window_start=? WHERE user_id=?", (t, user_id))
    await db_run("UPDATE movies SET views=views+1 WHERE id=?", (movie_id,))
    await db_run("INSERT INTO history(user_id,movie_id,viewed_at) VALUES(?,?,?)", (user_id, movie_id, t))
    await db_stat_inc("views")


# ───────────────────────── premium ─────────────────────────
async def db_get_premium(user_id: int):
    return await db_fetchone(
        "SELECT * FROM premium_users WHERE user_id=? AND expires_at>?", (user_id, db_now())
    )


async def db_grant_premium(user_id: int, plan: str, days: int) -> int:
    t = db_now()
    r = await db_fetchone("SELECT expires_at FROM premium_users WHERE user_id=?", (user_id,))
    start = max(t, r["expires_at"]) if r else t
    exp = start + days * 86400
    await db_run(
        "INSERT INTO premium_users(user_id,plan,activated_at,expires_at) VALUES(?,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET plan=excluded.plan, activated_at=excluded.activated_at, "
        "expires_at=excluded.expires_at, reminded3=0, reminded1=0, expired_notified=0",
        (user_id, plan, t, exp),
    )
    return exp


async def db_revoke_premium(user_id: int) -> bool:
    cur = await db_run("DELETE FROM premium_users WHERE user_id=?", (user_id,))
    return cur.rowcount > 0


async def db_reminder_candidates():
    return await db_fetchall(
        "SELECT * FROM premium_users WHERE expires_at>? AND (reminded3=0 OR reminded1=0) "
        "AND expires_at-?<=?",
        (db_now(), db_now(), 3 * 86400),
    )


async def db_mark_reminded(user_id: int, level: int) -> None:
    if level == 1:
        await db_run("UPDATE premium_users SET reminded1=1, reminded3=1 WHERE user_id=?", (user_id,))
    else:
        await db_run("UPDATE premium_users SET reminded3=1 WHERE user_id=?", (user_id,))


async def db_expired_unnotified():
    return await db_fetchall(
        "SELECT * FROM premium_users WHERE expires_at<=? AND expired_notified=0", (db_now(),)
    )


async def db_mark_expired_notified(user_id: int) -> None:
    await db_run("UPDATE premium_users SET expired_notified=1 WHERE user_id=?", (user_id,))


# ───────────────────────── kinolar ─────────────────────────
async def db_add_movie(code, title, poster_id, video_id, video_type, is_vip) -> int:
    cur = await db_run(
        "INSERT INTO movies(code,title,title_lc,poster_id,video_id,video_type,is_vip,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (code, title, norm(title), poster_id, video_id, video_type, int(is_vip), db_now()),
    )
    return cur.lastrowid


async def db_get_movie_by_code(code: str):
    return await db_fetchone("SELECT * FROM movies WHERE code=?", (code.strip(),))


async def db_get_movie(movie_id: int):
    return await db_fetchone("SELECT * FROM movies WHERE id=?", (movie_id,))


async def db_delete_movie(movie_id: int) -> None:
    await _db.execute("DELETE FROM favorites WHERE movie_id=?", (movie_id,))
    await _db.execute("DELETE FROM history WHERE movie_id=?", (movie_id,))
    await _db.execute("DELETE FROM movies WHERE id=?", (movie_id,))
    await _db.commit()


async def db_update_movie(movie_id: int, **fields) -> None:
    allowed = {"title", "code", "poster_id", "video_id", "video_type", "is_vip"}
    if not fields or not set(fields) <= allowed:
        raise ValueError("noto'g'ri maydon")
    if "title" in fields:
        fields["title_lc"] = norm(fields["title"])
    cols = ", ".join(f"{k}=?" for k in fields)
    await db_run(f"UPDATE movies SET {cols} WHERE id=?", (*fields.values(), movie_id))


async def db_search_movies(query: str, limit: int = 10):
    q = norm(query).replace("%", "").replace("_", "")
    return await db_fetchall(
        "SELECT * FROM movies WHERE title_lc LIKE ? ORDER BY views DESC LIMIT ?",
        (f"%{q}%", limit),
    )


async def db_next_code() -> int:
    r = await db_scalar(
        "SELECT MAX(CAST(code AS INTEGER)) FROM movies WHERE code NOT GLOB '*[^0-9]*'"
    )
    return int(r) + 1 if r else 1001


async def db_count_movies() -> int:
    return await db_scalar("SELECT COUNT(*) FROM movies")


# ───────────────────────── sevimli / tarix ─────────────────────────
async def db_toggle_favorite(user_id: int, movie_id: int) -> bool:
    if await db_is_favorite(user_id, movie_id):
        await db_run("DELETE FROM favorites WHERE user_id=? AND movie_id=?", (user_id, movie_id))
        return False
    await db_run(
        "INSERT OR IGNORE INTO favorites(user_id,movie_id,added_at) VALUES(?,?,?)",
        (user_id, movie_id, db_now()),
    )
    return True


async def db_is_favorite(user_id: int, movie_id: int) -> bool:
    return bool(await db_fetchone(
        "SELECT 1 FROM favorites WHERE user_id=? AND movie_id=?", (user_id, movie_id)))


async def db_list_favorites(user_id: int, limit: int = 30):
    return await db_fetchall(
        "SELECT m.* FROM favorites f JOIN movies m ON m.id=f.movie_id "
        "WHERE f.user_id=? ORDER BY f.added_at DESC LIMIT ?", (user_id, limit))


async def db_list_history(user_id: int, limit: int = 20):
    return await db_fetchall(
        "SELECT m.*, MAX(h.viewed_at) AS t FROM history h JOIN movies m ON m.id=h.movie_id "
        "WHERE h.user_id=? GROUP BY m.id ORDER BY t DESC LIMIT ?", (user_id, limit))


# ───────────────────────── majburiy kanallar ─────────────────────────
async def db_add_channel(chat_id: int, title: str, link: str) -> None:
    await db_run(
        "INSERT INTO channels(chat_id,title,link,added_at) VALUES(?,?,?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, link=excluded.link",
        (chat_id, title, link, db_now()),
    )


async def db_list_channels():
    return await db_fetchall("SELECT * FROM channels ORDER BY id")


async def db_get_channel(cid: int):
    return await db_fetchone("SELECT * FROM channels WHERE id=?", (cid,))


async def db_delete_channel(cid: int) -> None:
    await db_run("DELETE FROM channels WHERE id=?", (cid,))


# ───────────────────────── adminlar / bloklash ─────────────────────────
async def db_add_admin(user_id: int) -> None:
    await db_run("INSERT OR IGNORE INTO admins(user_id,added_at) VALUES(?,?)", (user_id, db_now()))


async def db_remove_admin(user_id: int) -> None:
    await db_run("DELETE FROM admins WHERE user_id=?", (user_id,))


async def db_is_admin(user_id: int) -> bool:
    if user_id in config.admin_ids:
        return True
    return bool(await db_fetchone("SELECT 1 FROM admins WHERE user_id=?", (user_id,)))


async def db_admin_ids() -> set[int]:
    rows = await db_fetchall("SELECT user_id FROM admins")
    return {r[0] for r in rows} | set(config.admin_ids)


async def db_ban_user(user_id: int, by: int, reason: str = "") -> None:
    await db_run(
        "INSERT OR REPLACE INTO banned_users(user_id,reason,banned_by,banned_at) VALUES(?,?,?,?)",
        (user_id, reason, by, db_now()),
    )


async def db_unban_user(user_id: int) -> bool:
    cur = await db_run("DELETE FROM banned_users WHERE user_id=?", (user_id,))
    return cur.rowcount > 0


async def db_is_banned(user_id: int) -> bool:
    return bool(await db_fetchone("SELECT 1 FROM banned_users WHERE user_id=?", (user_id,)))


# ───────────────────────── to'lovlar ─────────────────────────
async def db_expire_stale_payments() -> None:
    minutes = int(await db_get_setting("reserve_minutes") or 60)
    await db_run(
        "UPDATE payments SET status='expired', updated_at=? WHERE status='created' AND updated_at<?",
        (db_now(), db_now() - minutes * 60),
    )


async def db_reserve_payment(user_id: int, plan: str):
    """Foydalanuvchiga noyob summa ajratadi (8001, 8002, ...)."""
    async with _lock:
        await db_expire_stale_payments()
        await _db.execute(
            "UPDATE payments SET status='cancelled', updated_at=? WHERE user_id=? AND status='created'",
            (db_now(), user_id),
        )
        await _db.commit()
        base = int(await db_get_setting(f"price_{plan}"))
        rows = await db_fetchall("SELECT amount_due FROM payments WHERE status IN ('created','pending')")
        used = {r[0] for r in rows}
        for n in range(1, 1000):
            if base + n not in used:
                amount = base + n
                break
        else:
            return None
        t = db_now()
        cur = await db_run(
            "INSERT INTO payments(user_id,plan,base_amount,amount_due,status,created_at,updated_at) "
            "VALUES(?,?,?,?,'created',?,?)",
            (user_id, plan, base, amount, t, t),
        )
        return await db_get_payment(cur.lastrowid)


async def db_get_payment(pid: int):
    return await db_fetchone("SELECT * FROM payments WHERE id=?", (pid,))


async def db_get_pending_for_user(user_id: int):
    return await db_fetchone(
        "SELECT * FROM payments WHERE user_id=? AND status='pending'", (user_id,))


async def db_touch_payment(pid: int) -> None:
    await db_run("UPDATE payments SET updated_at=? WHERE id=? AND status='created'", (db_now(), pid))


async def db_cancel_payment(pid: int, user_id: int) -> None:
    await db_run(
        "UPDATE payments SET status='cancelled', updated_at=? WHERE id=? AND user_id=? AND status='created'",
        (db_now(), pid, user_id),
    )


async def db_submit_payment(pid, tg_id_input, phone, amount_paid, check_file_id, check_type) -> bool:
    cur = await db_run(
        "UPDATE payments SET status='pending', tg_id_input=?, phone=?, amount_paid=?, "
        "check_file_id=?, check_type=?, updated_at=? WHERE id=? AND status='created'",
        (tg_id_input, phone, amount_paid, check_file_id, check_type, db_now(), pid),
    )
    return cur.rowcount > 0


async def db_approve_payment(pid: int, admin_id: int) -> bool:
    cur = await db_run(
        "UPDATE payments SET status='approved', admin_id=?, updated_at=? WHERE id=? AND status='pending'",
        (admin_id, db_now(), pid),
    )
    return cur.rowcount > 0


async def db_reject_payment(pid: int, admin_id: int) -> bool:
    cur = await db_run(
        "UPDATE payments SET status='rejected', admin_id=?, updated_at=? WHERE id=? AND status='pending'",
        (admin_id, db_now(), pid),
    )
    return cur.rowcount > 0


async def db_list_pending(limit: int = 20):
    return await db_fetchall(
        "SELECT * FROM payments WHERE status='pending' ORDER BY id LIMIT ?", (limit,))


# ───────────────────────── reklama / statistika ─────────────────────────
async def db_add_ad(admin_id: int, kind: str, src_chat: int, src_msg: int) -> int:
    cur = await db_run(
        "INSERT INTO ads(admin_id,kind,src_chat,src_msg,created_at) VALUES(?,?,?,?,?)",
        (admin_id, kind, src_chat, src_msg, db_now()),
    )
    return cur.lastrowid


async def db_finish_ad(ad_id: int, sent: int, failed: int) -> None:
    await db_run("UPDATE ads SET sent=?, failed=? WHERE id=?", (sent, failed, ad_id))


async def db_stats_summary() -> dict:
    t = db_now()
    total = await db_scalar("SELECT COUNT(*) FROM users")
    premium = await db_scalar("SELECT COUNT(*) FROM premium_users WHERE expires_at>?", (t,))
    today = await db_fetchone(
        "SELECT views, payments, revenue FROM statistics WHERE date=?", (db_today_key(),))
    return {
        "total": total,
        "new_today": await db_scalar("SELECT COUNT(*) FROM users WHERE created_at>=?", (db_day_start(),)),
        "premium": premium,
        "regular": max(total - premium, 0),
        "banned": await db_scalar("SELECT COUNT(*) FROM banned_users"),
        "left": await db_scalar("SELECT COUNT(*) FROM users WHERE left_bot=1"),
        "pay_today": today["payments"] if today else 0,
        "rev_today": today["revenue"] if today else 0,
        "revenue": await db_scalar("SELECT COALESCE(SUM(revenue),0) FROM statistics"),
        "views_today": today["views"] if today else 0,
        "movies": await db_count_movies(),
    }


def db_plan_days(plan: str) -> int:
    return PLANS[plan][1]


# ══════════════════════════════════════════════════════════════════════
# KEYBOARDS
# ══════════════════════════════════════════════════════════════════════
# ── foydalanuvchi tugmalari
kb_BTN_MOVIE = "🎬 Kino ko'rish"
kb_BTN_PREMIUM = "⭐ Premium"
kb_BTN_CHANNEL = "📢 Kino kanal"
kb_BTN_ADS = "📣 Reklama"
kb_BTN_PROFILE = "👤 Profil"
kb_BTN_FAVS = "❤️ Sevimlilar"
kb_BTN_SEARCH = "🔎 Qidirish"
kb_BTN_HISTORY = "📜 Tarix"
kb_BTN_CANCEL = "🔙 Bekor qilish"
kb_BTN_MY_ID = "🆔 Mening ID raqamim"
kb_BTN_SEND_PHONE = "📱 Raqamimni yuborish"

# ── admin tugmalari
kb_A_ADD_MOVIE = "➕ Kino qo'shish"
kb_A_DEL_MOVIE = "🗑 Kino o'chirish"
kb_A_EDIT_MOVIE = "✏ Kino tahrirlash"
kb_A_ADD_CHANNEL = "📢 Majburiy kanal qo'shish"
kb_A_DEL_CHANNEL = "🗑 Majburiy kanal o'chirish"
kb_A_CARD = "💳 Kartani almashtirish"
kb_A_PRICE = "⭐ Premium narxini o'zgartirish"
kb_A_PAYMENTS = "💰 Premium to'lovlari"
kb_A_BROADCAST = "📨 Reklama yuborish"
kb_A_BAN = "🚫 Foydalanuvchini bloklash"
kb_A_UNBAN = "✅ Blokdan chiqarish"
kb_A_STATS = "📊 Statistika"
kb_A_GRANT = "🎁 Premium berish"
kb_A_SETTINGS = "⚙ Sozlamalar"
kb_A_EXIT = "🚪 Chiqish"


def _reply(rows: list[list[str]], **kw) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t) for t in row] for row in rows],
        resize_keyboard=True, **kw)


def kb_main_menu() -> ReplyKeyboardMarkup:
    return _reply([
        [kb_BTN_MOVIE, kb_BTN_SEARCH],
        [kb_BTN_PREMIUM, kb_BTN_PROFILE],
        [kb_BTN_FAVS, kb_BTN_HISTORY],
        [kb_BTN_CHANNEL, kb_BTN_ADS],
    ])


def kb_cancel_kb() -> ReplyKeyboardMarkup:
    return _reply([[kb_BTN_CANCEL]])


def kb_tgid_kb() -> ReplyKeyboardMarkup:
    return _reply([[kb_BTN_MY_ID], [kb_BTN_CANCEL]])


def kb_phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=kb_BTN_SEND_PHONE, request_contact=True)],
                  [KeyboardButton(text=kb_BTN_CANCEL)]],
        resize_keyboard=True)


def kb_admin_menu() -> ReplyKeyboardMarkup:
    return _reply([
        [kb_A_ADD_MOVIE, kb_A_DEL_MOVIE],
        [kb_A_EDIT_MOVIE, kb_A_ADD_CHANNEL],
        [kb_A_DEL_CHANNEL, kb_A_CARD],
        [kb_A_PRICE, kb_A_PAYMENTS],
        [kb_A_BROADCAST, kb_A_BAN],
        [kb_A_UNBAN, kb_A_STATS],
        [kb_A_GRANT, kb_A_SETTINGS],
        [kb_A_EXIT],
    ])


# ── inline
def kb_subscribe_kb(channels, missing_ids: set | None = None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for ch in channels:
        joined = missing_ids is not None and ch["id"] not in missing_ids
        b.row(InlineKeyboardButton(
            text=f"{'✅' if joined else '📢'} {ch['title'] or 'Kanal'}", url=ch["link"]))
    b.row(InlineKeyboardButton(text="⭐ Premium sotib olish", callback_data="premium"))
    b.row(InlineKeyboardButton(text="🔄 Tekshirish", callback_data="check_sub"))
    return b.as_markup()


def kb_premium_kb(prices: dict[str, int]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key, (title, _) in PLANS.items():
        b.row(InlineKeyboardButton(
            text=f"{title} — {money(prices[key])} so'm", callback_data=f"plan:{key}"))
    return b.as_markup()


def kb_premium_btn() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⭐ Premium sotib olish", callback_data="premium")]])


def kb_pay_kb(pid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Pul tashladim", callback_data=f"pay:{pid}")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"paycancel:{pid}")],
    ])


def kb_movie_kb(movie_id: int, is_fav: bool, url: str | None = None) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text="💔 Sevimlidan olib tashlash" if is_fav else "❤️ Sevimlilarga qo'shish",
        callback_data=f"fav:{movie_id}")]]
    if url:
        rows.insert(0, [InlineKeyboardButton(text="▶️ Ko'rish", url=url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_movies_list_kb(movies) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for m in movies:
        vip = "💎 " if m["is_vip"] else ""
        b.row(InlineKeyboardButton(text=f"{vip}{m['title']} • {m['code']}"[:60],
                                   callback_data=f"mv:{m['code']}"))
    return b.as_markup()


def kb_pay_admin_kb(pid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"pa:ok:{pid}"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"pa:no:{pid}"),
    ]])


def kb_vip_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🆓 Oddiy", callback_data="vip:0"),
        InlineKeyboardButton(text="💎 VIP", callback_data="vip:1"),
    ]])


def kb_chpost_kb(movie_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Kanalga yuborish", callback_data=f"chpost:ok:{movie_id}"),
        InlineKeyboardButton(text="❌ Yubormaslik", callback_data=f"chpost:no:{movie_id}"),
    ]])


def kb_channel_post_kb(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎬 Botda ko'rish", url=url)]])


def kb_confirm_delete_kb(movie_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗑 Ha, o'chirish", callback_data=f"del:ok:{movie_id}"),
        InlineKeyboardButton(text="↩️ Yo'q", callback_data="del:no:0"),
    ]])


def kb_edit_kb(movie_id: int, is_vip: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📝 Nomi", callback_data=f"ed:title:{movie_id}"),
          InlineKeyboardButton(text="🔑 Kodi", callback_data=f"ed:code:{movie_id}"))
    b.row(InlineKeyboardButton(text="🖼 Rasmi", callback_data=f"ed:poster:{movie_id}"),
          InlineKeyboardButton(text="🎞 Videosi", callback_data=f"ed:video:{movie_id}"))
    b.row(InlineKeyboardButton(
        text="🆓 Oddiy qilish" if is_vip else "💎 VIP qilish", callback_data=f"ed:vip:{movie_id}"))
    return b.as_markup()


def kb_channels_del_kb(channels) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for ch in channels:
        b.row(InlineKeyboardButton(text=f"🗑 {ch['title'] or ch['chat_id']}"[:60],
                                   callback_data=f"chdel:{ch['id']}"))
    return b.as_markup()


def kb_price_kb(prices: dict[str, int]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key, (title, _) in PLANS.items():
        b.row(InlineKeyboardButton(
            text=f"{title}: {money(prices[key])} so'm", callback_data=f"pr:{key}"))
    return b.as_markup()


def kb_grant_kb(uid: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="1 OY (30 kun)", callback_data=f"gr:1m:{uid}"),
          InlineKeyboardButton(text="1 YIL (365 kun)", callback_data=f"gr:1y:{uid}"))
    b.row(InlineKeyboardButton(text="✏ Kun kiritish", callback_data=f"gr:days:{uid}"))
    b.row(InlineKeyboardButton(text="🗑 Premiumni olib tashlash", callback_data=f"gr:rev:{uid}"))
    return b.as_markup()


def kb_broadcast_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🚀 Yuborish", callback_data="bc:ok"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data="bc:no"),
    ]])


def kb_settings_kb(editable: dict[str, str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key, label in editable.items():
        b.row(InlineKeyboardButton(text=label, callback_data=f"st:{key}"))
    b.row(InlineKeyboardButton(text="💳 Karta ma'lumotlari", callback_data="st:card"),
          InlineKeyboardButton(text="💰 Premium narxlari", callback_data="st:prices"))
    b.row(InlineKeyboardButton(text="🔗 Majburiy kanallar", callback_data="st:channels"))
    return b.as_markup()


# ══════════════════════════════════════════════════════════════════════
# SERVICES
# ══════════════════════════════════════════════════════════════════════
svc_log = logging.getLogger(__name__)
_ok_cache: dict[int, float] = {}
svc_CACHE_TTL = 45


async def svc_not_joined(bot: Bot, user_id: int, force: bool = False) -> list:
    """Foydalanuvchi a'zo bo'lmagan majburiy kanallar ro'yxati."""
    channels = await db_list_channels()
    if not channels:
        return []
    if not force and time.time() - _ok_cache.get(user_id, 0) < svc_CACHE_TTL:
        return []

    async def check(ch):
        try:
            m = await bot.get_chat_member(ch["chat_id"], user_id)
            if m.status in ("left", "kicked"):
                return ch
            if m.status == "restricted" and not getattr(m, "is_member", True):
                return ch
        except TelegramAPIError as e:  # bot kanalda admin emas / kanal yo'q — foydalanuvchini bloklamaymiz
            svc_log.warning("Kanal %s tekshirib bo'lmadi: %s", ch["chat_id"], e)
        return None

    res = await asyncio.gather(*(check(c) for c in channels))
    missing = [r for r in res if r]
    if not missing:
        _ok_cache[user_id] = time.time()
        if len(_ok_cache) > 20000:
            _ok_cache.clear()
    else:
        _ok_cache.pop(user_id, None)
    return missing


async def svc_notify_admins(bot: Bot, text: str, **kw) -> None:
    for aid in await db_admin_ids():
        try:
            await bot.send_message(aid, text, **kw)
        except TelegramAPIError:
            pass


async def svc_payment_text(p) -> str:
    u = await db_get_user(p["user_id"])
    name = esc(u["first_name"]) if u else "—"
    uname = f"@{esc(u['username'])}" if u and u["username"] else "—"
    paid = p["amount_paid"]
    warn = "" if paid == p["amount_due"] else "  ⚠️ <b>MOS EMAS!</b>"
    card = await db_get_setting("card_number")
    return (
        "━━━━━━━━━━━━━━\n"
        "🆕 <b>PREMIUM SO'ROVI</b>\n\n"
        f"👤 Ism: {name}\n"
        f"🆔 Telegram ID: <code>{p['user_id']}</code>\n"
        f"🆔 Kiritilgan ID: <code>{esc(p['tg_id_input'])}</code>\n"
        f"👤 Username: {uname}\n"
        f"📱 Telefon: <code>{esc(p['phone'])}</code>\n"
        f"📦 Tarif: {PLANS[p['plan']][0]}\n"
        f"💰 Kerakli summa: <b>{money(p['amount_due'])}</b> so'm\n"
        f"💵 To'langan summa: <b>{money(paid) if paid is not None else '—'}</b> so'm{warn}\n"
        f"💳 Karta: <code>{esc(card)}</code>\n"
        f"🕒 Sana: {fmt_dt(p['updated_at'])}\n"
        f"📷 Chek: {'✅ ilova qilingan' if p['check_file_id'] else '❌ yo`q'}\n"
        "━━━━━━━━━━━━━━"
    )


async def svc_send_payment_to(bot: Bot, chat_id: int, p) -> None:
    text = await svc_payment_text(p)
    markup = kb_pay_admin_kb(p["id"])
    try:
        if p["check_type"] == "document":
            await bot.send_document(chat_id, p["check_file_id"], caption=text, reply_markup=markup)
        else:
            await bot.send_photo(chat_id, p["check_file_id"], caption=text, reply_markup=markup)
    except TelegramAPIError as e:
        svc_log.warning("To'lov adminga yuborilmadi (%s): %s", chat_id, e)


async def svc_notify_admins_payment(bot: Bot, pid: int) -> None:
    p = await db_get_payment(pid)
    for aid in await db_admin_ids():
        await svc_send_payment_to(bot, aid, p)


def svc_channel_caption(movie, bot_username: str) -> str:
    vip = "💎 <b>VIP</b>\n" if movie["is_vip"] else ""
    return (
        f"🎬 <b>{esc(movie['title'])}</b>\n{vip}\n"
        f"🔑 Kino kodi: <code>{esc(movie['code'])}</code>\n\n"
        f"🤖 @{bot_username} botiga kodni yuboring"
    )


def svc_card_block(card: str, owner: str, bank: str) -> str:
    s = f"💳 Karta: <code>{esc(fmt_card(card) if card.replace(' ', '').isdigit() else card)}</code>\n"
    s += f"👤 Karta egasi: <b>{esc(owner)}</b>\n"
    if bank:
        s += f"🏦 Bank: {esc(bank)}\n"
    return s


# ══════════════════════════════════════════════════════════════════════
# MIDDLEWARES
# ══════════════════════════════════════════════════════════════════════
class AccessMiddleware(BaseMiddleware):
    """Ro'yxatga olish, antispam va bloklangan foydalanuvchilarni to'xtatish."""

    def __init__(self) -> None:
        self._last: dict[int, float] = {}

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        chat = data.get("event_chat")
        if user is None or user.is_bot:
            return await handler(event, data)
        if chat is not None and chat.type != "private":
            return None
        await db_upsert_user(user.id, user.first_name or "", user.username)
        if await db_is_admin(user.id):
            return await handler(event, data)

        if isinstance(event, Message):
            t = time.monotonic()
            if t - self._last.get(user.id, 0) < 0.3:
                return None
            self._last[user.id] = t
            if len(self._last) > 20000:
                self._last.clear()

        if await db_is_banned(user.id):
            if isinstance(event, CallbackQuery):
                await event.answer("🚫 Siz bloklangansiz.", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("🚫 Siz bloklangansiz.")
            return None
        return await handler(event, data)


class SubscriptionGate(BaseMiddleware):
    """Majburiy obuna: Premium va adminlar bundan ozod."""

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)
        if await db_is_admin(user.id) or await db_get_premium(user.id):
            return await handler(event, data)

        state: FSMContext = data["state"]
        bot: Bot = data["bot"]

        # Obuna bo'lmagan odam ham Premium sotib ola olishi kerak
        if isinstance(event, CallbackQuery):
            d = event.data or ""
            if d in ("check_sub", "premium") or d.startswith(("plan:", "pay:", "paycancel:")):
                return await handler(event, data)
        else:
            cur = await state.get_state()
            if cur and cur.startswith("PayStates"):
                return await handler(event, data)

        missing = await svc_not_joined(bot, user.id)
        if not missing:
            return await handler(event, data)

        if isinstance(event, Message) and (event.text or "").startswith("/start m_"):
            await state.update_data(pending_code=event.text.split("m_", 1)[1].strip())

        if isinstance(event, CallbackQuery):
            await event.answer()
        channels = await db_list_channels()
        await bot.send_message(
            user.id,
            "📢 <b>Botdan foydalanish uchun quyidagi kanallarga a'zo bo'ling</b>\n\n"
            "So'ng «🔄 Tekshirish» tugmasini bosing.\n"
            "⭐ Premium foydalanuvchilar majburiy obunasiz ishlaydi.",
            reply_markup=kb_subscribe_kb(channels, {c["id"] for c in missing}),
        )
        return None


# ══════════════════════════════════════════════════════════════════════
# TASKS
# ══════════════════════════════════════════════════════════════════════
"""Fon vazifalari: Premium eslatmalari, muddati tugashi, eskirgan to'lovlarni tozalash."""


INTERVAL = 600  # 10 daqiqa


async def _send(bot: Bot, uid: int, text: str) -> None:
    try:
        await bot.send_message(uid, text, reply_markup=kb_premium_btn())
    except TelegramAPIError:
        pass


async def tick(bot: Bot) -> None:
    await db_expire_stale_payments()
    t = db_now()
    for r in await db_reminder_candidates():
        left = r["expires_at"] - t
        if left <= 86400 and not r["reminded1"]:
            await _send(bot, r["user_id"],
                        f"⏰ <b>Premium muddati tugashiga 1 kundan kam qoldi!</b>\n📅 {fmt_date(r['expires_at'])}\n\nUzaytirish uchun pastdagi tugmani bosing.")
            await db_mark_reminded(r["user_id"], 1)
        elif 86400 < left <= 3 * 86400 and not r["reminded3"]:
            await _send(bot, r["user_id"],
                        f"⏰ <b>Premium muddati tugashiga 3 kun qoldi.</b>\n📅 {fmt_date(r['expires_at'])}\n\nUzaytirish uchun pastdagi tugmani bosing.")
            await db_mark_reminded(r["user_id"], 3)
        await asyncio.sleep(0.05)
    for r in await db_expired_unnotified():
        await _send(bot, r["user_id"], "⌛ <b>Premium muddatingiz tugadi.</b>\nQayta faollashtirish uchun tarif tanlang.")
        await db_mark_expired_notified(r["user_id"])
        await asyncio.sleep(0.05)


async def background_loop(bot: Bot) -> None:
    while True:
        try:
            await tick(bot)
        except Exception:
            log.exception("Fon vazifasida xato")
        await asyncio.sleep(INTERVAL)


# ══════════════════════════════════════════════════════════════════════
# HANDLERS/COMMON
# ══════════════════════════════════════════════════════════════════════
"""Admin kirish (login), /admin va umumiy «Bekor qilish»."""


common_router = Router(name="common")

_fails: dict[int, list[float]] = {}
MAX_TRIES, LOCK_SEC = 5, 900


@common_router.message(F.text == kb_BTN_CANCEL)
async def cancel_any(m: Message, state: FSMContext):
    await state.clear()
    if await db_is_admin(m.from_user.id) and (m.text == kb_BTN_CANCEL):
        # admin oqimidan bekor qilsa — panelga, foydalanuvchi oqimida bo'lsa — menyuga qaytadi
        await m.answer("↩️ Bekor qilindi.", reply_markup=kb_admin_menu())
    else:
        await m.answer("↩️ Bekor qilindi.", reply_markup=kb_main_menu())


@common_router.message(F.text == f"/{config.admin_command}")
async def admin_login(m: Message, state: FSMContext):
    uid = m.from_user.id
    if await db_is_admin(uid):
        await state.clear()
        await m.answer("🛠 <b>Admin panel</b>", reply_markup=kb_admin_menu())
        return
    tries = [t for t in _fails.get(uid, []) if time.time() - t < LOCK_SEC]
    if len(tries) >= MAX_TRIES:
        await m.answer("⛔ Juda ko'p urinish. Keyinroq qayta urinib ko'ring.")
        return
    await state.set_state(AdminAuth.password)
    await m.answer("🔐 Parolni kiriting", reply_markup=kb_cancel_kb())


@common_router.message(AdminAuth.password, F.text)
async def admin_password(m: Message, state: FSMContext):
    uid = m.from_user.id
    txt = m.text.strip()
    if txt.startswith("/start"):
        await state.clear()
        await m.answer("↩️ Bekor qilindi.", reply_markup=kb_main_menu())
        return
    try:
        await m.delete()  # parol chatda qolmasin
    except Exception:
        pass
    if hmac.compare_digest(txt.encode(), config.admin_password.encode()):
        _fails.pop(uid, None)
        await db_add_admin(uid)
        await db_log(uid, "admin_login", "muvaffaqiyatli")
        await state.clear()
        await m.answer("✅ Xush kelibsiz, admin!\n\n🛠 <b>Admin panel</b>", reply_markup=kb_admin_menu())
        return
    tries = [t for t in _fails.get(uid, []) if time.time() - t < LOCK_SEC] + [time.time()]
    _fails[uid] = tries
    await db_log(uid, "admin_login_fail", f"urinish={len(tries)}")
    if len(tries) >= MAX_TRIES:
        await state.clear()
        await m.answer("⛔ Juda ko'p xato urinish. 15 daqiqadan keyin qayta urinib ko'ring.",
                       reply_markup=kb_main_menu())
    else:
        await m.answer(f"❌ Parol noto'g'ri. Qolgan urinishlar: {MAX_TRIES - len(tries)}")


@common_router.message(Command("admin"))
async def admin_cmd(m: Message, state: FSMContext):
    if await db_is_admin(m.from_user.id):
        await state.clear()
        await m.answer("🛠 <b>Admin panel</b>", reply_markup=kb_admin_menu())


# ══════════════════════════════════════════════════════════════════════
# HANDLERS/ADMIN
# ══════════════════════════════════════════════════════════════════════
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_tasks: set[asyncio.Task] = set()
ADMIN_BTNS = {
    kb_A_ADD_MOVIE, kb_A_DEL_MOVIE, kb_A_EDIT_MOVIE, kb_A_ADD_CHANNEL, kb_A_DEL_CHANNEL, kb_A_CARD,
    kb_A_PRICE, kb_A_PAYMENTS, kb_A_GRANT, kb_A_BROADCAST, kb_A_BAN, kb_A_UNBAN, kb_A_STATS, kb_A_SETTINGS,
    kb_A_EXIT,
}
NOT_MENU = ~F.text.in_(ADMIN_BTNS)


class IsAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user) and await db_is_admin(user.id)


admin_router = Router(name="admin")
admin_router.message.filter(IsAdmin())
admin_router.callback_query.filter(IsAdmin())


async def _done(m: Message | CallbackQuery, state: FSMContext, text: str, bot: Bot | None = None):
    """Oqimni tugatib, admin menyusini qaytaradi."""
    await state.clear()
    chat_id = m.from_user.id
    target = bot or m.bot
    await target.send_message(chat_id, text, reply_markup=kb_admin_menu())


def _parse_video(m: Message):
    if m.video:
        return m.video.file_id, "video"
    if m.document:
        return m.document.file_id, "document"
    if m.text and m.text.strip().startswith(("http://", "https://")):
        return m.text.strip(), "link"
    return None


# ═════════════════════════ CHIQISH ═════════════════════════
@admin_router.message(F.text == kb_A_EXIT)
async def a_exit(m: Message, state: FSMContext):
    await state.clear()
    if m.from_user.id in config.admin_ids:
        await m.answer("🏠 Foydalanuvchi menyusi. Panelga qaytish: /admin", reply_markup=kb_main_menu())
        return
    await db_remove_admin(m.from_user.id)
    await db_log(m.from_user.id, "admin_logout")
    await m.answer("🚪 Admin paneldan chiqdingiz.", reply_markup=kb_main_menu())


# ═════════════════════════ KINO QO'SHISH ═════════════════════════
@admin_router.message(F.text == kb_A_ADD_MOVIE)
async def add_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddMovie.title)
    await m.answer("🎬 <b>Yangi kino</b>\n\n1️⃣ Kino nomini kiriting:", reply_markup=kb_cancel_kb())


@admin_router.message(AddMovie.title, F.text, NOT_MENU)
async def add_title(m: Message, state: FSMContext):
    title = m.text.strip()
    if not 1 <= len(title) <= 200:
        await m.answer("❗ Nom 1–200 belgidan iborat bo'lsin.")
        return
    await state.update_data(title=title)
    await state.set_state(AddMovie.code)
    await m.answer(f"2️⃣ Kino kodini kiriting.\nBo'sh kod: <code>{await db_next_code()}</code>")


@admin_router.message(AddMovie.code, F.text, NOT_MENU)
async def add_code(m: Message, state: FSMContext):
    code = m.text.strip()
    if not CODE_RE.fullmatch(code):
        await m.answer("❗ Kod faqat harf, raqam, «-» va «_» dan iborat bo'lsin (maks 32).")
        return
    if await db_get_movie_by_code(code):
        await m.answer("❌ Bu kod band. Boshqa kod kiriting.")
        return
    await state.update_data(code=code)
    await state.set_state(AddMovie.poster)
    await m.answer("3️⃣ Kino <b>rasmini</b> yuboring:")


@admin_router.message(AddMovie.poster, F.photo)
async def add_poster(m: Message, state: FSMContext):
    await state.update_data(poster=m.photo[-1].file_id)
    await state.set_state(AddMovie.video)
    await m.answer("4️⃣ <b>Videoni</b> yuboring yoki video <b>havolasini</b> yozing:")


@admin_router.message(AddMovie.poster, NOT_MENU)
async def add_poster_bad(m: Message):
    await m.answer("❗ Iltimos, rasm yuboring.")


@admin_router.message(AddMovie.video, NOT_MENU)
async def add_video(m: Message, state: FSMContext):
    parsed = _parse_video(m)
    if not parsed:
        await m.answer("❗ Video, video-fayl yoki http(s) havola yuboring.")
        return
    await state.update_data(video=parsed[0], vtype=parsed[1])
    await state.set_state(AddMovie.vip)
    await m.answer("5️⃣ Kino turi:", reply_markup=kb_vip_kb())


@admin_router.callback_query(AddMovie.vip, F.data.startswith("vip:"))
async def add_vip(c: CallbackQuery, state: FSMContext, bot: Bot):
    d = await state.get_data()
    vip = c.data.endswith("1")
    if await db_get_movie_by_code(d["code"]):
        await c.answer("Kod band bo'lib qoldi", show_alert=True)
        return
    mid = await db_add_movie(d["code"], d["title"], d["poster"], d["video"], d["vtype"], vip)
    await db_log(c.from_user.id, "movie_add", f"id={mid} code={d['code']} title={d['title']} vip={vip}")
    await c.answer("Saqlandi")
    await c.message.edit_text(f"✅ <b>Kino saqlandi!</b>\n🎬 {esc(d['title'])}\n🔑 Kod: <code>{esc(d['code'])}</code>")
    await _done(c, state, "📢 Quyida kanalga yuboriladigan post ko'rinishi 👇", bot)
    movie = await db_get_movie(mid)
    me = await bot.me()
    await bot.send_photo(c.from_user.id, movie["poster_id"],
                         caption=svc_channel_caption(movie, me.username),
                         reply_markup=kb_chpost_kb(mid))


@admin_router.callback_query(F.data.startswith("chpost:"))
async def channel_post(c: CallbackQuery, bot: Bot):
    _, act, mid = c.data.split(":")
    base = c.message.html_text or ""
    if act == "no":
        await c.answer("Yuborilmadi")
        await c.message.edit_caption(caption=base + "\n\n🚫 <i>Kanalga yuborilmadi</i>", reply_markup=None)
        return
    movie = await db_get_movie(int(mid))
    target = channel_target(await db_get_setting("movie_channel"))
    if not movie or not target:
        await c.answer("❌ Kanal manzili aniqlanmadi. Sozlamalarda kino kanal havolasini ochiq (t.me/nom) qiling.",
                       show_alert=True)
        return
    me = await bot.me()
    url = f"https://t.me/{me.username}?start=m_{movie['code']}"
    try:
        await bot.send_photo(target, movie["poster_id"], caption=svc_channel_caption(movie, me.username),
                             reply_markup=kb_channel_post_kb(url))
    except TelegramAPIError as e:
        await c.answer(f"❌ Yuborib bo'lmadi: {e.message[:150]}\nBot kanalda admin bo'lishi kerak.", show_alert=True)
        return
    await db_log(c.from_user.id, "channel_post", f"movie={movie['code']}")
    await c.answer("✅ Kanalga yuborildi")
    await c.message.edit_caption(caption=base + "\n\n✅ <i>Kanalga yuborildi</i>", reply_markup=None)


# ═════════════════════════ KINO O'CHIRISH ═════════════════════════
@admin_router.message(F.text == kb_A_DEL_MOVIE)
async def del_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(DelMovie.code)
    await m.answer("🗑 O'chiriladigan <b>kino kodini</b> yozing:", reply_markup=kb_cancel_kb())


@admin_router.message(DelMovie.code, F.text, NOT_MENU)
async def del_code(m: Message, state: FSMContext):
    movie = await db_get_movie_by_code(m.text.strip())
    if not movie:
        await m.answer("❌ Bunday kod topilmadi. Qayta kiriting.")
        return
    await state.clear()
    await m.answer("Tasdiqlang:", reply_markup=kb_admin_menu())
    await m.answer(f"🗑 <b>{esc(movie['title'])}</b> (kod: <code>{esc(movie['code'])}</code>) o'chirilsinmi?",
                   reply_markup=kb_confirm_delete_kb(movie["id"]))


@admin_router.callback_query(F.data.startswith("del:"))
async def del_confirm(c: CallbackQuery):
    _, act, mid = c.data.split(":")
    if act == "no":
        await c.answer("Bekor qilindi")
        await c.message.edit_text("↩️ Bekor qilindi.")
        return
    movie = await db_get_movie(int(mid))
    if not movie:
        await c.answer("Allaqachon o'chirilgan", show_alert=True)
        return
    await db_delete_movie(movie["id"])
    await db_log(c.from_user.id, "movie_delete", f"code={movie['code']} title={movie['title']}")
    await c.answer("O'chirildi")
    await c.message.edit_text(f"✅ <b>{esc(movie['title'])}</b> o'chirildi.")


# ═════════════════════════ KINO TAHRIRLASH ═════════════════════════
@admin_router.message(F.text == kb_A_EDIT_MOVIE)
async def edit_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(EditMovie.code)
    await m.answer("✏ Tahrirlanadigan <b>kino kodini</b> yozing:", reply_markup=kb_cancel_kb())


@admin_router.message(EditMovie.code, F.text, NOT_MENU)
async def edit_code(m: Message, state: FSMContext):
    movie = await db_get_movie_by_code(m.text.strip())
    if not movie:
        await m.answer("❌ Bunday kod topilmadi. Qayta kiriting.")
        return
    await state.clear()
    await m.answer("Nimani o'zgartiramiz?", reply_markup=kb_admin_menu())
    await m.answer(
        f"🎬 <b>{esc(movie['title'])}</b>\n🔑 Kod: <code>{esc(movie['code'])}</code>\n"
        f"💎 Turi: {'VIP' if movie['is_vip'] else 'Oddiy'}\n👁 Ko'rishlar: {movie['views']}",
        reply_markup=kb_edit_kb(movie["id"], bool(movie["is_vip"])))


EDIT_PROMPTS = {
    "title": "📝 Yangi <b>nomni</b> kiriting:",
    "code": "🔑 Yangi <b>kodni</b> kiriting:",
    "poster": "🖼 Yangi <b>rasmni</b> yuboring:",
    "video": "🎞 Yangi <b>video</b> yoki <b>havola</b> yuboring:",
}


@admin_router.callback_query(F.data.startswith("ed:"))
async def edit_pick(c: CallbackQuery, state: FSMContext, bot: Bot):
    _, field, mid = c.data.split(":")
    movie = await db_get_movie(int(mid))
    if not movie:
        await c.answer("Kino topilmadi", show_alert=True)
        return
    if field == "vip":
        new = 0 if movie["is_vip"] else 1
        await db_update_movie(movie["id"], is_vip=new)
        await db_log(c.from_user.id, "movie_edit", f"code={movie['code']} vip={new}")
        await c.answer("Yangilandi")
        await c.message.edit_reply_markup(reply_markup=kb_edit_kb(movie["id"], bool(new)))
        return
    await c.answer()
    await state.set_state(EditMovie.value)
    await state.update_data(mid=movie["id"], field=field)
    await bot.send_message(c.from_user.id, EDIT_PROMPTS[field], reply_markup=kb_cancel_kb())


@admin_router.message(EditMovie.value, NOT_MENU)
async def edit_value(m: Message, state: FSMContext):
    d = await state.get_data()
    movie = await db_get_movie(d["mid"])
    if not movie:
        await _done(m, state, "❌ Kino topilmadi.")
        return
    f = d["field"]
    if f == "title":
        if not m.text or not 1 <= len(m.text.strip()) <= 200:
            await m.answer("❗ Nom 1–200 belgi bo'lsin.")
            return
        await db_update_movie(movie["id"], title=m.text.strip())
    elif f == "code":
        code = (m.text or "").strip()
        if not CODE_RE.fullmatch(code):
            await m.answer("❗ Kod noto'g'ri formatda.")
            return
        other = await db_get_movie_by_code(code)
        if other and other["id"] != movie["id"]:
            await m.answer("❌ Bu kod band.")
            return
        await db_update_movie(movie["id"], code=code)
    elif f == "poster":
        if not m.photo:
            await m.answer("❗ Rasm yuboring.")
            return
        await db_update_movie(movie["id"], poster_id=m.photo[-1].file_id)
    else:
        parsed = _parse_video(m)
        if not parsed:
            await m.answer("❗ Video, fayl yoki havola yuboring.")
            return
        await db_update_movie(movie["id"], video_id=parsed[0], video_type=parsed[1])
    await db_log(m.from_user.id, "movie_edit", f"code={movie['code']} field={f}")
    await _done(m, state, "✅ Kino yangilandi.")


# ═════════════════════════ MAJBURIY KANALLAR ═════════════════════════
@admin_router.message(F.text == kb_A_ADD_CHANNEL)
async def ch_add_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddChannel.ref)
    await m.answer(
        "📢 Kanalni yuboring:\n• <code>@username</code> yoki havola\n• kanal ID si\n• kanaldan <b>forward</b> qilingan xabar\n\n"
        "⚠️ Bot kanalda <b>admin</b> bo'lishi shart.", reply_markup=kb_cancel_kb())


@admin_router.message(AddChannel.ref, NOT_MENU)
async def ch_add(m: Message, state: FSMContext, bot: Bot):
    ref = None
    fo = getattr(m, "forward_origin", None)
    if fo is not None and getattr(fo, "chat", None) is not None:
        ref = fo.chat.id
    elif m.text:
        ref = parse_chat_ref(m.text)
    if ref is None:
        await m.answer("❗ Kanal aniqlanmadi. @username, havola, ID yoki forward yuboring.")
        return
    try:
        chat = await bot.get_chat(ref)
    except TelegramAPIError:
        await m.answer("❌ Kanal topilmadi yoki bot unda yo'q.")
        return
    if chat.type not in ("channel", "supergroup", "group"):
        await m.answer("❌ Bu kanal/guruh emas.")
        return
    me = await bot.me()
    try:
        mem = await bot.get_chat_member(chat.id, me.id)
        is_adm = mem.status in ("administrator", "creator")
    except TelegramAPIError:
        is_adm = False
    if not is_adm:
        await m.answer("❌ Avval botni shu kanalga <b>admin</b> qiling, so'ng qayta yuboring.")
        return
    link = f"https://t.me/{chat.username}" if chat.username else None
    if not link:
        try:
            link = getattr(chat, "invite_link", None) or await bot.export_chat_invite_link(chat.id)
        except TelegramAPIError:
            link = None
    if not link:
        await m.answer("❌ Kanal havolasini olib bo'lmadi (botga «havola yaratish» huquqini bering).")
        return
    await db_add_channel(chat.id, chat.title or str(chat.id), link)
    await db_log(m.from_user.id, "channel_add", f"{chat.id} {chat.title}")
    await _done(m, state, f"✅ Majburiy kanal qo'shildi: <b>{esc(chat.title)}</b>")


async def _channels_text() -> str:
    chs = await db_list_channels()
    if not chs:
        return "📭 Majburiy kanallar yo'q."
    return "📢 <b>Majburiy kanallar:</b>\n\n" + "\n".join(
        f"{i}. {esc(c['title'])} — {esc(c['link'])}" for i, c in enumerate(chs, 1))


@admin_router.message(F.text == kb_A_DEL_CHANNEL)
async def ch_del_list(m: Message, state: FSMContext):
    await state.clear()
    chs = await db_list_channels()
    if not chs:
        await m.answer("📭 Majburiy kanallar yo'q.")
        return
    await m.answer("🗑 O'chiriladigan kanalni tanlang:", reply_markup=kb_channels_del_kb(chs))


@admin_router.callback_query(F.data.startswith("chdel:"))
async def ch_del(c: CallbackQuery):
    ch = await db_get_channel(int(c.data.split(":")[1]))
    if ch:
        await db_delete_channel(ch["id"])
        await db_log(c.from_user.id, "channel_delete", f"{ch['chat_id']} {ch['title']}")
    await c.answer("O'chirildi")
    chs = await db_list_channels()
    if chs:
        await c.message.edit_reply_markup(reply_markup=kb_channels_del_kb(chs))
    else:
        await c.message.edit_text("📭 Majburiy kanallar yo'q.")


# ═════════════════════════ KARTA ═════════════════════════
async def start_card(bot: Bot, chat_id: int, state: FSMContext):
    await state.clear()
    await state.set_state(CardStates.number)
    cur = await db_get_setting("card_number")
    await bot.send_message(chat_id, f"💳 Joriy karta: <code>{esc(cur)}</code>\n\nYangi <b>karta raqamini</b> kiriting (16 xona):",
                           reply_markup=kb_cancel_kb())


@admin_router.message(F.text == kb_A_CARD)
async def card_start(m: Message, state: FSMContext, bot: Bot):
    await start_card(bot, m.chat.id, state)


@admin_router.message(CardStates.number, F.text, NOT_MENU)
async def card_number(m: Message, state: FSMContext):
    d = re.sub(r"\D", "", m.text)
    if len(d) != 16:
        await m.answer("❗ Karta raqami 16 ta raqamdan iborat bo'lishi kerak.")
        return
    await state.update_data(number=fmt_card(d))
    await state.set_state(CardStates.owner)
    await m.answer("👤 <b>Karta egasining ismini</b> kiriting:")


@admin_router.message(CardStates.owner, F.text, NOT_MENU)
async def card_owner(m: Message, state: FSMContext):
    if not 2 <= len(m.text.strip()) <= 80:
        await m.answer("❗ Ism 2–80 belgi bo'lsin.")
        return
    await state.update_data(owner=m.text.strip())
    await state.set_state(CardStates.bank)
    await m.answer("🏦 <b>Bank nomini</b> kiriting (kerak bo'lmasa «-»):")


@admin_router.message(CardStates.bank, F.text, NOT_MENU)
async def card_bank(m: Message, state: FSMContext):
    d = await state.get_data()
    bank = "" if m.text.strip() == "-" else m.text.strip()[:60]
    await db_set_setting("card_number", d["number"])
    await db_set_setting("card_owner", d["owner"])
    await db_set_setting("card_bank", bank)
    await db_log(m.from_user.id, "card_change", d["number"][-4:])
    await _done(m, state, "✅ Karta yangilandi:\n\n" + svc_card_block(d["number"], d["owner"], bank))


# ═════════════════════════ PREMIUM NARXI ═════════════════════════
async def _prices() -> dict[str, int]:
    return {k: int(await db_get_setting(f"price_{k}")) for k in PLANS}


async def show_prices(bot: Bot, chat_id: int, state: FSMContext):
    await state.clear()
    await bot.send_message(chat_id, "⭐ <b>Premium narxlari</b>\nO'zgartirmoqchi bo'lgan tarifni tanlang:",
                           reply_markup=kb_price_kb(await _prices()))


@admin_router.message(F.text == kb_A_PRICE)
async def price_start(m: Message, state: FSMContext, bot: Bot):
    await show_prices(bot, m.chat.id, state)


@admin_router.callback_query(F.data.startswith("pr:"))
async def price_pick(c: CallbackQuery, state: FSMContext, bot: Bot):
    plan = c.data[3:]
    if plan not in PLANS:
        await c.answer()
        return
    await c.answer()
    await state.set_state(PriceStates.value)
    await state.update_data(plan=plan)
    await bot.send_message(c.from_user.id, f"💰 <b>{PLANS[plan][0]}</b> uchun yangi narxni kiriting (so'mda):",
                           reply_markup=kb_cancel_kb())


@admin_router.message(PriceStates.value, F.text, NOT_MENU)
async def price_value(m: Message, state: FSMContext):
    t = re.sub(r"[\s,.']", "", m.text)
    if not t.isdigit() or not (1000 <= int(t) <= 100_000_000):
        await m.answer("❗ Narx 1 000 dan 100 000 000 gacha bo'lgan raqam bo'lsin.")
        return
    plan = (await state.get_data())["plan"]
    await db_set_setting(f"price_{plan}", t)
    await db_log(m.from_user.id, "price_change", f"{plan}={t}")
    await _done(m, state, f"✅ {PLANS[plan][0]} narxi: <b>{money(t)}</b> so'm.\n"
                          "<i>Yangi so'rovlar yangi narxda beriladi.</i>")


# ═════════════════════════ PREMIUM TO'LOVLARI ═════════════════════════
@admin_router.message(F.text == kb_A_PAYMENTS)
async def payments_list(m: Message, state: FSMContext, bot: Bot):
    await state.clear()
    rows = await db_list_pending()
    if not rows:
        await m.answer("📭 Kutayotgan to'lovlar yo'q.")
        return
    await m.answer(f"💰 Kutayotgan to'lovlar: <b>{len(rows)}</b>")
    for p in rows:
        await svc_send_payment_to(bot, m.chat.id, p)


@admin_router.callback_query(F.data.startswith("pa:"))
async def payment_decide(c: CallbackQuery, bot: Bot):
    _, act, pid = c.data.split(":")
    p = await db_get_payment(int(pid))
    base = c.message.html_text or ""

    async def mark(text: str):
        try:
            await c.message.edit_caption(caption=base + f"\n\n{text}", reply_markup=None)
        except TelegramBadRequest:
            pass

    if not p or p["status"] != "pending":
        await c.answer("Bu so'rov allaqachon ko'rib chiqilgan.", show_alert=True)
        await mark("ℹ️ <i>Allaqachon ko'rib chiqilgan</i>")
        return

    if act == "no":
        if await db_reject_payment(p["id"], c.from_user.id):
            await db_log(c.from_user.id, "payment_reject", f"id={p['id']} user={p['user_id']}")
            await c.answer("Bekor qilindi")
            await mark(f"❌ <i>Bekor qilindi</i> (admin {c.from_user.id})")
            try:
                await bot.send_message(p["user_id"], "❌ <b>To'lov tasdiqlanmadi.</b>\nPremium berilmaydi.")
            except TelegramAPIError:
                pass
        return

    # Tasdiqlash — xavfsizlik tekshiruvlari
    if not p["check_file_id"]:
        await c.answer("❌ Chek yo'q — Premium berilmaydi.", show_alert=True)
        return
    if p["amount_paid"] != p["amount_due"]:
        await c.answer(
            f"❌ Summa mos emas!\nKerak: {money(p['amount_due'])}\nKiritilgan: {money(p['amount_paid'] or 0)}\n"
            "Noto'g'ri summada Premium berilmaydi. Bekor qiling.", show_alert=True)
        return
    if not await db_approve_payment(p["id"], c.from_user.id):
        await c.answer("Allaqachon ko'rib chiqilgan.", show_alert=True)
        return
    days = PLANS[p["plan"]][1]
    exp = await db_grant_premium(p["user_id"], p["plan"], days)
    await db_stat_inc("payments")
    await db_stat_inc("revenue", p["amount_due"])
    await db_log(c.from_user.id, "payment_approve", f"id={p['id']} user={p['user_id']} sum={p['amount_due']}")
    await c.answer("✅ Premium berildi")
    await mark(f"✅ <i>Tasdiqlandi</i> (admin {c.from_user.id})")
    try:
        await bot.send_message(p["user_id"],
                               f"✅ <b>Premium muvaffaqiyatli yoqildi.</b>\n📅 Amal qilish muddati: <b>{fmt_date(exp)}</b> gacha",
                               reply_markup=kb_main_menu())
    except TelegramAPIError:
        pass


# ═════════════════════════ PREMIUM BERISH (qo'lda) ═════════════════════════
async def _give_premium(bot: Bot, admin_id: int, uid: int, plan: str, days: int) -> int:
    exp = await db_grant_premium(uid, plan, days)
    await db_log(admin_id, "premium_grant_admin", f"user={uid} days={days}")
    try:
        await bot.send_message(
            uid, f"✅ <b>Premium muvaffaqiyatli yoqildi.</b>\n📅 Amal qilish muddati: <b>{fmt_date(exp)}</b> gacha",
            reply_markup=kb_main_menu())
    except TelegramAPIError:
        pass
    return exp


@admin_router.message(F.text == kb_A_GRANT)
async def grant_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(GrantStates.user_id)
    await m.answer("🎁 Premium beriladigan foydalanuvchining <b>Telegram ID</b> sini yozing:",
                   reply_markup=kb_cancel_kb())


@admin_router.message(GrantStates.user_id, F.text, NOT_MENU)
async def grant_id(m: Message, state: FSMContext):
    t = m.text.strip()
    if not t.isdigit():
        await m.answer("❗ Faqat raqamli Telegram ID kiriting.")
        return
    uid = int(t)
    u = await db_get_user(uid)
    p = await db_get_premium(uid)
    name = esc(u["first_name"]) if u else "— (botga hali kirmagan)"
    status = f"✅ faol, {fmt_date(p['expires_at'])} gacha" if p else "❌ yo'q"
    await state.clear()
    await m.answer(f"👤 {name}\n🆔 <code>{uid}</code>\n⭐ Premium: {status}", reply_markup=kb_admin_menu())
    await m.answer("Muddatni tanlang:", reply_markup=kb_grant_kb(uid))


@admin_router.callback_query(F.data.startswith("gr:"))
async def grant_pick(c: CallbackQuery, state: FSMContext, bot: Bot):
    _, act, uid_s = c.data.split(":")
    uid = int(uid_s)
    if act == "rev":
        ok = await db_revoke_premium(uid)
        await db_log(c.from_user.id, "premium_revoke", f"user={uid} ok={ok}")
        await c.answer("Olib tashlandi" if ok else "Bu foydalanuvchida Premium yo'q", show_alert=not ok)
        if ok:
            await c.message.edit_text(f"🗑 <code>{uid}</code> dan Premium olib tashlandi.")
        return
    if act == "days":
        await c.answer()
        await state.set_state(GrantStates.days)
        await state.update_data(uid=uid)
        await bot.send_message(c.from_user.id, "✏ Necha <b>kunga</b> Premium beramiz? (1–3650)",
                               reply_markup=kb_cancel_kb())
        return
    if act not in PLANS:
        await c.answer()
        return
    days = PLANS[act][1]
    exp = await _give_premium(bot, c.from_user.id, uid, act, days)
    await c.answer("✅ Berildi")
    await c.message.edit_text(f"✅ <code>{uid}</code> ga <b>{PLANS[act][0]}</b> Premium berildi.\n📅 {fmt_date(exp)} gacha")


@admin_router.message(GrantStates.days, F.text, NOT_MENU)
async def grant_days(m: Message, state: FSMContext, bot: Bot):
    t = m.text.strip()
    if not t.isdigit() or not (1 <= int(t) <= 3650):
        await m.answer("❗ 1 dan 3650 gacha kun kiriting.")
        return
    uid = (await state.get_data())["uid"]
    exp = await _give_premium(bot, m.from_user.id, uid, "admin", int(t))
    await _done(m, state, f"✅ <code>{uid}</code> ga <b>{t} kunlik</b> Premium berildi.\n📅 {fmt_date(exp)} gacha")


# ═════════════════════════ BLOKLASH ═════════════════════════
@admin_router.message(F.text == kb_A_BAN)
async def ban_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(BlockStates.user_id)
    await m.answer("🚫 Bloklanadigan <b>Telegram ID</b> ni yozing:", reply_markup=kb_cancel_kb())


@admin_router.message(BlockStates.user_id, F.text, NOT_MENU)
async def ban_do(m: Message, state: FSMContext):
    t = m.text.strip()
    if not t.isdigit():
        await m.answer("❗ Faqat raqamli Telegram ID kiriting.")
        return
    uid = int(t)
    if await db_is_admin(uid):
        await m.answer("❌ Adminni bloklab bo'lmaydi.")
        return
    await db_ban_user(uid, m.from_user.id)
    await db_log(m.from_user.id, "user_ban", str(uid))
    await _done(m, state, f"🚫 <code>{uid}</code> bloklandi.")


@admin_router.message(F.text == kb_A_UNBAN)
async def unban_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(UnblockStates.user_id)
    await m.answer("✅ Blokdan chiqariladigan <b>Telegram ID</b> ni yozing:", reply_markup=kb_cancel_kb())


@admin_router.message(UnblockStates.user_id, F.text, NOT_MENU)
async def unban_do(m: Message, state: FSMContext):
    t = m.text.strip()
    if not t.isdigit():
        await m.answer("❗ Faqat raqamli Telegram ID kiriting.")
        return
    ok = await db_unban_user(int(t))
    await db_log(m.from_user.id, "user_unban", f"{t} ok={ok}")
    await _done(m, state, f"✅ <code>{t}</code> blokdan chiqarildi." if ok else "ℹ️ Bu ID bloklanganlar ro'yxatida yo'q.")


# ═════════════════════════ REKLAMA YUBORISH ═════════════════════════
@admin_router.message(F.text == kb_A_BROADCAST)
async def bc_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(BroadcastStates.content)
    await m.answer("📨 Barcha foydalanuvchilarga yuboriladigan xabarni yuboring:\n"
                   "matn, rasm, video yoki <b>forward</b> qilingan xabar.", reply_markup=kb_cancel_kb())


@admin_router.message(BroadcastStates.content, NOT_MENU)
async def bc_content(m: Message, state: FSMContext, bot: Bot):
    fwd = getattr(m, "forward_origin", None) is not None
    kind = "forward" if fwd else m.content_type.value if hasattr(m.content_type, "value") else str(m.content_type)
    await state.update_data(src_chat=m.chat.id, src_msg=m.message_id, fwd=fwd, kind=kind)
    n = len(await db_broadcast_user_ids())
    await m.answer("👀 <b>Ko'rinishi:</b>", reply_markup=kb_admin_menu())
    try:
        if fwd:
            await bot.forward_message(m.chat.id, m.chat.id, m.message_id)
        else:
            await bot.copy_message(m.chat.id, m.chat.id, m.message_id)
    except TelegramAPIError as e:
        await m.answer(f"❌ Bu xabarni yuborib bo'lmaydi: {e.message[:150]}")
        return
    await m.answer(f"Yuboramizmi? Qabul qiluvchilar: <b>{n}</b>", reply_markup=kb_broadcast_kb())


@admin_router.callback_query(F.data.startswith("bc:"))
async def bc_confirm(c: CallbackQuery, state: FSMContext, bot: Bot):
    d = await state.get_data()
    if c.data == "bc:no" or "src_msg" not in d:
        await state.clear()
        await c.answer("Bekor qilindi")
        await c.message.edit_text("↩️ Reklama bekor qilindi.")
        return
    await state.clear()
    ad_id = await db_add_ad(c.from_user.id, d["kind"], d["src_chat"], d["src_msg"])
    await db_log(c.from_user.id, "broadcast_start", f"ad={ad_id} kind={d['kind']}")
    await c.answer("Boshlandi")
    await c.message.edit_text("🚀 Yuborish boshlandi. Tugagach hisobot beraman.")
    task = asyncio.create_task(_broadcast(bot, ad_id, c.from_user.id, d))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _broadcast(bot: Bot, ad_id: int, admin_id: int, d: dict) -> None:
    ids = await db_broadcast_user_ids()
    sent = failed = 0

    async def send(uid: int) -> bool:
        for _ in range(2):
            try:
                if d["fwd"]:
                    await bot.forward_message(uid, d["src_chat"], d["src_msg"])
                else:
                    await bot.copy_message(uid, d["src_chat"], d["src_msg"])
                return True
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except TelegramForbiddenError:
                await db_set_left(uid, True)
                return False
            except TelegramAPIError:
                return False
        return False

    for uid in ids:
        if await send(uid):
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(0.05)  # ~20 xabar/soniya
    await db_finish_ad(ad_id, sent, failed)
    await db_log(admin_id, "broadcast_done", f"ad={ad_id} sent={sent} failed={failed}")
    try:
        await bot.send_message(admin_id, f"📨 <b>Reklama yuborildi</b>\n\n✅ Yetkazildi: {sent}\n❌ Xato/bloklagan: {failed}",
                               reply_markup=kb_admin_menu())
    except TelegramAPIError:
        pass


# ═════════════════════════ STATISTIKA ═════════════════════════
@admin_router.message(F.text == kb_A_STATS)
async def stats(m: Message, state: FSMContext):
    await state.clear()
    s = await db_stats_summary()
    await m.answer(
        "📊 <b>Statistika</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{s['total']}</b>\n"
        f"🆕 Bugun qo'shilganlar: <b>{s['new_today']}</b>\n"
        f"⭐ Premium foydalanuvchilar: <b>{s['premium']}</b>\n"
        f"👤 Oddiy foydalanuvchilar: <b>{s['regular']}</b>\n"
        f"🚫 Bloklanganlar: <b>{s['banned']}</b>\n"
        f"🚪 Botni tark etganlar: <b>{s['left']}</b>\n"
        f"💳 Bugungi to'lovlar: <b>{s['pay_today']}</b> ta ({money(s['rev_today'])} so'm)\n"
        f"💰 Umumiy daromad: <b>{money(s['revenue'])}</b> so'm\n"
        f"👁 Bugungi ko'rilgan kinolar: <b>{s['views_today']}</b>\n"
        f"🎬 Jami kinolar soni: <b>{s['movies']}</b>")


# ═════════════════════════ SOZLAMALAR ═════════════════════════
EDITABLE = {
    "start_text": "👋 Start matni",
    "bot_name": "🤖 Bot nomi",
    "premium_text": "⭐ Premium matni",
    "ad_text": "📣 Reklama matni",
    "daily_limit": "🔢 Kunlik limit",
    "movie_channel": "📢 Kino kanal havolasi",
}
HTML_KEYS = {"start_text", "premium_text", "ad_text"}


@admin_router.message(F.text == kb_A_SETTINGS)
async def settings_menu(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("⚙ <b>Sozlamalar</b>\nNimani o'zgartiramiz?", reply_markup=kb_settings_kb(EDITABLE))


@admin_router.callback_query(F.data.startswith("st:"))
async def settings_pick(c: CallbackQuery, state: FSMContext, bot: Bot):
    key = c.data[3:]
    await c.answer()
    if key == "card":
        await start_card(bot, c.from_user.id, state)
    elif key == "prices":
        await show_prices(bot, c.from_user.id, state)
    elif key == "channels":
        await bot.send_message(c.from_user.id,
                               await _channels_text() + "\n\nQo'shish/o'chirish uchun admin menyudagi tugmalardan foydalaning.")
    elif key in EDITABLE:
        cur = (await db_get_setting(key))[:900]
        extra = "\n<i>Formatlash (qalin, kursiv, havola) saqlanadi.</i>" if key in HTML_KEYS else ""
        if key in ("start_text",):
            extra += "\nMaxsus so'zlar: <code>{name}</code> — ism, <code>{bot}</code> — bot nomi."
        if key == "ad_text":
            extra += "\nTozalash uchun «-» yuboring."
        await state.set_state(SettingStates.value)
        await state.update_data(key=key)
        await bot.send_message(c.from_user.id,
                               f"{EDITABLE[key]}\n\nJoriy qiymat:\n<code>{esc(cur) or '—'}</code>\n\nYangi qiymatni yuboring.{extra}",
                               reply_markup=kb_cancel_kb())


@admin_router.message(SettingStates.value, F.text, NOT_MENU)
async def settings_value(m: Message, state: FSMContext):
    key = (await state.get_data())["key"]
    val = m.html_text.strip() if key in HTML_KEYS else m.text.strip()
    if key == "ad_text" and val == "-":
        val = ""
    if key == "daily_limit":
        if not val.isdigit() or not (1 <= int(val) <= 10000):
            await m.answer("❗ Limit 1 dan 10000 gacha raqam bo'lsin.")
            return
    elif key == "movie_channel":
        if not re.match(r"^https?://t\.me/\S+$", val):
            await m.answer("❗ Havola <code>https://t.me/...</code> ko'rinishida bo'lsin.")
            return
    elif key == "bot_name":
        if not 1 <= len(val) <= 60:
            await m.answer("❗ Nom 1–60 belgi bo'lsin.")
            return
    elif len(val) > 3500:
        await m.answer("❗ Matn juda uzun (maks 3500 belgi).")
        return
    if key in HTML_KEYS and val:
        try:
            preview = val.replace("{name}", "Ism").replace("{bot}", "Bot")
            await m.answer("👀 <b>Ko'rinishi:</b>\n\n" + preview)
        except TelegramBadRequest:
            await m.answer("❌ Matn formati xato. Qayta yuboring.")
            return
    await db_set_setting(key, val)
    await db_log(m.from_user.id, "setting_change", key)
    await _done(m, state, f"✅ {EDITABLE[key]} yangilandi.")


# ══════════════════════════════════════════════════════════════════════
# HANDLERS/USER
# ══════════════════════════════════════════════════════════════════════
user_router = Router(name="user")
user_router.message.middleware(SubscriptionGate())
user_router.callback_query.middleware(SubscriptionGate())


# ───────────────────────── yordamchi funksiyalar ─────────────────────────
async def send_welcome(bot: Bot, user) -> None:
    name = await db_get_setting("bot_name")
    tpl = await db_get_setting("start_text")
    text = tpl.replace("{name}", esc(user.first_name)).replace("{bot}", esc(name))
    try:
        await bot.send_message(user.id, text, reply_markup=kb_main_menu())
    except TelegramBadRequest:
        await bot.send_message(user.id, text, parse_mode=None, reply_markup=kb_main_menu())


def _link_url(movie) -> str | None:
    if movie["video_type"] == "link" and (movie["video_id"] or "").startswith(("http://", "https://")):
        return movie["video_id"]
    return None


async def deliver_movie(bot: Bot, user_id: int, code: str) -> bool:
    movie = await db_get_movie_by_code(code)
    if not movie:
        await bot.send_message(user_id, "❌ Bunday kod topilmadi.")
        return False

    premium = await db_is_admin(user_id) or await db_get_premium(user_id)
    if movie["is_vip"] and not premium:
        await bot.send_message(
            user_id, "💎 <b>Bu VIP kino.</b>\nUni faqat Premium foydalanuvchilar ko'ra oladi.",
            reply_markup=kb_premium_btn())
        return False

    limit = int(await db_get_setting("daily_limit") or 10)
    used, reset = await db_get_usage(user_id)
    if not premium and used >= limit:
        left = max(reset - db_now(), 0)
        await bot.send_message(
            user_id,
            "❌ <b>Bugungi limit tugadi.</b>\n\n"
            "⭐ Premium sotib olishingiz mumkin.\n"
            f"🔄 Limit {left // 3600} soat {left % 3600 // 60} daqiqadan keyin yangilanadi.",
            reply_markup=kb_premium_btn())
        return False

    me = await bot.me()
    is_fav = await db_is_favorite(user_id, movie["id"])
    vip = " 💎" if movie["is_vip"] else ""
    quota = "" if premium else f"\n📊 Limit: {used + 1}/{limit}"
    caption = (f"🎬 <b>{esc(movie['title'])}</b>{vip}\n🔑 Kod: <code>{esc(movie['code'])}</code>"
               f"{quota}\n\n🤖 @{me.username}")
    url = _link_url(movie)
    try:
        if movie["poster_id"]:
            await bot.send_photo(user_id, movie["poster_id"],
                                 caption=f"🎬 <b>{esc(movie['title'])}</b>{vip}\n🔑 Kod: <code>{esc(movie['code'])}</code>")
        mk = kb_movie_kb(movie["id"], is_fav, url)
        if movie["video_type"] == "link":
            await bot.send_message(user_id, caption + f"\n\n🔗 {esc(movie['video_id'])}", reply_markup=mk)
        elif movie["video_type"] == "document":
            await bot.send_document(user_id, movie["video_id"], caption=caption, reply_markup=mk)
        else:
            await bot.send_video(user_id, movie["video_id"], caption=caption, reply_markup=mk,
                                 supports_streaming=True)
    except TelegramAPIError as e:
        log.error("Kino yuborilmadi (%s): %s", code, e)
        await bot.send_message(user_id, "⚠️ Kino vaqtincha yuborilmadi. Keyinroq urinib ko'ring.")
        return False
    await db_register_view(user_id, movie["id"])
    return True


async def show_premium(bot: Bot, user_id: int) -> None:
    prices = {k: int(await db_get_setting(f"price_{k}")) for k in PLANS}
    p = await db_get_premium(user_id)
    head = f"✅ <b>Sizda Premium faol</b> — {fmt_date(p['expires_at'])} gacha.\nMuddatni uzaytirishingiz mumkin.\n\n" if p else ""
    text = (
        f"⭐ <b>PREMIUM</b>\n\n{head}{await db_get_setting('premium_text')}\n\n"
        "✅ Majburiy obunasiz ishlaydi\n✅ Cheksiz kino\n✅ VIP kinolar\n✅ Kunlik limit yo'q\n\n"
        "💎 <b>Tarifni tanlang:</b>"
    )
    try:
        await bot.send_message(user_id, text, reply_markup=kb_premium_kb(prices))
    except TelegramBadRequest:
        await bot.send_message(user_id, text, parse_mode=None, reply_markup=kb_premium_kb(prices))


# ───────────────────────── /start ─────────────────────────
@user_router.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext, bot: Bot, command: CommandObject):
    await state.clear()
    await send_welcome(bot, m.from_user)
    arg = command.args or ""
    if arg.startswith("m_"):
        await deliver_movie(bot, m.from_user.id, arg[2:])


@user_router.callback_query(F.data == "check_sub")
async def check_sub(c: CallbackQuery, state: FSMContext, bot: Bot):
    missing = await svc_not_joined(bot, c.from_user.id, force=True)
    if missing:
        await c.answer("❌ Hali barcha kanallarga a'zo bo'lmadingiz!", show_alert=True)
        channels = await db_list_channels()
        try:
            await c.message.edit_reply_markup(
                reply_markup=kb_subscribe_kb(channels, {x["id"] for x in missing}))
        except TelegramBadRequest:
            pass
        return
    await c.answer("✅ Rahmat!")
    try:
        await c.message.delete()
    except TelegramAPIError:
        pass
    data = await state.get_data()
    code = data.pop("pending_code", None)
    await state.set_data(data)
    await send_welcome(bot, c.from_user)
    if code:
        await deliver_movie(bot, c.from_user.id, code)


# ───────────────────────── asosiy menyu (har qanday holatda ishlaydi) ─────────────────────────
@user_router.message(F.text == kb_BTN_MOVIE)
async def btn_movie(m: Message, state: FSMContext):
    await state.set_state(UserStates.code)
    await m.answer("🎬 <b>Kino kodini kiriting.</b>\n\nMasalan: <code>2514</code>",
                   reply_markup=kb_main_menu())


@user_router.message(F.text == kb_BTN_SEARCH)
async def btn_search(m: Message, state: FSMContext):
    await state.set_state(UserStates.search)
    await m.answer("🔎 <b>Kino nomini yozing.</b>\n\nMasalan: <i>Forsaj</i>", reply_markup=kb_main_menu())


@user_router.message(F.text == kb_BTN_PREMIUM)
async def btn_premium(m: Message, state: FSMContext, bot: Bot):
    await state.clear()
    await show_premium(bot, m.from_user.id)


@user_router.message(F.text == kb_BTN_CHANNEL)
async def btn_channel(m: Message, state: FSMContext):
    await state.clear()
    link = await db_get_setting("movie_channel")
    mk = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📢 Kanalga o'tish", url=link)]])
    await m.answer("📢 <b>Kino kanalimiz</b>\n\nYangi kinolar shu yerda e'lon qilinadi.", reply_markup=mk)


@user_router.message(F.text == kb_BTN_ADS)
async def btn_ads(m: Message, state: FSMContext):
    await state.clear()
    ad = (await db_get_setting("ad_text")).strip()
    await m.answer(ad if ad else "📣 Hozircha reklama mavjud emas.")


@user_router.message(F.text == kb_BTN_PROFILE)
async def btn_profile(m: Message, state: FSMContext):
    await state.clear()
    u = m.from_user
    p = await db_get_premium(u.id)
    used, _ = await db_get_usage(u.id)
    limit = await db_get_setting("daily_limit")
    status = "✅ Faol" if p else "❌ Yo'q"
    until = f"\n📅 Premium tugash sanasi: <b>{fmt_date(p['expires_at'])}</b>" if p else ""
    await m.answer(
        "👤 <b>Profil</b>\n\n"
        f"📛 Ism: {esc(u.first_name)}\n"
        f"🆔 Telegram ID: <code>{u.id}</code>\n"
        f"🔗 Username: {'@' + esc(u.username) if u.username else '—'}\n"
        f"⭐ Premium: {status}{until}\n"
        f"🎬 Bugungi ko'rilgan kinolar: <b>{used}/{'∞' if p else limit}</b>")


@user_router.message(F.text == kb_BTN_FAVS)
async def btn_favs(m: Message, state: FSMContext):
    await state.clear()
    rows = await db_list_favorites(m.from_user.id)
    if not rows:
        await m.answer("❤️ Sevimli kinolar yo'q.\nKino ostidagi «❤️ Sevimlilarga qo'shish» tugmasini bosing.")
        return
    await m.answer("❤️ <b>Sevimli kinolaringiz:</b>", reply_markup=kb_movies_list_kb(rows))


@user_router.message(F.text == kb_BTN_HISTORY)
async def btn_history(m: Message, state: FSMContext):
    await state.clear()
    rows = await db_list_history(m.from_user.id)
    if not rows:
        await m.answer("📜 Siz hali kino ko'rmagansiz.")
        return
    await m.answer("📜 <b>Oxirgi ko'rgan kinolaringiz:</b>", reply_markup=kb_movies_list_kb(rows))


# ───────────────────────── callbacklar ─────────────────────────
@user_router.callback_query(F.data == "premium")
async def cb_premium(c: CallbackQuery, bot: Bot):
    await c.answer()
    await show_premium(bot, c.from_user.id)


@user_router.callback_query(F.data.startswith("mv:"))
async def cb_movie(c: CallbackQuery, bot: Bot):
    await c.answer()
    await deliver_movie(bot, c.from_user.id, c.data[3:])


@user_router.callback_query(F.data.startswith("fav:"))
async def cb_fav(c: CallbackQuery):
    mid = int(c.data[4:])
    movie = await db_get_movie(mid)
    if not movie:
        await c.answer("Kino topilmadi", show_alert=True)
        return
    now_fav = await db_toggle_favorite(c.from_user.id, mid)
    await c.answer("❤️ Sevimlilarga qo'shildi" if now_fav else "💔 Sevimlilardan olib tashlandi")
    try:
        await c.message.edit_reply_markup(reply_markup=kb_movie_kb(mid, now_fav, _link_url(movie)))
    except TelegramBadRequest:
        pass


@user_router.callback_query(F.data.startswith("plan:"))
async def cb_plan(c: CallbackQuery, bot: Bot):
    plan = c.data[5:]
    if plan not in PLANS:
        await c.answer()
        return
    if await db_get_pending_for_user(c.from_user.id):
        await c.answer("⏳ Sizning to'lov so'rovingiz admin tomonidan tekshirilmoqda.", show_alert=True)
        return
    pay = await db_reserve_payment(c.from_user.id, plan)
    if not pay:
        await c.answer("⚠️ Hozir band. Birozdan keyin urinib ko'ring.", show_alert=True)
        return
    await c.answer()
    card = await db_get_setting("card_number")
    owner = await db_get_setting("card_owner")
    bank = await db_get_setting("card_bank")
    minutes = await db_get_setting("reserve_minutes")
    await db_log(c.from_user.id, "payment_reserve", f"id={pay['id']} plan={plan} sum={pay['amount_due']}")
    await bot.send_message(
        c.from_user.id,
        f"💳 <b>To'lov</b>\n\n📦 Tarif: <b>{PLANS[plan][0]}</b>\n"
        f"💰 Sizning summangiz: <code>{pay['amount_due']}</code> so'm\n\n"
        f"{svc_card_block(card, owner, bank)}\n"
        "⚠️ <b>Sizga berilgan aynan shu summani yuboring.</b>\n"
        "Boshqa summa yuborilsa Premium berilmaydi.\n\n"
        f"⏱ Admin 2 daqiqa ichida tekshiradi.\n"
        f"<i>Summa {minutes} daqiqa davomida faqat sizga biriktirilgan.</i>",
        reply_markup=kb_pay_kb(pay["id"]))


@user_router.callback_query(F.data.startswith("paycancel:"))
async def cb_paycancel(c: CallbackQuery, state: FSMContext):
    await db_cancel_payment(int(c.data.split(":")[1]), c.from_user.id)
    await state.clear()
    await c.answer("Bekor qilindi")
    try:
        await c.message.edit_text("❌ To'lov so'rovi bekor qilindi.")
    except TelegramBadRequest:
        pass


@user_router.callback_query(F.data.startswith("pay:"))
async def cb_pay(c: CallbackQuery, state: FSMContext, bot: Bot):
    pid = int(c.data.split(":")[1])
    p = await db_get_payment(pid)
    if not p or p["user_id"] != c.from_user.id or p["status"] != "created":
        await c.answer("Bu so'rov eskirgan. Premium bo'limidan qaytadan boshlang.", show_alert=True)
        return
    await db_touch_payment(pid)
    await c.answer()
    await state.set_state(PayStates.tg_id)
    await state.update_data(pid=pid)
    await bot.send_message(c.from_user.id, "🆔 <b>Telegram ID</b> raqamingizni yuboring.",
                           reply_markup=kb_tgid_kb())


# ───────────────────────── to'lov bosqichlari ─────────────────────────
@user_router.message(PayStates.tg_id)
async def pay_tg_id(m: Message, state: FSMContext):
    txt = (m.text or "").strip()
    if txt == kb_BTN_MY_ID:
        val = str(m.from_user.id)
    elif txt.isdigit() and 5 <= len(txt) <= 15:
        val = txt
    else:
        await m.answer("❗ Telegram ID faqat raqamlardan iborat. Qayta yuboring yoki tugmani bosing.")
        return
    await state.update_data(tg_id=val)
    await state.set_state(PayStates.phone)
    await m.answer("📱 <b>Telefon raqamingizni</b> yuboring.", reply_markup=kb_phone_kb())


@user_router.message(PayStates.phone)
async def pay_phone(m: Message, state: FSMContext):
    raw = m.contact.phone_number if m.contact else (m.text or "")
    digits = re.sub(r"[\s\-()]", "", raw)
    if not re.fullmatch(r"\+?\d{9,15}", digits):
        await m.answer("❗ Telefon raqami noto'g'ri. Masalan: <code>+998901234567</code>")
        return
    if not digits.startswith("+"):
        digits = "+" + digits
    await state.update_data(phone=digits)
    await state.set_state(PayStates.amount)
    data = await state.get_data()
    p = await db_get_payment(data["pid"])
    await m.answer(f"💰 <b>Necha so'm tashladingiz?</b>\nSizga berilgan summa: <code>{p['amount_due']}</code>",
                   reply_markup=kb_cancel_kb())


@user_router.message(PayStates.amount, F.text)
async def pay_amount(m: Message, state: FSMContext):
    t = re.sub(r"[\s,.']", "", m.text)
    if not t.isdigit() or not (100 <= int(t) <= 100_000_000):
        await m.answer("❗ Summani faqat raqam bilan yozing. Masalan: <code>8003</code>")
        return
    await state.update_data(paid=int(t))
    await state.set_state(PayStates.check)
    await m.answer("📷 <b>To'lov chekini yuboring</b> (rasm yoki PDF).")


@user_router.message(PayStates.check)
async def pay_check(m: Message, state: FSMContext, bot: Bot):
    if m.photo:
        fid, ctype = m.photo[-1].file_id, "photo"
    elif m.document and (m.document.mime_type or "").startswith(("image/", "application/pdf")):
        fid, ctype = m.document.file_id, "document"
    else:
        await m.answer("❗ Chek yuborilmasdan Premium berilmaydi. Iltimos, chekni rasm ko'rinishida yuboring.")
        return
    d = await state.get_data()
    p = await db_get_payment(d["pid"])
    if not p or p["status"] != "created":
        await state.clear()
        await m.answer("⚠️ So'rov muddati tugagan. Premium bo'limidan qaytadan boshlang.",
                       reply_markup=kb_main_menu())
        return
    ok = await db_submit_payment(p["id"], d["tg_id"], d["phone"], d["paid"], fid, ctype)
    await state.clear()
    if not ok:
        await m.answer("⚠️ Xatolik yuz berdi. Qaytadan urinib ko'ring.", reply_markup=kb_main_menu())
        return
    await db_set_phone(m.from_user.id, d["phone"])
    await db_log(m.from_user.id, "payment_submit",
                 f"id={p['id']} kerak={p['amount_due']} tolangan={d['paid']}")
    await m.answer("✅ <b>So'rovingiz adminga yuborildi.</b>\n⏳ Admin 2 daqiqa ichida tekshiradi.",
                   reply_markup=kb_main_menu())
    await svc_notify_admins_payment(bot, p["id"])


# ───────────────────────── kod / qidiruv holatlari ─────────────────────────
@user_router.message(UserStates.search, F.text)
async def do_search(m: Message):
    q = m.text.strip()
    if len(q) < 2:
        await m.answer("❗ Kamida 2 ta belgi kiriting.")
        return
    rows = await db_search_movies(q)
    if not rows:
        await m.answer("❌ Hech narsa topilmadi.")
        return
    await m.answer(f"🔎 <b>Topilganlar ({len(rows)}):</b>", reply_markup=kb_movies_list_kb(rows))


@user_router.message(UserStates.code, F.text)
async def do_code(m: Message, bot: Bot):
    await deliver_movie(bot, m.from_user.id, m.text.strip())


# ───────────────────────── botni bloklash/qayta ochish ─────────────────────────
@user_router.my_chat_member()
async def on_member_update(ev: ChatMemberUpdated):
    if ev.chat.type == "private":
        await db_set_left(ev.from_user.id, ev.new_chat_member.status in ("kicked", "left"))


# ───────────────────────── fallback: holatsiz matn ─────────────────────────
@user_router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def fallback_text(m: Message, bot: Bot):
    txt = m.text.strip()
    if await db_get_movie_by_code(txt):
        await deliver_movie(bot, m.from_user.id, txt)
        return
    rows = await db_search_movies(txt) if len(txt) >= 2 else []
    if rows:
        await m.answer(f"🔎 <b>Topilganlar ({len(rows)}):</b>", reply_markup=kb_movies_list_kb(rows))
    else:
        await m.answer("❌ Bunday kod topilmadi.")


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════
def setup_logging() -> None:
    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    handlers = [logging.StreamHandler(),
                RotatingFileHandler("bot.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)


async def on_error(event: ErrorEvent) -> bool:
    logging.getLogger("main").exception("Handler xatosi: %s", event.exception)
    upd = event.update
    try:
        if upd.message:
            await upd.message.answer("⚠️ Xatolik yuz berdi. Qaytadan urinib ko'ring.")
        elif upd.callback_query:
            await upd.callback_query.answer("⚠️ Xatolik yuz berdi.", show_alert=True)
    except Exception:
        pass
    return True


async def main() -> None:
    setup_logging()
    log = logging.getLogger("main")
    await db_init_db()

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    dp.errors.register(on_error)
    access = AccessMiddleware()
    dp.message.outer_middleware(access)
    dp.callback_query.outer_middleware(access)

    # Tartib muhim: common → admin → user
    dp.include_router(common_router)
    dp.include_router(admin_router)
    dp.include_router(user_router)

    await bot.set_my_commands([BotCommand(command="start", description="Botni ishga tushirish")])
    me = await bot.get_me()
    log.info("Bot ishga tushdi: @%s", me.username)

    task = asyncio.create_task(background_loop(bot))
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        task.cancel()
        await db_close_db()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
