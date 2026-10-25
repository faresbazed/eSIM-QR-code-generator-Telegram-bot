#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Arabic Telegram eSIM QR & LPA Converter Bot
-------------------------------------------
Features:
- Converts LPA strings (LPA:1$...) or Apple/Android eSIM URLs into:
  * High-resolution QR code image
  * Extracted SM-DP+ server address & Activation Code
  * Full manual LPA code (tap-to-copy)
  * Direct Automatic Install links for iOS (Apple) and Android
  * Inline URL buttons ("📲 تركيب على الأيفون" and "🤖 تركيب على الأندرويد")
- Decodes QR code photos/images sent by users into the full eSIM message + buttons
- Forwards/logs all user messages to the bot Admin(s) with user metadata
  (Name, @Username, User ID, conversion status, and copy of the message/QR)
- Allows Admin(s) to reply directly to any user by replying to the notification
  or the forwarded message below it
- Includes Admin moderation commands: /ban, /unban, /banned, /stats, /admin
"""

import html
import io
import logging
import os
import re
import sqlite3
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
import qrcode
from PIL import Image
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Optional pyzbar fallback for additional QR decoding robustness
try:
    from pyzbar.pyzbar import decode as pyzbar_decode
except Exception:
    pyzbar_decode = None


# ---------------------------------------------------------------------------
# Environment & Configuration Loader
# ---------------------------------------------------------------------------
def load_dotenv_file(dotenv_path: str = ".env") -> None:
    """Lightweight built-in .env loader (no external dependency required)."""
    path = Path(dotenv_path)
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv_file()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
RAW_ADMIN_IDS = os.getenv("ADMIN_ID", os.getenv("ADMIN_IDS", "")).strip()
DB_PATH = os.getenv("DB_PATH", "bot_data.db").strip()

ADMIN_IDS: set[int] = set()
for part in re.split(r"[,\s]+", RAW_ADMIN_IDS):
    if part.strip().lstrip("-").isdigit():
        ADMIN_IDS.add(int(part.strip()))

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("esim_bot")


# ---------------------------------------------------------------------------
# SQLite Database Layer (Users, Bans, and Admin Reply Mapping)
# ---------------------------------------------------------------------------
class BotDatabase:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    full_name TEXT,
                    username TEXT,
                    first_seen TEXT,
                    last_seen TEXT,
                    conversions_count INTEGER DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS banned_users (
                    user_id INTEGER PRIMARY KEY,
                    reason TEXT,
                    banned_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS message_map (
                    admin_chat_id INTEGER,
                    admin_message_id INTEGER,
                    target_user_id INTEGER,
                    created_at TEXT,
                    PRIMARY KEY (admin_chat_id, admin_message_id)
                )
                """
            )
            conn.commit()

    def upsert_user(
        self,
        user_id: int,
        full_name: str,
        username: Optional[str],
        increment_conversion: bool = False,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, full_name, username, first_seen, last_seen, conversions_count)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    full_name = excluded.full_name,
                    username = excluded.username,
                    last_seen = excluded.last_seen,
                    conversions_count = users.conversions_count + ?
                """,
                (
                    user_id,
                    full_name,
                    username or "",
                    now,
                    now,
                    1 if increment_conversion else 0,
                    1 if increment_conversion else 0,
                ),
            )
            conn.commit()

    def ban_user(self, user_id: int, reason: str = "بدون سبب") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO banned_users (user_id, reason, banned_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    reason = excluded.reason,
                    banned_at = excluded.banned_at
                """,
                (user_id, reason, now),
            )
            conn.commit()

    def unban_user(self, user_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM banned_users WHERE user_id = ?", (user_id,)
            )
            conn.commit()
            return cur.rowcount > 0

    def get_ban_info(self, user_id: int) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT reason FROM banned_users WHERE user_id = ?", (user_id,)
            ).fetchone()
            return row["reason"] if row else None

    def list_banned_users(self) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT user_id, reason, banned_at FROM banned_users ORDER BY banned_at DESC"
            ).fetchall()

    def save_message_link(
        self, admin_chat_id: int, admin_message_id: int, target_user_id: int
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO message_map
                (admin_chat_id, admin_message_id, target_user_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (admin_chat_id, admin_message_id, target_user_id, now),
            )
            conn.commit()

    def get_target_user_id(
        self, admin_chat_id: int, admin_message_id: int
    ) -> Optional[int]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT target_user_id FROM message_map
                WHERE admin_chat_id = ? AND admin_message_id = ?
                """,
                (admin_chat_id, admin_message_id),
            ).fetchone()
            return int(row["target_user_id"]) if row else None

    def get_stats(self) -> Tuple[int, int, int]:
        with self._connect() as conn:
            total_users = conn.execute(
                "SELECT COUNT(*) AS c FROM users"
            ).fetchone()["c"]
            total_conversions = conn.execute(
                "SELECT COALESCE(SUM(conversions_count), 0) AS s FROM users"
            ).fetchone()["s"]
            total_banned = conn.execute(
                "SELECT COUNT(*) AS c FROM banned_users"
            ).fetchone()["c"]
            return int(total_users), int(total_conversions), int(total_banned)


db = BotDatabase(DB_PATH)


# ---------------------------------------------------------------------------
# LPA Parsing, Formatting & QR Code Utilities
# ---------------------------------------------------------------------------
LPA_REGEX = re.compile(
    r"(LPA:1\$[A-Za-z0-9._\-]+\$[A-Za-z0-9._\-]+(?:\$[A-Za-z0-9._\-]*)*)",
    re.IGNORECASE,
)
BARE_LPA_REGEX = re.compile(
    r"(?<!LPA:)(1\$[A-Za-z0-9._\-]+\.[A-Za-z0-9._\-]+\$[A-Za-z0-9._\-]+(?:\$[A-Za-z0-9._\-]*)*)",
    re.IGNORECASE,
)
CARDDATA_URL_REGEX = re.compile(
    r"carddata=([^\s&\"'<>]+)",
    re.IGNORECASE,
)


def extract_lpa_from_text(text: str) -> Optional[str]:
    """
    Extracts and normalizes an LPA string from:
    1. Standard LPA string: LPA:1$smdp.address$matching_id
    2. Apple/Android provisioning URL with ?carddata=LPA%3A1%24...
    3. Bare 1$smdp.address$matching_id string
    """
    if not text:
        return None

    cleaned = text.strip()

    # Check if text contains an Apple/Android provisioning URL with carddata=
    url_match = CARDDATA_URL_REGEX.search(cleaned)
    if url_match:
        unquoted = urllib.parse.unquote(url_match.group(1)).strip()
        m = LPA_REGEX.search(unquoted)
        if m:
            raw = m.group(1).strip()
            return "LPA:" + raw[4:]

    # Direct LPA:1$... match
    m = LPA_REGEX.search(cleaned)
    if m:
        raw = m.group(1).strip()
        return "LPA:" + raw[4:]

    # Bare 1$smdp$activation_code match
    m_bare = BARE_LPA_REGEX.search(cleaned)
    if m_bare:
        return "LPA:" + m_bare.group(1).strip()

    return None


def parse_lpa_components(lpa_code: str) -> Tuple[str, str, str]:
    """
    Splits an LPA string (LPA:1$smdp$matching_id[$...]) into:
    (normalized_lpa, smdp_address, matching_id)
    """
    normalized = lpa_code.strip()
    if normalized.lower().startswith("lpa:"):
        normalized = "LPA:" + normalized[4:]
    elif normalized.startswith("1$"):
        normalized = "LPA:" + normalized

    parts = normalized.split("$")
    smdp_address = parts[1].strip() if len(parts) > 1 else "—"
    matching_id = parts[2].strip() if len(parts) > 2 else "—"
    return normalized, smdp_address, matching_id


def build_install_links(lpa_code: str) -> Tuple[str, str]:
    """
    Builds Apple (iOS) and Android universal eSIM provisioning URLs
    matching the exact URL-encoding format in the reference screenshots.
    """
    encoded_lpa = urllib.parse.quote(lpa_code.strip(), safe="")
    apple_url = (
        f"https://esimsetup.apple.com/esim_qrcode_provisioning?carddata={encoded_lpa}"
    )
    android_url = (
        f"https://esimsetup.android.com/esim_qrcode_provisioning?carddata={encoded_lpa}"
    )
    return apple_url, android_url


def build_esim_message_and_keyboard(
    lpa_code: str,
) -> Tuple[str, InlineKeyboardMarkup]:
    """
    Builds the exact Arabic message text and inline keyboard buttons
    shown in the reference screenshots.
    """
    normalized_lpa, smdp, matching_id = parse_lpa_components(lpa_code)
    apple_url, android_url = build_install_links(normalized_lpa)

    safe_smdp = html.escape(smdp)
    safe_matching_id = html.escape(matching_id)
    safe_lpa = html.escape(normalized_lpa)
    safe_apple_url = html.escape(apple_url)
    safe_android_url = html.escape(android_url)

    message_html = (
        "✅ <b>بيانات الشريحة</b>\n\n"
        "<b>عنوان السيرفر (SM-DP+):</b>\n"
        f"<code>{safe_smdp}</code>\n\n"
        "<b>كود التفعيل:</b>\n"
        f"<code>{safe_matching_id}</code>\n\n"
        "<b>الكود اليدوي الكامل:</b>\n"
        f"<code>{safe_lpa}</code>\n\n"
        "📲 <b>لينك التركيب التلقائي:</b>\n"
        f"- الأيفون: {safe_apple_url}\n"
        f"- الأندرويد: {safe_android_url}\n\n"
        "⚠️ افتح اللينك من متصفح الجهاز (Safari/Chrome) مش من جوه تليجرام."
    )

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📲 تركيب على الأيفون", url=apple_url)],
            [InlineKeyboardButton("🤖 تركيب على الأندرويد", url=android_url)],
        ]
    )

    return message_html, keyboard


def generate_qr_image_bytes(data: str) -> io.BytesIO:
    """Generates a clean, high-contrast QR code PNG in memory."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=4,
    )
    qr.add_data(data.strip())
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    bio = io.BytesIO()
    bio.name = "esim_qr.png"
    img.save(bio, format="PNG", optimize=True)
    bio.seek(0)
    return bio


def decode_qr_from_bytes(image_bytes: bytes) -> Optional[str]:
    """
    Decodes a QR code from raw image bytes using multi-pass preprocessing
    (pyzbar if installed + OpenCV QRCodeDetector across multiple thresholds/scales).
    """
    try:
        pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        logger.warning("Failed to open image bytes: %s", exc)
        return None

    # 1. Try pyzbar if available on system
    if pyzbar_decode is not None:
        try:
            decoded_objs = pyzbar_decode(pil_img)
            for obj in decoded_objs:
                text = obj.data.decode("utf-8", errors="ignore").strip()
                if text:
                    return text
        except Exception:
            pass

    # 2. Multi-pass OpenCV QRCodeDetector
    bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    detector = cv2.QRCodeDetector()

    candidates = [
        bgr,
        gray,
        cv2.bitwise_not(gray),  # Inverted (dark mode QR codes)
        cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1],
        cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 5
        ),
        cv2.copyMakeBorder(
            gray, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255
        ),
    ]

    # Also add upscaled/downscaled versions if image is very small or very large
    h, w = gray.shape[:2]
    if max(h, w) < 500:
        candidates.append(
            cv2.resize(gray, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
        )
    elif max(h, w) > 1600:
        scale = 1200.0 / max(h, w)
        candidates.append(
            cv2.resize(
                gray,
                (int(w * scale), int(h * scale)),
                interpolation=cv2.INTER_AREA,
            )
        )

    for candidate in candidates:
        try:
            data, _, _ = detector.detectAndDecode(candidate)
            if data and data.strip():
                return data.strip()
            ok, decoded_info, _, _ = detector.detectAndDecodeMulti(candidate)
            if ok and decoded_info:
                for item in decoded_info:
                    if item and item.strip():
                        return item.strip()
        except Exception:
            continue

    return None


# ---------------------------------------------------------------------------
# Helper: Admin Notification & Forwarding
# ---------------------------------------------------------------------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def notify_admins(
    context: ContextTypes.DEFAULT_TYPE,
    message: Message,
    status_html: str,
    qr_bytes_for_admin: Optional[bytes] = None,
) -> None:
    """
    Sends the exact notification card shown in image.png to every configured Admin,
    followed immediately by the message/QR below it so the Admin can reply to it.
    """
    user = message.from_user
    if not user:
        return

    # If the sender is the admin testing the bot in their own chat, skip duplicate self-forwarding
    if is_admin(user.id):
        return

    full_name = html.escape(user.full_name or "بدون اسم")
    username_display = f"@{html.escape(user.username)}" if user.username else "@—"

    admin_header = (
        "📩 <b>رسالة جديدة</b>\n"
        f"👤 {full_name}\n"
        f"🔗 {username_display}\n"
        f"🆔 <code>{user.id}</code>\n\n"
        f"{status_html}\n\n"
        "↩️ رد على الرسالة اللي تحت عشان تبعتله."
    )

    for admin_id in ADMIN_IDS:
        try:
            # 1) Send the metadata summary card
            header_msg = await context.bot.send_message(
                chat_id=admin_id,
                text=admin_header,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            db.save_message_link(admin_id, header_msg.message_id, user.id)

            # 2) Send the QR photo (if generated/converted) or copy the user's message right below it
            if qr_bytes_for_admin is not None:
                bio = io.BytesIO(qr_bytes_for_admin)
                bio.name = "esim_qr.png"
                below_msg = await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=bio,
                )
            else:
                below_msg = await context.bot.copy_message(
                    chat_id=admin_id,
                    from_chat_id=message.chat_id,
                    message_id=message.message_id,
                )
            db.save_message_link(admin_id, below_msg.message_id, user.id)
        except Exception as exc:
            logger.error("Failed to notify admin %s: %s", admin_id, exc)


async def send_esim_result_to_user(
    message: Message,
    lpa_code: str,
    qr_bytes: bytes,
) -> None:
    """
    Sends the QR code image + full formatted eSIM details + direct install buttons to the user.
    """
    text_html, keyboard = build_esim_message_and_keyboard(lpa_code)
    photo_io = io.BytesIO(qr_bytes)
    photo_io.name = "esim_qr.png"

    # Send QR code photo first, or photo with caption + buttons if under Telegram's 1024-char caption limit
    if len(text_html) <= 1024:
        await message.reply_photo(
            photo=photo_io,
            caption=text_html,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    else:
        await message.reply_photo(photo=photo_io)
        await message.reply_text(
            text=text_html,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )


# ---------------------------------------------------------------------------
# Bot Command Handlers
# ---------------------------------------------------------------------------
async def start_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    ban_reason = db.get_ban_info(user.id)
    if ban_reason and not is_admin(user.id):
        await message.reply_text(
            f"🚫 تم حظرك من استخدام البوت.\nالسبب: {ban_reason}"
        )
        return

    db.upsert_user(user.id, user.full_name, user.username)

    welcome_text = (
        "👋 <b>أهلاً بك في بوت تحويل شرائح الـ eSIM (QR & LPA)</b>\n\n"
        "🔹 <b>إزاي تستخدم البوت؟</b>\n"
        "1️⃣ ابعت <b>صورة QR Code</b> الخاصة بالشريحة، وهطلعلك كود الـ LPA الكامل ولينكات وأزرار التركيب المباشر للأيفون والأندرويد.\n"
        "2️⃣ أو ابعت <b>كود الـ LPA</b> (اللي بيبدأ بـ <code>LPA:1$</code>)، وهحولهولك لصورة QR Code جاهزة للمسح مع لينكات وأزرار التركيب التلقائي.\n\n"
        "📩 <i>ابعت الكود أو صورة الـ QR دلوقتي!</i>"
    )
    await message.reply_text(welcome_text, parse_mode=ParseMode.HTML)

    if is_admin(user.id):
        admin_help = (
            "🛠️ <b>أوامر الأدمن:</b>\n"
            "• <code>/ban ID سبب</code> — حظر مستخدم\n"
            "• <code>/unban ID</code> — فك حظر مستخدم\n"
            "• <code>/banned</code> — عرض قائمة المحظورين\n"
            "• <code>/stats</code> — إحصائيات البوت\n"
            "• للرد على أي مستخدم: اعمل <b>Reply (رد)</b> على رسالته أو كارت الإشعار اللي بيوصلك."
        )
        await message.reply_text(admin_help, parse_mode=ParseMode.HTML)


async def ban_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    if not context.args:
        await message.reply_text(
            "⚠️ الاستخدام الصحيح:\n<code>/ban ID سبب الحظر</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    target_str = context.args[0].strip()
    if not target_str.isdigit():
        await message.reply_text("❌ رقم الـ ID يجب أن يكون أرقاماً فقط.")
        return

    target_id = int(target_str)
    reason = " ".join(context.args[1:]).strip() or "مخالفة شروط الاستخدام"
    db.ban_user(target_id, reason)

    await message.reply_text(
        f"✅ تم حظر المستخدم <code>{target_id}</code> بنجاح.\nالسبب: {html.escape(reason)}",
        parse_mode=ParseMode.HTML,
    )


async def unban_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    if not context.args or not context.args[0].strip().isdigit():
        await message.reply_text(
            "⚠️ الاستخدام الصحيح:\n<code>/unban ID</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    target_id = int(context.args[0].strip())
    removed = db.unban_user(target_id)
    if removed:
        await message.reply_text(
            f"✅ تم فك الحظر عن المستخدم <code>{target_id}</code>.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await message.reply_text(
            f"ℹ️ المستخدم <code>{target_id}</code> غير موجود في قائمة الحظر.",
            parse_mode=ParseMode.HTML,
        )


async def banned_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    rows = db.list_banned_users()
    if not rows:
        await message.reply_text("✅ لا يوجد مستخدمون محظورون حالياً.")
        return

    lines = ["🚫 <b>قائمة المستخدمين المحظورين:</b>\n"]
    for row in rows:
        lines.append(
            f"• <code>{row['user_id']}</code> — {html.escape(row['reason'] or '')}"
        )
    await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def stats_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return

    total_users, total_conversions, total_banned = db.get_stats()
    text = (
        "📊 <b>إحصائيات البوت:</b>\n\n"
        f"👥 إجمالي المستخدمين: <b>{total_users}</b>\n"
        f"🔄 إجمالي عمليات التحويل: <b>{total_conversions}</b>\n"
        f"🚫 المحظورون: <b>{total_banned}</b>"
    )
    await message.reply_text(text, parse_mode=ParseMode.HTML)


# ---------------------------------------------------------------------------
# Message & Media Handlers
# ---------------------------------------------------------------------------
def extract_user_id_from_reply(reply_msg: Message) -> Optional[int]:
    """
    Resolves the target user ID when an Admin replies to a notification card
    or to the forwarded/copied message below it.
    """
    # 1. Lookup in SQLite message_map
    mapped = db.get_target_user_id(reply_msg.chat_id, reply_msg.message_id)
    if mapped:
        return mapped

    # 2. Fallback: parse 🆔 <id> from the message text/caption if present
    content = reply_msg.text or reply_msg.caption or ""
    m = re.search(r"🆔\s*(\d+)", content)
    if m:
        return int(m.group(1))

    return None


async def handle_admin_reply(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    If the sender is an Admin replying to a user notification/forwarded message,
    routes the reply back to that user and returns True.
    """
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not is_admin(user.id):
        return False

    if not message.reply_to_message:
        return False

    target_user_id = extract_user_id_from_reply(message.reply_to_message)
    if not target_user_id:
        return False

    try:
        await context.bot.copy_message(
            chat_id=target_user_id,
            from_chat_id=message.chat_id,
            message_id=message.message_id,
        )
        await message.reply_text(
            f"✅ تم إرسال رسالتك إلى المستخدم <code>{target_user_id}</code> بنجاح.",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logger.error("Failed to send admin reply to %s: %s", target_user_id, exc)
        await message.reply_text(
            f"❌ فشل إرسال الرد للمستخدم <code>{target_user_id}</code>: {html.escape(str(exc))}",
            parse_mode=ParseMode.HTML,
        )
    return True


async def handle_text_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    # Check if admin is replying to a user's forwarded message
    if await handle_admin_reply(update, context):
        return

    # Check if user is banned
    ban_reason = db.get_ban_info(user.id)
    if ban_reason and not is_admin(user.id):
        await message.reply_text(
            f"🚫 تم حظرك من استخدام البوت.\nالسبب: {ban_reason}"
        )
        return

    text = message.text or ""
    lpa_code = extract_lpa_from_text(text)

    if lpa_code:
        normalized_lpa, _, _ = parse_lpa_components(lpa_code)
        qr_io = generate_qr_image_bytes(normalized_lpa)
        qr_bytes = qr_io.getvalue()

        db.upsert_user(
            user.id, user.full_name, user.username, increment_conversion=True
        )
        await send_esim_result_to_user(message, normalized_lpa, qr_bytes)

        status_html = (
            "✅ تحويل LPA ناجح\n"
            f"<code>{html.escape(normalized_lpa)}</code>"
        )
        await notify_admins(
            context, message, status_html, qr_bytes_for_admin=qr_bytes
        )
    else:
        db.upsert_user(
            user.id, user.full_name, user.username, increment_conversion=False
        )
        await message.reply_text(
            "⚠️ لم يتم العثور على كود LPA صالح في رسالتك.\n\n"
            "ابعت كود يبدأ بـ <code>LPA:1$</code> أو ابعت صورة الـ QR Code الخاصة بالشريحة.",
            parse_mode=ParseMode.HTML,
        )
        status_html = f"💬 رسالة نصية:\n<code>{html.escape(text[:500])}</code>"
        await notify_admins(context, message, status_html)


async def handle_image_or_other_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return

    # Check if admin is replying with media/photo/voice to a user
    if await handle_admin_reply(update, context):
        return

    # Check if user is banned
    ban_reason = db.get_ban_info(user.id)
    if ban_reason and not is_admin(user.id):
        await message.reply_text(
            f"🚫 تم حظرك من استخدام البوت.\nالسبب: {ban_reason}"
        )
        return

    # Determine if the message contains an image (Photo or Image Document)
    tg_file = None
    if message.photo:
        tg_file = await message.photo[-1].get_file()
    elif (
        message.document
        and message.document.mime_type
        and message.document.mime_type.startswith("image/")
    ):
        tg_file = await message.document.get_file()

    if tg_file is not None:
        img_bytearray = await tg_file.download_as_bytearray()
        raw_bytes = bytes(img_bytearray)
        decoded_text = decode_qr_from_bytes(raw_bytes)

        # Also check caption if QR wasn't found in image
        lpa_code = extract_lpa_from_text(decoded_text or "") or extract_lpa_from_text(
            message.caption or ""
        )

        if lpa_code:
            normalized_lpa, _, _ = parse_lpa_components(lpa_code)
            clean_qr_io = generate_qr_image_bytes(normalized_lpa)
            clean_qr_bytes = clean_qr_io.getvalue()

            db.upsert_user(
                user.id,
                user.full_name,
                user.username,
                increment_conversion=True,
            )
            await send_esim_result_to_user(
                message, normalized_lpa, clean_qr_bytes
            )

            status_html = (
                "✅ تحويل QR ناجح\n"
                f"<code>{html.escape(normalized_lpa)}</code>"
            )
            await notify_admins(
                context,
                message,
                status_html,
                qr_bytes_for_admin=clean_qr_bytes,
            )
            return
        else:
            db.upsert_user(
                user.id,
                user.full_name,
                user.username,
                increment_conversion=False,
            )
            if decoded_text:
                await message.reply_text(
                    "⚠️ تم قراءة الـ QR ولكن لا يحتوي على كود شريحة eSIM (LPA) صالح:\n"
                    f"<code>{html.escape(decoded_text[:400])}</code>",
                    parse_mode=ParseMode.HTML,
                )
                status_html = (
                    "⚠️ QR غير خاص بـ eSIM:\n"
                    f"<code>{html.escape(decoded_text[:400])}</code>"
                )
            else:
                await message.reply_text(
                    "❌ لم أتمكن من قراءة كود الـ QR من الصورة. تأكد من أن الصورة واضحة وأعد المحاولة."
                )
                status_html = "❌ فشل قراءة QR من الصورة المرسلة"
            await notify_admins(context, message, status_html)
            return

    # Non-image attachment (voice, video, sticker, file, etc.) — forward to admin
    db.upsert_user(
        user.id, user.full_name, user.username, increment_conversion=False
    )
    await message.reply_text(
        "📩 تم استلام رسالتك. لتحويل شريحة eSIM، ابعت صورة الـ QR Code أو كود الـ LPA."
    )
    status_html = "📎 مرفق / وسائط من المستخدم"
    await notify_admins(context, message, status_html)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit(
            "Error: BOT_TOKEN is not set. Add BOT_TOKEN and ADMIN_ID to your .env file or environment variables."
        )

    if not ADMIN_IDS:
        logger.warning(
            "Warning: ADMIN_ID is not set. Admin notifications will be disabled until ADMIN_ID is configured."
        )

    application = Application.builder().token(BOT_TOKEN).build()

    # Commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", start_command))
    application.add_handler(CommandHandler("admin", start_command))
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("unban", unban_command))
    application.add_handler(CommandHandler("banned", banned_command))
    application.add_handler(CommandHandler("stats", stats_command))

    # Text messages (LPA codes, links, admin replies, general text)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
    )

    # Photos, image documents, and all other media
    application.add_handler(
        MessageHandler(~filters.TEXT & ~filters.COMMAND, handle_image_or_other_message)
    )

    logger.info("Bot started polling... (Configured Admins: %s)", list(ADMIN_IDS))
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()