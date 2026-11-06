#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eSIM QR Code, LPA & Direct Link Converter Telegram Bot
Supports: Arabic (default), English, Chinese
Features:
- Converts eSIM QR code images, LPA strings, and Apple/Android installation links
  into a complete installation package (High-res QR + SM-DP+ + Activation Code +
  Full Manual LPA + Apple/Android Direct Links + Direct Install Inline Buttons)
- Forwards all user messages & activity to the Bot Owner/Admin
- Interactive Admin Control Panel (/admin) & Slash Commands (/ban, /unban, /send,
  /broadcast, /stats, /users)
- Interactive console & web setup prompt if BOT_TOKEN or OWNER_ID are not set in env
"""

import asyncio
import csv
import html
import io
import json
import logging
import os
import re
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, unquote, urlparse

import cv2
import numpy as np
import qrcode
from PIL import Image
from dotenv import load_dotenv

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Load .env if present
load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("esim_bot")

CONFIG_FILE = os.environ.get("CONFIG_FILE", "config.json")
DB_FILE = os.environ.get("DB_FILE", "bot_data.db")

# ==============================================================================
# 1. MULTILINGUAL TRANSLATIONS (Arabic Default, English, Chinese)
# ==============================================================================

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "ar": {
        "lang_name": "العربية 🇸🇦",
        "welcome": (
            "👋 <b>أهلاً بك في بوت تحويل واستخراج بيانات الشريحة الإلكترونية (eSIM)!</b>\n\n"
            "أرسل لي أي مما يلي:\n"
            "• 📷 <b>صورة باركود (QR Code)</b> للشريحة\n"
            "• 📝 <b>كود LPA النصي</b> (مثل: <code>LPA:1$rsp.truphone.com$...</code>)\n"
            "• 🔗 <b>لينك التركيب المباشر</b> (Apple أو Android)\n\n"
            "وسأقوم فوراً باستخراج وتوليد:\n"
            "✅ صورة QR Code واضحة جاهزة للمسح\n"
            "✅ عنوان السيرفر (SM-DP+) وكود التفعيل للنسخ السريع\n"
            "✅ الكود اليدوي الكامل (LPA)\n"
            "✅ روابط وأزرار التركيب التلقائي المباشر للأيفون والأندرويد"
        ),
        "choose_lang": "🌐 اختر لغة البوت / Choose Language / 选择语言:",
        "lang_updated": "✅ تم تغيير اللغة إلى العربية.",
        "esim_Caption": (
            "✅ <b>بيانات تركيب الشريحة</b>\n\n"
            "<b>عنوان السيرفر (SM-DP+):</b>\n"
            "<code>{smdp}</code>\n\n"
            "<b>كود التفعيل:</b>\n"
            "<code>{matching_id}</code>\n"
            "{confirmation_block}\n"
            "<b>الكود اليدوي الكامل:</b>\n"
            "<code>{lpa}</code>\n\n"
            "📲 <b>لينك التركيب التلقائي:</b>\n"
            "- الأيفون: {apple_url}\n"
            "- الأندرويد: {android_url}\n\n"
            "⚠️ افتح اللينك من متصفح الجهاز (Safari/Chrome) مش من جوه تليجرام."
        ),
        "confirmation_line": "\n<b>كود التأكيد (Confirmation Code):</b>\n<code>{code}</code>\n",
        "btn_iphone": "📲 تركيب على الأيفون",
        "btn_android": "🤖 تركيب على الأندرويد",
        "btn_change_lang": "🌐 تغيير اللغة | Language",
        "invalid_input": (
            "❌ <b>لم أتمكن من العثور على بيانات شريحة eSIM صالحة في رسالتك.</b>\n\n"
            "تأكد من إرسال:\n"
            "1️⃣ صورة باركود QR واضحة تحتوي على بيانات eSIM\n"
            "2️⃣ أو كود يبدأ بـ <code>LPA:1$</code>\n"
            "3️⃣ أو رابط تركيب مباشر من Apple / Android."
        ),
        "qr_not_found": (
            "❌ <b>لم أتمكن من قراءة باركود eSIM من هذه الصورة.</b>\n"
            "يرجى التأكد من أن الصورة واضحة وتحتوي على باركود (QR Code) صالح للشريحة."
        ),
        "banned_notice": "🚫 <b>عذراً، تم حظرك من استخدام هذا البوت.</b>\nالسبب: {reason}",
        "admin_reply_prefix": "📩 <b>رسالة من إدارة البوت:</b>\n\n{message}",
        "help_text": (
            "📖 <b>طريقة الاستخدام:</b>\n\n"
            "• أرسل صورة QR Code أو كود LPA أو رابط التركيب وسأحوله فوراً لرسالة كاملة تحتوي على الباركود وجميع الأكواد وروابط التركيب المباشر.\n"
            "• لتغيير اللغة اضغط /lang"
        ),
    },
    "en": {
        "lang_name": "English 🇺🇸",
        "welcome": (
            "👋 <b>Welcome to the eSIM QR, LPA & Link Converter Bot!</b>\n\n"
            "Send me any of the following:\n"
            "• 📷 <b>An eSIM QR Code image</b>\n"
            "• 📝 <b>An LPA string</b> (e.g., <code>LPA:1$rsp.truphone.com$...</code>)\n"
            "• 🔗 <b>A direct installation link</b> (Apple or Android)\n\n"
            "I will instantly generate:\n"
            "✅ A high-contrast scannable QR Code\n"
            "✅ Copyable SM-DP+ Server Address & Activation Code\n"
            "✅ Full Manual LPA Code\n"
            "✅ One-tap Direct Installation Links & Buttons for iPhone and Android"
        ),
        "choose_lang": "🌐 Choose your preferred language / اختر اللغة / 选择语言:",
        "lang_updated": "✅ Language has been set to English.",
        "esim_Caption": (
            "✅ <b>eSIM Installation Details</b>\n\n"
            "<b>SM-DP+ Server Address:</b>\n"
            "<code>{smdp}</code>\n\n"
            "<b>Activation Code:</b>\n"
            "<code>{matching_id}</code>\n"
            "{confirmation_block}\n"
            "<b>Full Manual LPA Code:</b>\n"
            "<code>{lpa}</code>\n\n"
            "📲 <b>Direct Installation Links:</b>\n"
            "- iPhone: {apple_url}\n"
            "- Android: {android_url}\n\n"
            "⚠️ Open the link in your device browser (Safari/Chrome), not inside Telegram."
        ),
        "confirmation_line": "\n<b>Confirmation Code:</b>\n<code>{code}</code>\n",
        "btn_iphone": "📲 Install on iPhone",
        "btn_android": "🤖 Install on Android",
        "btn_change_lang": "🌐 Change Language | اللغة",
        "invalid_input": (
            "❌ <b>Could not detect valid eSIM data in your message.</b>\n\n"
            "Please send:\n"
            "1️⃣ A clear eSIM QR Code image\n"
            "2️⃣ An LPA code starting with <code>LPA:1$</code>\n"
            "3️⃣ Or an Apple / Android eSIM provisioning URL."
        ),
        "qr_not_found": (
            "❌ <b>Could not decode an eSIM QR code from this image.</b>\n"
            "Please make sure the image is clear and contains a valid eSIM QR code."
        ),
        "banned_notice": "🚫 <b>You have been banned from using this bot.</b>\nReason: {reason}",
        "admin_reply_prefix": "📩 <b>Message from Bot Admin:</b>\n\n{message}",
        "help_text": (
            "📖 <b>How to use:</b>\n\n"
            "• Send an eSIM QR photo, LPA code, or direct install URL and I will convert it into a full installation card with QR, manual codes, and direct install buttons.\n"
            "• Use /lang to switch languages."
        ),
    },
    "zh": {
        "lang_name": "中文 🇨🇳",
        "welcome": (
            "👋 <b>欢迎使用 eSIM 二维码、LPA 与安装链接转换机器人！</b>\n\n"
            "您可以直接向我发送以下任意内容：\n"
            "• 📷 <b>eSIM 二维码图片 (QR Code)</b>\n"
            "• 📝 <b>LPA 文本代码</b> (例如: <code>LPA:1$rsp.truphone.com$...</code>)\n"
            "• 🔗 <b>Apple 或 Android 直接安装链接</b>\n\n"
            "我将立即为您生成完整的安装信息：\n"
            "✅ 高清可扫描二维码图片\n"
            "✅ 可一键复制的 SM-DP+ 服务器地址与激活码\n"
            "✅ 完整手动安装代码 (LPA)\n"
            "✅ iPhone 与 Android 一键安装链接及快捷按钮"
        ),
        "choose_lang": "🌐 请选择语言 / Choose Language / اختر اللغة:",
        "lang_updated": "✅ 语言已切换为中文。",
        "esim_Caption": (
            "✅ <b>eSIM 安装信息</b>\n\n"
            "<b>服务器地址 (SM-DP+):</b>\n"
            "<code>{smdp}</code>\n\n"
            "<b>激活码 (Activation Code):</b>\n"
            "<code>{matching_id}</code>\n"
            "{confirmation_block}\n"
            "<b>完整手动安装代码 (LPA):</b>\n"
            "<code>{lpa}</code>\n\n"
            "📲 <b>自动安装链接:</b>\n"
            "- iPhone: {apple_url}\n"
            "- Android: {android_url}\n\n"
            "⚠️ 请在设备自带浏览器 (Safari/Chrome) 中打开链接，不要在 Telegram 内置浏览器中打开。"
        ),
        "confirmation_line": "\n<b>确认码 (Confirmation Code):</b>\n<code>{code}</code>\n",
        "btn_iphone": "📲 在 iPhone 上安装",
        "btn_android": "🤖 在 Android 上安装",
        "btn_change_lang": "🌐 切换语言 | Language",
        "invalid_input": (
            "❌ <b>未能从您的消息中识别出有效的 eSIM 数据。</b>\n\n"
            "请确保发送以下内容之一：\n"
            "1️⃣ 清晰的 eSIM 二维码图片\n"
            "2️⃣ 以 <code>LPA:1$</code> 开头的激活代码\n"
            "3️⃣ Apple 或 Android 的 eSIM 直接安装链接。"
        ),
        "qr_not_found": (
            "❌ <b>无法从该图片中识别出有效的 eSIM 二维码。</b>\n"
            "请确保二维码清晰完整。"
        ),
        "banned_notice": "🚫 <b>抱歉，您已被禁止使用本机器人。</b>\n原因: {reason}",
        "admin_reply_prefix": "📩 <b>来自管理员的消息:</b>\n\n{message}",
        "help_text": (
            "📖 <b>使用说明:</b>\n\n"
            "• 发送 eSIM 二维码图片、LPA 代码或安装链接，即可生成包含二维码、手动代码及一键安装按钮的完整卡片。\n"
            "• 发送 /lang 可切换语言。"
        ),
    },
}


# ==============================================================================
# 2. DATABASE MANAGER (SQLite - Users, Bans, Stats, Logs)
# ==============================================================================

class Database:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    language TEXT DEFAULT 'ar',
                    is_banned INTEGER DEFAULT 0,
                    ban_reason TEXT DEFAULT '',
                    esim_count INTEGER DEFAULT 0,
                    joined_at TEXT,
                    last_active TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    smdp TEXT,
                    matching_id TEXT,
                    lpa TEXT,
                    source_type TEXT,
                    created_at TEXT
                )
                """
            )
            conn.commit()

    def upsert_user(
        self, user_id: int, username: Optional[str], full_name: str
    ) -> sqlite3.Row:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        with self._get_conn() as conn:
            cur = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            existing = cur.fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO users (user_id, username, full_name, language, is_banned, ban_reason, esim_count, joined_at, last_active)
                    VALUES (?, ?, ?, 'ar', 0, '', 0, ?, ?)
                    """,
                    (user_id, username or "", full_name or "", now, now),
                )
            else:
                conn.execute(
                    """
                    UPDATE users
                    SET username = ?, full_name = ?, last_active = ?
                    WHERE user_id = ?
                    """,
                    (username or "", full_name or "", now, user_id),
                )
            conn.commit()
            return conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()

    def get_user(self, user_id: int) -> Optional[sqlite3.Row]:
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()

    def get_lang(self, user_id: int) -> str:
        row = self.get_user(user_id)
        if row and row["language"] in TRANSLATIONS:
            return row["language"]
        return "ar"

    def set_lang(self, user_id: int, lang: str) -> None:
        if lang not in TRANSLATIONS:
            lang = "ar"
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id)
            )
            conn.commit()

    def ban_user(self, user_id: int, reason: str = "مخالفة شروط الاستخدام / Policy violation") -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        with self._get_conn() as conn:
            cur = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
            if cur.fetchone() is None:
                conn.execute(
                    """
                    INSERT INTO users (user_id, username, full_name, language, is_banned, ban_reason, esim_count, joined_at, last_active)
                    VALUES (?, '', 'Unknown', 'ar', 1, ?, 0, ?, ?)
                    """,
                    (user_id, reason, now, now),
                )
            else:
                conn.execute(
                    "UPDATE users SET is_banned = 1, ban_reason = ? WHERE user_id = ?",
                    (reason, user_id),
                )
            conn.commit()

    def unban_user(self, user_id: int) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE users SET is_banned = 0, ban_reason = '' WHERE user_id = ?",
                (user_id,),
            )
            conn.commit()
            return cur.rowcount > 0

    def record_conversion(
        self, user_id: int, smdp: str, matching_id: str, lpa: str, source_type: str
    ) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO conversions (user_id, smdp, matching_id, lpa, source_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, smdp, matching_id, lpa, source_type, now),
            )
            conn.execute(
                "UPDATE users SET esim_count = esim_count + 1, last_active = ? WHERE user_id = ?",
                (now, user_id),
            )
            conn.commit()

    def get_stats(self) -> Dict[str, int]:
        with self._get_conn() as conn:
            total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            banned_users = conn.execute(
                "SELECT COUNT(*) FROM users WHERE is_banned = 1"
            ).fetchone()[0]
            active_users = total_users - banned_users
            total_conversions = conn.execute(
                "SELECT COUNT(*) FROM conversions"
            ).fetchone()[0]
            ar_users = conn.execute(
                "SELECT COUNT(*) FROM users WHERE language = 'ar'"
            ).fetchone()[0]
            en_users = conn.execute(
                "SELECT COUNT(*) FROM users WHERE language = 'en'"
            ).fetchone()[0]
            zh_users = conn.execute(
                "SELECT COUNT(*) FROM users WHERE language = 'zh'"
            ).fetchone()[0]
            return {
                "total_users": total_users,
                "active_users": active_users,
                "banned_users": banned_users,
                "total_conversions": total_conversions,
                "ar_users": ar_users,
                "en_users": en_users,
                "zh_users": zh_users,
            }

    def get_all_users(self, include_banned: bool = True) -> List[sqlite3.Row]:
        with self._get_conn() as conn:
            if include_banned:
                return conn.execute(
                    "SELECT * FROM users ORDER BY joined_at DESC"
                ).fetchall()
            return conn.execute(
                "SELECT * FROM users WHERE is_banned = 0 ORDER BY joined_at DESC"
            ).fetchall()

    def get_banned_users(self) -> List[sqlite3.Row]:
        with self._get_conn() as conn:
            return conn.execute(
                "SELECT * FROM users WHERE is_banned = 1 ORDER BY last_active DESC"
            ).fetchall()


# ==============================================================================
# 3. eSIM PARSER, QR DECODER & QR GENERATOR
# ==============================================================================

class EsimData:
    def __init__(
        self,
        smdp: str,
        matching_id: str,
        lpa: str,
        confirmation_code: str = "",
        source_type: str = "text",
    ):
        self.smdp = smdp.strip()
        self.matching_id = matching_id.strip()
        self.lpa = lpa.strip()
        self.confirmation_code = confirmation_code.strip()
        self.source_type = source_type

    @property
    def encoded_lpa(self) -> str:
        # Encode ':' as %3A and '$' as %24 matching the screenshot format
        return quote(self.lpa, safe="-_.")

    @property
    def apple_url(self) -> str:
        return f"https://esimsetup.apple.com/esim_qrcode_provisioning?carddata={self.encoded_lpa}"

    @property
    def android_url(self) -> str:
        return f"https://esimsetup.android.com/esim_qrcode_provisioning?carddata={self.encoded_lpa}"


def parse_esim_payload(raw_text: str, source_type: str = "text") -> Optional[EsimData]:
    """
    Parses any eSIM representation:
    1. Direct Apple/Android installation link:
       https://esimsetup.apple.com/esim_qrcode_provisioning?carddata=LPA:1$...
       https://esimsetup.android.com/esim_qrcode_provisioning?carddata=LPA%3A1%24...
    2. Standard LPA string:
       LPA:1$rsp.truphone.com$QRF-SPEEDTEST-PMRDGIR2EARDCIT5
       or 1$smdp.address$matching_id
    3. Multi-line text containing SM-DP+ Address and Activation Code
    """
    if not raw_text:
        return None

    text = raw_text.strip()

    # Step 1: Check for URL with carddata=... parameter
    url_match = re.search(
        r"https?://[^\s<>\"']+(?:carddata=|data=)([^\s&<>\"']+)", text, re.IGNORECASE
    )
    if url_match:
        decoded_carddata = unquote(unquote(url_match.group(1)))
        parsed = _parse_lpa_string(decoded_carddata, source_type="link")
        if parsed:
            return parsed

    # Also check if any URL in the text has query params
    if "http://" in text.lower() or "https://" in text.lower():
        for token in re.split(r"\s+", text):
            if token.lower().startswith(("http://", "https://")):
                try:
                    parsed_url = urlparse(token)
                    qs = parse_qs(parsed_url.query)
                    for key in ("carddata", "data", "lpa", "code"):
                        if key in qs and qs[key]:
                            candidate = unquote(unquote(qs[key][0]))
                            parsed = _parse_lpa_string(candidate, source_type="link")
                            if parsed:
                                return parsed
                except Exception:
                    pass

    # Step 2: Check for standard LPA:1$... or 1$... inside text
    unquoted_text = unquote(text)
    for candidate_text in (text, unquoted_text):
        parsed = _parse_lpa_string(candidate_text, source_type=source_type)
        if parsed:
            return parsed

    # Step 3: Check for structured two-part text (SM-DP+ + Activation Code)
    smdp_match = re.search(
        r"(?:SM-DP\+|Server|سيرفر|عنوان السيرفر|服务器)[^\n:：]*[:：]\s*([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
        text,
        re.IGNORECASE,
    )
    act_match = re.search(
        r"(?:Activation|Matching|كود التفعيل|التفعيل|激活码)[^\n:：]*[:：]\s*([A-Za-z0-9\-_$.]+)",
        text,
        re.IGNORECASE,
    )
    if smdp_match and act_match:
        smdp = smdp_match.group(1).strip()
        matching_id = act_match.group(1).strip()
        lpa = f"LPA:1${smdp}${matching_id}"
        return EsimData(smdp=smdp, matching_id=matching_id, lpa=lpa, source_type=source_type)

    return None


def _parse_lpa_string(text: str, source_type: str = "text") -> Optional[EsimData]:
    # Look for LPA:1$... pattern
    lpa_regex = re.compile(
        r"(?:LPA\s*:\s*)?1\$([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\$([^\s\"'<>]+)",
        re.IGNORECASE,
    )
    match = lpa_regex.search(text)
    if not match:
        return None

    smdp = match.group(1).strip()
    remainder = match.group(2).strip()
    parts = remainder.split("$")
    matching_id = parts[0].strip()
    if not matching_id:
        return None

    confirmation_code = ""
    if len(parts) >= 3 and parts[2].strip():
        confirmation_code = parts[2].strip()
    elif len(parts) == 2 and parts[1].strip() and not parts[1].startswith("2.999"):
        confirmation_code = parts[1].strip()

    # Reconstruct clean canonical LPA string
    if len(parts) > 1 and any(p.strip() for p in parts[1:]):
        clean_lpa = f"LPA:1${smdp}${remainder}"
    else:
        clean_lpa = f"LPA:1${smdp}${matching_id}"

    return EsimData(
        smdp=smdp,
        matching_id=matching_id,
        lpa=clean_lpa,
        confirmation_code=confirmation_code,
        source_type=source_type,
    )


def decode_qr_from_image_bytes(image_bytes: bytes) -> Optional[str]:
    """
    Decodes QR code from image bytes using multiple OpenCV preprocessing passes
    (standard, grayscale, Otsu threshold, adaptive threshold, inverted for dark mode,
    upscaled, downscaled, and padded) to handle screenshots and cropped QR codes reliably.
    """
    np_arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if img is None:
        return None

    detector = cv2.QRCodeDetector()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Create candidate images for robust detection
    candidates = [
        img,
        gray,
        cv2.bitwise_not(gray),  # Inverted (handles dark-mode QR codes)
        cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1],
        cv2.threshold(cv2.bitwise_not(gray), 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1],
        cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, 5
        ),
        cv2.copyMakeBorder(gray, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255),
    ]

    # Also try cropping bright white regions (such as a QR card inside a phone screenshot)
    _, thresh_white = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh_white, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        x, y, cw, ch = cv2.boundingRect(cnt)
        if cw > 120 and ch > 120 and 0.6 <= (cw / float(ch)) <= 1.4:
            crop = gray[max(0, y - 10):min(gray.shape[0], y + ch + 10), max(0, x - 10):min(gray.shape[1], x + cw + 10)]
            if crop.size > 0:
                candidates.insert(0, crop)
                candidates.insert(1, cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1])

    # Add scaled versions if image is very large or very small
    h, w = gray.shape[:2]
    if max(h, w) > 1000:
        scale = 800.0 / max(h, w)
        resized = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        candidates.append(resized)
        candidates.append(cv2.threshold(resized, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1])
    elif min(h, w) < 350:
        resized = cv2.resize(gray, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
        candidates.append(resized)

    for candidate in candidates:
        try:
            data, _, _ = detector.detectAndDecode(candidate)
            if data and data.strip():
                return data.strip()
            retval, decoded_info, _, _ = detector.detectAndDecodeMulti(candidate)
            if retval and decoded_info:
                for item in decoded_info:
                    if item and item.strip():
                        return item.strip()
        except Exception:
            continue

    return None


def generate_qr_png_bytes(lpa_string: str) -> bytes:
    """
    Generates a clean, high-contrast QR Code PNG with generous quiet zone
    matching the screenshot style.
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=4,
    )
    qr.add_data(lpa_string)
    qr.make(fit=True)
    img: Image.Image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()


def format_esim_response(esim: EsimData, lang: str = "ar") -> Tuple[str, InlineKeyboardMarkup]:
    """
    Builds the localized HTML caption and InlineKeyboardMarkup with direct install buttons.
    """
    t = TRANSLATIONS.get(lang, TRANSLATIONS["ar"])
    confirmation_block = ""
    if esim.confirmation_code:
        confirmation_block = t["confirmation_line"].format(
            code=html.escape(esim.confirmation_code)
        )

    caption = t["esim_Caption"].format(
        smdp=html.escape(esim.smdp),
        matching_id=html.escape(esim.matching_id),
        confirmation_block=confirmation_block,
        lpa=html.escape(esim.lpa),
        apple_url=esim.apple_url,
        android_url=esim.android_url,
    )

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(text=t["btn_iphone"], url=esim.apple_url)],
            [InlineKeyboardButton(text=t["btn_android"], url=esim.android_url)],
        ]
    )
    return caption, keyboard


# ==============================================================================
# 4. CONFIGURATION & HOSTING SETUP (ENV + CONFIG.JSON + WEB/CLI PROMPT)
# ==============================================================================

def load_or_prompt_config() -> Tuple[str, int]:
    """
    Loads BOT_TOKEN and OWNER_ID from:
    1. Environment variables (BOT_TOKEN, OWNER_ID / ADMIN_ID)
    2. Local config.json file
    3. Interactive CLI prompt (if running in an interactive terminal)
    4. Embedded Web Setup Server (if running on a cloud PaaS with PORT set and no TTY)
    """
    bot_token = os.environ.get("BOT_TOKEN", "").strip()
    owner_id_str = (
        os.environ.get("OWNER_ID", "").strip()
        or os.environ.get("ADMIN_ID", "").strip()
    )

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if not bot_token:
                    bot_token = str(saved.get("BOT_TOKEN", "")).strip()
                if not owner_id_str:
                    owner_id_str = str(saved.get("OWNER_ID", "")).strip()
        except Exception as e:
            logger.warning(f"Failed to read {CONFIG_FILE}: {e}")

    if bot_token and owner_id_str and owner_id_str.lstrip("-").isdigit():
        return bot_token, int(owner_id_str)

    # If interactive terminal is available, ask the user directly in console
    if sys.stdin and sys.stdin.isatty():
        print("\n" + "=" * 65)
        print("🤖 eSIM Telegram Bot - First-Time Setup")
        print("=" * 65)
        while not bot_token:
            bot_token = input("👉 Enter your Telegram Bot Token (from @BotFather): ").strip()
        while not (owner_id_str and owner_id_str.lstrip("-").isdigit()):
            owner_id_str = input("👉 Enter your Owner Telegram User ID (e.g. 123456789): ").strip()

        save_config(bot_token, int(owner_id_str))
        print(f"✅ Configuration saved to {CONFIG_FILE}!\n")
        return bot_token, int(owner_id_str)

    # If running on a non-interactive cloud host (e.g., Render/Railway/Heroku) without env vars yet,
    # wait for credentials via the Web Setup UI on $PORT
    port = int(os.environ.get("PORT", "8080"))
    logger.info(
        f"No BOT_TOKEN / OWNER_ID found in environment. Starting Web Setup Page on port {port}..."
    )
    return wait_for_web_setup(port)


def save_config(bot_token: str, owner_id: int) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"BOT_TOKEN": bot_token, "OWNER_ID": owner_id}, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save {CONFIG_FILE}: {e}")


class KeepAliveAndSetupHandler(BaseHTTPRequestHandler):
    setup_result: Dict[str, str] = {}
    setup_event: Optional[threading.Event] = None
    bot_running: bool = False

    def log_message(self, format: str, *args) -> None:
        return  # Keep HTTP logs quiet

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"status": "ok", "bot_connected": self.bot_running}).encode("utf-8")
            )
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if self.bot_running:
            html_page = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>eSIM Bot Status</title>
<style>body{font-family:system-ui,sans-serif;background:#0f172a;color:#f8fafc;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{background:#1e293b;padding:2rem 2.5rem;border-radius:16px;box-shadow:0 10px 25px rgba(0,0,0,.4);max-width:460px;text-align:center}
.badge{display:inline-block;background:#10b981;color:#052e16;font-weight:700;padding:6px 14px;border-radius:999px;margin-bottom:1rem}</style></head>
<body><div class="card"><div class="badge">● ONLINE</div><h2>eSIM Telegram Bot is Running</h2>
<p>Supports Arabic (Default), English &amp; Chinese.</p></div></body></html>"""
        else:
            html_page = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Connect eSIM Telegram Bot</title>
<style>body{font-family:system-ui,sans-serif;background:#0f172a;color:#f8fafc;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
.card{background:#1e293b;padding:2rem 2.5rem;border-radius:16px;box-shadow:0 10px 25px rgba(0,0,0,.4);width:100%;max-width:440px}
h2{margin-top:0;color:#38bdf8}label{display:block;margin:1rem 0 .4rem;font-size:.9rem;color:#cbd5e1}
input{width:100%;padding:.75rem;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#fff;box-sizing:border-box}
button{margin-top:1.5rem;width:100%;padding:.85rem;background:#0284c7;color:#fff;border:none;border-radius:8px;font-weight:700;cursor:pointer;font-size:1rem}
button:hover{background:#0369a1}</style></head>
<body><div class="card"><h2>🤖 Connect eSIM Bot</h2>
<p style="color:#94a3b8;font-size:.9rem">Enter your Telegram Bot Token and Owner Telegram ID to launch the bot.</p>
<form method="POST" action="/setup">
<label>Telegram Bot Token (@BotFather)</label>
<input type="text" name="bot_token" placeholder="123456789:ABCdefGHIjklMNOpqrSTUvwxYZ" required>
<label>Owner Telegram User ID</label>
<input type="number" name="owner_id" placeholder="123456789" required>
<button type="submit">Save &amp; Connect Bot 🚀</button>
</form></div></body></html>"""
        self.wfile.write(html_page.encode("utf-8"))

    def do_POST(self):
        if self.path == "/setup" and not self.bot_running:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            params = parse_qs(body)
            token = params.get("bot_token", [""])[0].strip()
            owner = params.get("owner_id", [""])[0].strip()
            if token and owner.lstrip("-").isdigit():
                KeepAliveAndSetupHandler.setup_result["BOT_TOKEN"] = token
                KeepAliveAndSetupHandler.setup_result["OWNER_ID"] = owner
                KeepAliveAndSetupHandler.bot_running = True
                if KeepAliveAndSetupHandler.setup_event:
                    KeepAliveAndSetupHandler.setup_event.set()
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
        self.send_response(400)
        self.end_headers()
        self.wfile.write(b"Invalid token or owner ID.")


def start_background_http_server(port: int) -> HTTPServer:
    server = HTTPServer(("0.0.0.0", port), KeepAliveAndSetupHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"HTTP health/status server listening on 0.0.0.0:{port}")
    return server


def wait_for_web_setup(port: int) -> Tuple[str, int]:
    event = threading.Event()
    KeepAliveAndSetupHandler.setup_event = event
    KeepAliveAndSetupHandler.bot_running = False
    start_background_http_server(port)
    event.wait()
    token = KeepAliveAndSetupHandler.setup_result["BOT_TOKEN"]
    owner_id = int(KeepAliveAndSetupHandler.setup_result["OWNER_ID"])
    save_config(token, owner_id)
    return token, owner_id


# ==============================================================================
# 5. TELEGRAM BOT HANDLERS & ADMIN PANEL
# ==============================================================================

class EsimBotApp:
    def __init__(self, bot_token: str, owner_id: int, db: Database):
        self.bot_token = bot_token
        self.owner_id = owner_id
        self.db = db
        # Track admin interactive state: {admin_user_id: {"mode": ..., "target_id": ...}}
        self.admin_state: Dict[int, Dict[str, object]] = {}
        # Map forwarded message_id in owner chat -> target user_id for easy native reply
        self.forwarded_map: Dict[int, int] = {}

    def is_admin(self, user_id: int) -> bool:
        return user_id == self.owner_id

    async def register_and_check_ban(self, update: Update) -> Optional[str]:
        """
        Registers/updates user in DB.
        Returns the user's language if allowed, or None if the user is banned.
        """
        user = update.effective_user
        if not user:
            return "ar"
        full_name = " ".join(filter(None, [user.first_name, user.last_name])) or "User"
        row = self.db.upsert_user(user.id, user.username, full_name)
        lang = row["language"] if row["language"] in TRANSLATIONS else "ar"

        if row["is_banned"] and not self.is_admin(user.id):
            reason = row["ban_reason"] or "مخالفة شروط الاستخدام / Policy violation"
            if update.effective_message:
                await update.effective_message.reply_text(
                    TRANSLATIONS[lang]["banned_notice"].format(reason=html.escape(reason)),
                    parse_mode=ParseMode.HTML,
                )
            return None
        return lang

    def get_language_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("العربية 🇸🇦", callback_data="lang:ar"),
                    InlineKeyboardButton("English 🇺🇸", callback_data="lang:en"),
                    InlineKeyboardButton("中文 🇨🇳", callback_data="lang:zh"),
                ]
            ]
        )

    def get_admin_panel_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("📊 إحصائيات البوت | Stats", callback_data="adm:stats"),
                    InlineKeyboardButton("👥 المستخدمين | Users", callback_data="adm:users:0"),
                ],
                [
                    InlineKeyboardButton("📢 إذاعة للجميع | Broadcast", callback_data="adm:broadcast"),
                    InlineKeyboardButton("✉️ رسالة لمستخدم | Send Msg", callback_data="adm:send"),
                ],
                [
                    InlineKeyboardButton("🚫 حظر مستخدم | Ban", callback_data="adm:ban"),
                    InlineKeyboardButton("✅ فك حظر | Unban", callback_data="adm:unban"),
                ],
                [
                    InlineKeyboardButton("🚫 قائمة المحظورين | Banned List", callback_data="adm:banned_list"),
                    InlineKeyboardButton("📥 تصدير CSV | Export Users", callback_data="adm:export_csv"),
                ],
                [
                    InlineKeyboardButton("📌 تثبيت أوامر الأدمن | Pin Commands", callback_data="adm:pin_help"),
                ],
            ]
        )

    def get_admin_help_text(self) -> str:
        return (
            "🛠️ <b>لوحة وأوامر الأدمن | Admin Control Panel</b>\n\n"
            "• <code>/admin</code> — فتح لوحة التحكم التفاعلية بالأزرار\n"
            "• <code>/ban ID سبب</code> — حظر مستخدم مع ذكر السبب\n"
            "• <code>/unban ID</code> — إلغاء حظر مستخدم\n"
            "• <code>/send ID الرسالة</code> — إرسال رسالة خاصة لمستخدم\n"
            "• <code>/broadcast الرسالة</code> — إرسال رسالة عامة لجميع المستخدمين (أو بالرد على أي رسالة بـ /broadcast)\n"
            "• <code>/stats</code> — عرض إحصائيات البوت التفصيلية\n"
            "• <code>/users</code> — عرض قائمة المستخدمين وتصديرها\n\n"
            "💡 <i>يمكنك أيضاً الرد مباشرة (Reply) على أي رسالة محولة من مستخدم وسيقوم البوت بإيصال ردك إليه فوراً!</i>"
        )

    # --------------------------------------------------------------------------
    # User Commands (/start, /lang, /help)
    # --------------------------------------------------------------------------

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        lang = await self.register_and_check_ban(update)
        if not lang:
            return
        t = TRANSLATIONS[lang]
        buttons = [
            [
                InlineKeyboardButton("العربية 🇸🇦", callback_data="lang:ar"),
                InlineKeyboardButton("English 🇺🇸", callback_data="lang:en"),
                InlineKeyboardButton("中文 🇨🇳", callback_data="lang:zh"),
            ]
        ]
        if self.is_admin(update.effective_user.id):
            buttons.append(
                [InlineKeyboardButton("🛠️ لوحة تحكم الأدمن | Admin Panel", callback_data="adm:home")]
            )
        await update.message.reply_text(
            t["welcome"],
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

        # Notify owner when a non-admin starts the bot
        if not self.is_admin(update.effective_user.id):
            await self.forward_to_owner(update, context, note="🚀 بدأ استخدام البوت (/start)")

    async def cmd_lang(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        lang = await self.register_and_check_ban(update)
        if not lang:
            return
        await update.message.reply_text(
            TRANSLATIONS[lang]["choose_lang"],
            reply_markup=self.get_language_keyboard(),
        )

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        lang = await self.register_and_check_ban(update)
        if not lang:
            return
        text = TRANSLATIONS[lang]["help_text"]
        if self.is_admin(update.effective_user.id):
            text += "\n\n" + self.get_admin_help_text()
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    # --------------------------------------------------------------------------
    # Admin Slash Commands (/admin, /ban, /unban, /send, /broadcast, /stats, /users)
    # --------------------------------------------------------------------------

    async def cmd_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.is_admin(update.effective_user.id):
            return
        self.admin_state.pop(update.effective_user.id, None)
        await update.message.reply_text(
            self.get_admin_help_text(),
            parse_mode=ParseMode.HTML,
            reply_markup=self.get_admin_panel_keyboard(),
        )

    async def cmd_ban(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.is_admin(update.effective_user.id):
            return
        if not context.args:
            await update.message.reply_text(
                "⚠️ الاستخدام: <code>/ban USER_ID [السبب]</code>\nمثال: <code>/ban 123456789 إزعاج</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        target_str = context.args[0].strip()
        if not target_str.isdigit():
            await update.message.reply_text("❌ رقم الـ ID يجب أن يكون أرقاماً فقط.")
            return
        target_id = int(target_str)
        if target_id == self.owner_id:
            await update.message.reply_text("❌ لا يمكنك حظر مالك البوت!")
            return
        reason = " ".join(context.args[1:]).strip() or "مخالفة شروط الاستخدام / Policy violation"
        self.db.ban_user(target_id, reason)
        await update.message.reply_text(
            f"🚫 تم حظر المستخدم <code>{target_id}</code> بنجاح.\nالسبب: {html.escape(reason)}",
            parse_mode=ParseMode.HTML,
        )
        try:
            user_lang = self.db.get_lang(target_id)
            await context.bot.send_message(
                chat_id=target_id,
                text=TRANSLATIONS[user_lang]["banned_notice"].format(reason=html.escape(reason)),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    async def cmd_unban(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.is_admin(update.effective_user.id):
            return
        if not context.args or not context.args[0].strip().isdigit():
            await update.message.reply_text(
                "⚠️ الاستخدام: <code>/unban USER_ID</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        target_id = int(context.args[0].strip())
        self.db.unban_user(target_id)
        await update.message.reply_text(
            f"✅ تم إلغاء حظر المستخدم <code>{target_id}</code> بنجاح.",
            parse_mode=ParseMode.HTML,
        )

    async def cmd_send(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.is_admin(update.effective_user.id):
            return
        if len(context.args) < 2 or not context.args[0].strip().isdigit():
            await update.message.reply_text(
                "⚠️ الاستخدام: <code>/send USER_ID الرسالة</code>\nمثال: <code>/send 123456789 مرحباً بك</code>",
                parse_mode=ParseMode.HTML,
            )
            return
        target_id = int(context.args[0].strip())
        msg_body = update.message.text.split(None, 2)[2]
        await self._send_message_to_user(update, context, target_id, msg_body)

    async def _send_message_to_user(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_id: int,
        msg_body: str,
    ) -> None:
        user_lang = self.db.get_lang(target_id)
        formatted = TRANSLATIONS[user_lang]["admin_reply_prefix"].format(
            message=html.escape(msg_body)
        )
        try:
            await context.bot.send_message(
                chat_id=target_id, text=formatted, parse_mode=ParseMode.HTML
            )
            await update.effective_message.reply_text(
                f"✅ تم إرسال الرسالة إلى المستخدم <code>{target_id}</code> بنجاح.",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            await update.effective_message.reply_text(
                f"❌ تعذر إرسال الرسالة إلى <code>{target_id}</code>: {html.escape(str(e))}",
                parse_mode=ParseMode.HTML,
            )

    async def cmd_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.is_admin(update.effective_user.id):
            return

        users = self.db.get_all_users(include_banned=False)
        if update.message.reply_to_message:
            sent, failed = 0, 0
            status_msg = await update.message.reply_text(
                f"⏳ جاري إرسال الإذاعة إلى {len(users)} مستخدم..."
            )
            for u in users:
                try:
                    await context.bot.copy_message(
                        chat_id=u["user_id"],
                        from_chat_id=update.effective_chat.id,
                        message_id=update.message.reply_to_message.message_id,
                    )
                    sent += 1
                    await asyncio.sleep(0.04)
                except Exception:
                    failed += 1
            await status_msg.edit_text(
                f"✅ <b>اكتملت الإذاعة الجماعية!</b>\n\n"
                f"• تم الإرسال بنجاح: <b>{sent}</b>\n"
                f"• فشل الإرسال: <b>{failed}</b>",
                parse_mode=ParseMode.HTML,
            )
            return

        if not context.args:
            await update.message.reply_text(
                "⚠️ الاستخدام:\n"
                "• <code>/broadcast نص الرسالة الجماعية</code>\n"
                "• أو قم بالرد (Reply) على أي رسالة/صورة بـ <code>/broadcast</code> لإرسالها لجميع المستخدمين.",
                parse_mode=ParseMode.HTML,
            )
            return

        broadcast_text = update.message.text.split(None, 1)[1]
        await self._execute_text_broadcast(update, context, broadcast_text)

    async def _execute_text_broadcast(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, broadcast_text: str
    ) -> None:
        users = self.db.get_all_users(include_banned=False)
        sent, failed = 0, 0
        status_msg = await update.effective_message.reply_text(
            f"⏳ جاري إرسال الرسالة الجماعية إلى {len(users)} مستخدم..."
        )
        for u in users:
            try:
                await context.bot.send_message(
                    chat_id=u["user_id"],
                    text=f"📢 <b>إشعار عام | Announcement:</b>\n\n{html.escape(broadcast_text)}",
                    parse_mode=ParseMode.HTML,
                )
                sent += 1
                await asyncio.sleep(0.04)
            except Exception:
                failed += 1
        await status_msg.edit_text(
            f"✅ <b>اكتملت الإذاعة الجماعية!</b>\n\n"
            f"• إجمالي المستلمين: <b>{sent}</b>\n"
            f"• فشل الإرسال: <b>{failed}</b>",
            parse_mode=ParseMode.HTML,
        )

    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.is_admin(update.effective_user.id):
            return
        text = self._build_stats_text()
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=self.get_admin_panel_keyboard(),
        )

    def _build_stats_text(self) -> str:
        s = self.db.get_stats()
        return (
            "📊 <b>إحصائيات البوت | Bot Statistics</b>\n\n"
            f"👥 <b>إجمالي المستخدمين:</b> <code>{s['total_users']}</code>\n"
            f"✅ <b>المستخدمين النشطين:</b> <code>{s['active_users']}</code>\n"
            f"🚫 <b>المحظورين:</b> <code>{s['banned_users']}</code>\n"
            f"🔄 <b>إجمالي عمليات تحويل eSIM:</b> <code>{s['total_conversions']}</code>\n\n"
            "🌐 <b>توزيع اللغات:</b>\n"
            f"• العربية 🇸🇦: <code>{s['ar_users']}</code>\n"
            f"• English 🇺🇸: <code>{s['en_users']}</code>\n"
            f"• 中文 🇨🇳: <code>{s['zh_users']}</code>"
        )

    async def cmd_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.is_admin(update.effective_user.id):
            return
        text, markup = self._build_users_page(page=0)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)

    def _build_users_page(self, page: int = 0, page_size: int = 10) -> Tuple[str, InlineKeyboardMarkup]:
        users = self.db.get_all_users(include_banned=True)
        total = len(users)
        start = page * page_size
        end = start + page_size
        slice_users = users[start:end]

        lines = [f"👥 <b>قائمة مستخدمي البوت ({total}):</b>\n"]
        if not slice_users:
            lines.append("لا يوجد مستخدمين حتى الآن.")
        else:
            for idx, u in enumerate(slice_users, start=start + 1):
                status = "🚫" if u["is_banned"] else "✅"
                uname = f"@{u['username']}" if u["username"] else "بدون معرف"
                lines.append(
                    f"{idx}. {status} <b>{html.escape(u['full_name'])}</b> ({html.escape(uname)})\n"
                    f"   ID: <code>{u['user_id']}</code> | اللغة: <code>{u['language']}</code> | الشرائح: <code>{u['esim_count']}</code>"
                )

        nav_buttons = []
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton("⬅️ السابق", callback_data=f"adm:users:{page - 1}")
            )
        if end < total:
            nav_buttons.append(
                InlineKeyboardButton("التالي ➡️", callback_data=f"adm:users:{page + 1}")
            )

        rows = []
        if nav_buttons:
            rows.append(nav_buttons)
        rows.append([InlineKeyboardButton("📥 تحميل ملف المستخدمين CSV", callback_data="adm:export_csv")])
        rows.append([InlineKeyboardButton("🔙 العودة للوحة الأدمن", callback_data="adm:home")])
        return "\n".join(lines), InlineKeyboardMarkup(rows)

    # --------------------------------------------------------------------------
    # Callback Query Handler (Language Switching & Admin Panel Actions)
    # --------------------------------------------------------------------------

    async def on_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query or not query.data:
            return
        user = query.from_user
        data = query.data

        # Language Selection
        if data.startswith("lang:"):
            new_lang = data.split(":", 1)[1]
            self.db.upsert_user(
                user.id,
                user.username,
                " ".join(filter(None, [user.first_name, user.last_name])) or "User",
            )
            self.db.set_lang(user.id, new_lang)
            t = TRANSLATIONS.get(new_lang, TRANSLATIONS["ar"])
            await query.answer(t["lang_updated"])
            buttons = [
                [
                    InlineKeyboardButton("العربية 🇸🇦", callback_data="lang:ar"),
                    InlineKeyboardButton("English 🇺🇸", callback_data="lang:en"),
                    InlineKeyboardButton("中文 🇨🇳", callback_data="lang:zh"),
                ]
            ]
            if self.is_admin(user.id):
                buttons.append(
                    [InlineKeyboardButton("🛠️ لوحة تحكم الأدمن | Admin Panel", callback_data="adm:home")]
                )
            try:
                await query.edit_message_text(
                    t["welcome"],
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(buttons),
                )
            except BadRequest:
                await query.message.reply_text(
                    t["welcome"],
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(buttons),
                )
            return

        # Admin-only callbacks
        if data.startswith("adm:"):
            if not self.is_admin(user.id):
                await query.answer("⛔ هذه اللوحة مخصصة للأدمن فقط.", show_alert=True)
                return

            parts = data.split(":")
            action = parts[1]

            if action == "home":
                self.admin_state.pop(user.id, None)
                await query.answer()
                await query.edit_message_text(
                    self.get_admin_help_text(),
                    parse_mode=ParseMode.HTML,
                    reply_markup=self.get_admin_panel_keyboard(),
                )

            elif action == "stats":
                await query.answer()
                await query.edit_message_text(
                    self._build_stats_text(),
                    parse_mode=ParseMode.HTML,
                    reply_markup=self.get_admin_panel_keyboard(),
                )

            elif action == "users":
                page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
                text, markup = self._build_users_page(page=page)
                await query.answer()
                await query.edit_message_text(
                    text, parse_mode=ParseMode.HTML, reply_markup=markup
                )

            elif action == "banned_list":
                banned = self.db.get_banned_users()
                await query.answer()
                if not banned:
                    await query.edit_message_text(
                        "✅ لا يوجد أي مستخدم محظور حالياً.",
                        reply_markup=InlineKeyboardMarkup(
                            [[InlineKeyboardButton("🔙 رجوع", callback_data="adm:home")]]
                        ),
                    )
                    return
                lines = ["🚫 <b>قائمة المستخدمين المحظورين:</b>\n"]
                kb = []
                for b in banned[:20]:
                    lines.append(
                        f"• <code>{b['user_id']}</code> — {html.escape(b['full_name'])} (السبب: {html.escape(b['ban_reason'])})"
                    )
                    kb.append(
                        [
                            InlineKeyboardButton(
                                f"✅ فك حظر {b['user_id']}",
                                callback_data=f"adm:quick_unban:{b['user_id']}",
                            )
                        ]
                    )
                kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm:home")])
                await query.edit_message_text(
                    "\n".join(lines),
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(kb),
                )

            elif action == "quick_unban" and len(parts) > 2:
                target_id = int(parts[2])
                self.db.unban_user(target_id)
                await query.answer(f"✅ تم فك حظر {target_id}", show_alert=True)
                await query.edit_message_text(
                    f"✅ تم إلغاء حظر المستخدم <code>{target_id}</code>.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=self.get_admin_panel_keyboard(),
                )

            elif action == "quick_ban" and len(parts) > 2:
                target_id = int(parts[2])
                if target_id == self.owner_id:
                    await query.answer("❌ لا يمكن حظر المالك", show_alert=True)
                    return
                self.db.ban_user(target_id, "حظر من قبل الإدارة / Banned by Admin")
                await query.answer(f"🚫 تم حظر {target_id}", show_alert=True)
                await query.message.reply_text(
                    f"🚫 تم حظر المستخدم <code>{target_id}</code>.",
                    parse_mode=ParseMode.HTML,
                )

            elif action == "quick_reply" and len(parts) > 2:
                target_id = int(parts[2])
                self.admin_state[user.id] = {"mode": "reply_user", "target_id": target_id}
                await query.answer()
                await query.message.reply_text(
                    f"✉️ أرسل الآن الرسالة التي تريد إرسالها للمستخدم <code>{target_id}</code> (أو أرسل /cancel للإلغاء):",
                    parse_mode=ParseMode.HTML,
                )

            elif action == "broadcast":
                self.admin_state[user.id] = {"mode": "broadcast"}
                await query.answer()
                await query.message.reply_text(
                    "📢 <b>وضع الإذاعة الجماعية:</b>\n"
                    "أرسل الآن أي رسالة (نص، صورة، ملف، إلخ) ليتم إرسالها إلى جميع مستخدمي البوت، أو أرسل /cancel للإلغاء.",
                    parse_mode=ParseMode.HTML,
                )

            elif action == "send":
                self.admin_state[user.id] = {"mode": "send_wait_id"}
                await query.answer()
                await query.message.reply_text(
                    "✉️ أرسل الآن <b>الـ ID الخاص بالمستخدم</b> الذي تريد مراسلته (أو أرسل /cancel للإلغاء):",
                    parse_mode=ParseMode.HTML,
                )

            elif action == "ban":
                self.admin_state[user.id] = {"mode": "ban_wait_id"}
                await query.answer()
                await query.message.reply_text(
                    "🚫 أرسل الآن <b>رقم ID المستخدم</b> متبوعاً بسبب الحظر (مثال: <code>123456789 سبام</code>) أو /cancel للإلغاء:",
                    parse_mode=ParseMode.HTML,
                )

            elif action == "unban":
                self.admin_state[user.id] = {"mode": "unban_wait_id"}
                await query.answer()
                await query.message.reply_text(
                    "✅ أرسل الآن <b>رقم ID المستخدم</b> لإلغاء حظره (أو /cancel للإلغاء):",
                    parse_mode=ParseMode.HTML,
                )

            elif action == "export_csv":
                await query.answer("📥 جاري تجهيز ملف المستخدمين...")
                users = self.db.get_all_users(include_banned=True)
                sio = io.StringIO()
                writer = csv.writer(sio)
                writer.writerow(
                    [
                        "user_id",
                        "username",
                        "full_name",
                        "language",
                        "is_banned",
                        "ban_reason",
                        "esim_count",
                        "joined_at",
                        "last_active",
                    ]
                )
                for u in users:
                    writer.writerow(
                        [
                            u["user_id"],
                            u["username"],
                            u["full_name"],
                            u["language"],
                            u["is_banned"],
                            u["ban_reason"],
                            u["esim_count"],
                            u["joined_at"],
                            u["last_active"],
                        ]
                    )
                bio = io.BytesIO(sio.getvalue().encode("utf-8-sig"))
                bio.name = "bot_users.csv"
                await query.message.reply_document(
                    document=InputFile(bio, filename="bot_users.csv"),
                    caption=f"📊 قائمة مستخدمي البوت ({len(users)} مستخدم)",
                )

            elif action == "pin_help":
                await query.answer()
                pin_msg = await query.message.reply_text(
                    "🛠️ أوامر الأدمن: /ban ID سبب - حظر مستخدم | /unban ID - فك حظر | /send ID رسالة - مراسلة مستخدم | /broadcast رسالة - إذاعة للجميع | /stats - الإحصائيات | /users - المستخدمين | /admin - لوحة التحكم"
                )
                try:
                    await context.bot.pin_chat_message(
                        chat_id=query.message.chat_id,
                        message_id=pin_msg.message_id,
                        disable_notification=True,
                    )
                except Exception:
                    pass

    # --------------------------------------------------------------------------
    # Forwarding User Messages to Admin & Admin Interactive Flow
    # --------------------------------------------------------------------------

    async def forward_to_owner(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        note: str = "",
        esim: Optional[EsimData] = None,
    ) -> None:
        """
        Forwards every incoming user message/action to the Bot Owner with quick action buttons.
        """
        user = update.effective_user
        if not user or self.is_admin(user.id):
            return

        uname = f"@{user.username}" if user.username else "بدون معرف"
        full_name = " ".join(filter(None, [user.first_name, user.last_name])) or "User"
        header = (
            f"📨 <b>رسالة جديدة من مستخدم | User Activity</b>\n"
            f"• <b>الاسم:</b> {html.escape(full_name)} ({html.escape(uname)})\n"
            f"• <b>ID:</b> <code>{user.id}</code>\n"
        )
        if note:
            header += f"• <b>الحدث:</b> {html.escape(note)}\n"
        if esim:
            header += f"• <b>LPA:</b> <code>{html.escape(esim.lpa)}</code>\n"

        admin_kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✉️ رد على المستخدم", callback_data=f"adm:quick_reply:{user.id}"
                    ),
                    InlineKeyboardButton(
                        "🚫 حظر المستخدم", callback_data=f"adm:quick_ban:{user.id}"
                    ),
                ]
            ]
        )

        try:
            info_msg = await context.bot.send_message(
                chat_id=self.owner_id,
                text=header,
                parse_mode=ParseMode.HTML,
                reply_markup=admin_kb,
            )
            self.forwarded_map[info_msg.message_id] = user.id

            if update.effective_message:
                fwd = await update.effective_message.forward(chat_id=self.owner_id)
                self.forwarded_map[fwd.message_id] = user.id
        except Exception as e:
            logger.warning(f"Could not forward message to owner {self.owner_id}: {e}")

    async def handle_admin_interactive_input(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """
        Handles multi-step admin actions (broadcast, reply, ban, unban) and native Reply to forwarded messages.
        Returns True if the message was consumed as an admin action.
        """
        user = update.effective_user
        msg = update.effective_message
        if not user or not msg or not self.is_admin(user.id):
            return False

        # Cancel command
        if msg.text and msg.text.strip().lower() == "/cancel":
            if user.id in self.admin_state:
                self.admin_state.pop(user.id, None)
                await msg.reply_text("✅ تم إلغاء العملية الحالية.")
                return True

        # Check active admin state machine
        state = self.admin_state.get(user.id)
        if state:
            mode = state.get("mode")
            if mode == "broadcast":
                self.admin_state.pop(user.id, None)
                users = self.db.get_all_users(include_banned=False)
                sent, failed = 0, 0
                status = await msg.reply_text(f"⏳ جاري الإرسال إلى {len(users)} مستخدم...")
                for u in users:
                    try:
                        await context.bot.copy_message(
                            chat_id=u["user_id"],
                            from_chat_id=msg.chat_id,
                            message_id=msg.message_id,
                        )
                        sent += 1
                        await asyncio.sleep(0.04)
                    except Exception:
                        failed += 1
                await status.edit_text(
                    f"✅ <b>اكتملت الإذاعة الجماعية!</b>\n• تم الإرسال: <b>{sent}</b>\n• فشل: <b>{failed}</b>",
                    parse_mode=ParseMode.HTML,
                )
                return True

            if mode == "reply_user":
                target_id = int(state["target_id"])
                self.admin_state.pop(user.id, None)
                if msg.text:
                    await self._send_message_to_user(update, context, target_id, msg.text)
                else:
                    try:
                        await context.bot.copy_message(
                            chat_id=target_id,
                            from_chat_id=msg.chat_id,
                            message_id=msg.message_id,
                        )
                        await msg.reply_text(
                            f"✅ تم إرسال الوسائط إلى المستخدم <code>{target_id}</code>.",
                            parse_mode=ParseMode.HTML,
                        )
                    except Exception as e:
                        await msg.reply_text(f"❌ فشل الإرسال: {e}")
                return True

            if mode == "send_wait_id" and msg.text:
                raw_id = msg.text.strip()
                if not raw_id.isdigit():
                    await msg.reply_text("❌ يرجى إرسال رقم ID صحيح (أرقام فقط) أو /cancel:")
                    return True
                self.admin_state[user.id] = {"mode": "reply_user", "target_id": int(raw_id)}
                await msg.reply_text(
                    f"✉️ الآن أرسل الرسالة التي تريد إرسالها للمستخدم <code>{raw_id}</code>:",
                    parse_mode=ParseMode.HTML,
                )
                return True

            if mode == "ban_wait_id" and msg.text:
                parts = msg.text.strip().split(None, 1)
                if not parts[0].isdigit():
                    await msg.reply_text("❌ يرجى إرسال رقم ID صحيح متبوعاً بالسبب، أو /cancel:")
                    return True
                target_id = int(parts[0])
                reason = parts[1] if len(parts) > 1 else "مخالفة شروط الاستخدام / Policy violation"
                self.admin_state.pop(user.id, None)
                self.db.ban_user(target_id, reason)
                await msg.reply_text(
                    f"🚫 تم حظر المستخدم <code>{target_id}</code>.\nالسبب: {html.escape(reason)}",
                    parse_mode=ParseMode.HTML,
                )
                return True

            if mode == "unban_wait_id" and msg.text:
                raw_id = msg.text.strip()
                if not raw_id.isdigit():
                    await msg.reply_text("❌ يرجى إرسال رقم ID صحيح أو /cancel:")
                    return True
                target_id = int(raw_id)
                self.admin_state.pop(user.id, None)
                self.db.unban_user(target_id)
                await msg.reply_text(
                    f"✅ تم فك حظر المستخدم <code>{target_id}</code>.",
                    parse_mode=ParseMode.HTML,
                )
                return True

        # Check if Admin is replying directly to a forwarded user message
        if msg.reply_to_message:
            replied_id = msg.reply_to_message.message_id
            target_id = self.forwarded_map.get(replied_id)
            if not target_id and msg.reply_to_message.text:
                id_match = re.search(r"ID:\s*(\d+)", msg.reply_to_message.text)
                if id_match:
                    target_id = int(id_match.group(1))
            if target_id:
                if msg.text and parse_esim_payload(msg.text):
                    return False
                if msg.text:
                    await self._send_message_to_user(update, context, target_id, msg.text)
                else:
                    try:
                        await context.bot.copy_message(
                            chat_id=target_id,
                            from_chat_id=msg.chat_id,
                            message_id=msg.message_id,
                        )
                        await msg.reply_text(
                            f"✅ تم إرسال الرد إلى <code>{target_id}</code>.",
                            parse_mode=ParseMode.HTML,
                        )
                    except Exception as e:
                        await msg.reply_text(f"❌ تعذر إرسال الرد: {e}")
                return True

        return False

    # --------------------------------------------------------------------------
    # Core eSIM Processing Handlers (Text, Links, Photos, Image Documents)
    # --------------------------------------------------------------------------

    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        lang = await self.register_and_check_ban(update)
        if not lang:
            return

        if await self.handle_admin_interactive_input(update, context):
            return

        text = update.effective_message.text or ""
        esim = parse_esim_payload(text, source_type="text")

        if not esim:
            await self.forward_to_owner(update, context, note="💬 رسالة نصية")
            await update.effective_message.reply_text(
                TRANSLATIONS[lang]["invalid_input"],
                parse_mode=ParseMode.HTML,
            )
            return

        await self._send_esim_card(update, context, esim, lang)

    async def handle_photo_or_document(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        lang = await self.register_and_check_ban(update)
        if not lang:
            return

        if await self.handle_admin_interactive_input(update, context):
            return

        msg = update.effective_message
        file_obj = None
        if msg.photo:
            file_obj = await msg.photo[-1].get_file()
        elif msg.document and msg.document.mime_type and msg.document.mime_type.startswith("image/"):
            file_obj = await msg.document.get_file()

        if not file_obj:
            await self.forward_to_owner(update, context, note="📎 ملف مرفق")
            await msg.reply_text(
                TRANSLATIONS[lang]["invalid_input"],
                parse_mode=ParseMode.HTML,
            )
            return

        img_bytes = bytes(await file_obj.download_as_bytearray())
        decoded_qr = decode_qr_from_image_bytes(img_bytes)

        esim = None
        if decoded_qr:
            esim = parse_esim_payload(decoded_qr, source_type="qr_image")
        if not esim and msg.caption:
            esim = parse_esim_payload(msg.caption, source_type="caption")

        if not esim:
            await self.forward_to_owner(update, context, note="🖼️ صورة بدون باركود eSIM واضح")
            await msg.reply_text(
                TRANSLATIONS[lang]["qr_not_found"],
                parse_mode=ParseMode.HTML,
            )
            return

        await self._send_esim_card(update, context, esim, lang)

    async def _send_esim_card(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        esim: EsimData,
        lang: str,
    ) -> None:
        user = update.effective_user
        self.db.record_conversion(
            user_id=user.id,
            smdp=esim.smdp,
            matching_id=esim.matching_id,
            lpa=esim.lpa,
            source_type=esim.source_type,
        )

        qr_png = generate_qr_png_bytes(esim.lpa)
        caption, markup = format_esim_response(esim, lang=lang)

        await update.effective_message.reply_photo(
            photo=InputFile(io.BytesIO(qr_png), filename="esim_qr.png"),
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )

        await self.forward_to_owner(
            update,
            context,
            note=f"✅ تحويل شريحة eSIM ({esim.source_type})",
            esim=esim,
        )


# ==============================================================================
# 6. APPLICATION ENTRYPOINT
# ==============================================================================

async def post_init(application: Application) -> None:
    commands = [
        BotCommand("start", "بدء البوت | Start Bot | 启动机器人"),
        BotCommand("lang", "تغيير اللغة | Change Language | 切换语言"),
        BotCommand("help", "المساعدة | Help | 帮助"),
        BotCommand("admin", "لوحة تحكم الأدمن | Admin Panel"),
    ]
    try:
        await application.bot.set_my_commands(commands)
    except TelegramError as e:
        logger.warning(f"Could not set bot commands: {e}")


def main() -> None:
    bot_token, owner_id = load_or_prompt_config()

    # If PORT is set in environment and web server hasn't started yet, start health-check server
    port_env = os.environ.get("PORT")
    if port_env and port_env.isdigit() and not KeepAliveAndSetupHandler.bot_running:
        KeepAliveAndSetupHandler.bot_running = True
        start_background_http_server(int(port_env))
    else:
        KeepAliveAndSetupHandler.bot_running = True

    db = Database(DB_FILE)
    bot_app = EsimBotApp(bot_token=bot_token, owner_id=owner_id, db=db)

    application = (
        ApplicationBuilder()
        .token(bot_token)
        .post_init(post_init)
        .build()
    )

    # Register command handlers
    application.add_handler(CommandHandler("start", bot_app.cmd_start))
    application.add_handler(CommandHandler(["lang", "language"], bot_app.cmd_lang))
    application.add_handler(CommandHandler("help", bot_app.cmd_help))

    # Admin command handlers
    application.add_handler(CommandHandler(["admin", "panel"], bot_app.cmd_admin))
    application.add_handler(CommandHandler("ban", bot_app.cmd_ban))
    application.add_handler(CommandHandler("unban", bot_app.cmd_unban))
    application.add_handler(CommandHandler(["send", "msg"], bot_app.cmd_send))
    application.add_handler(CommandHandler(["broadcast", "all"], bot_app.cmd_broadcast))
    application.add_handler(CommandHandler("stats", bot_app.cmd_stats))
    application.add_handler(CommandHandler("users", bot_app.cmd_users))

    # Callback queries
    application.add_handler(CallbackQueryHandler(bot_app.on_callback_query))

    # Photos & image documents
    application.add_handler(
        MessageHandler(filters.PHOTO | filters.Document.IMAGE, bot_app.handle_photo_or_document)
    )

    # Text messages (LPA strings, Apple/Android URLs, or admin interactive replies)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, bot_app.handle_text_message)
    )

    logger.info(f"🚀 Starting eSIM Converter Bot (Owner ID: {owner_id})...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
