import os
import io
import json
import time
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from pyrogram.errors import FloodWait

# ═══════════════════════════════════════════════════════════════════════════════
#                              CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

BOT_TOKEN = "8622917685:AAECVP2-vTmbaef2FC6uOFHFvR5H0K_WLsE"
API_ID = 25621841
API_HASH = "083efc80016252b6b88bc476bb4ea724"

DATA_FILE = "users_data.json"

# Pyrogram (MTProto) bot token download/upload limit is 2 GB.
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB

# Session states
STATE_IDLE = "idle"
STATE_COMBINE = "combine"
STATE_SPLIT = "split"
STATE_SPLIT_METHOD = "split_method"
STATE_SPLIT_VALUE = "split_value"
STATE_MAKETXT = "maketxt"
STATE_CSVTOTXT = "csvtotxt"
STATE_REMOVEDUPE = "removedupe"
STATE_RENAME_FILE = "rename_file"
STATE_RENAME_NAME = "rename_name"

# ═══════════════════════════════════════════════════════════════════════════════
#                              LOGGING SETUP
# ═══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
#                              DATA MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

def load_users() -> Dict:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_users(users: Dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

def register_user(user) -> None:
    users = load_users()
    uid = str(user.id)
    users[uid] = {
        "id": user.id,
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "username": user.username or "",
        "last_active": datetime.now().isoformat(),
    }
    save_users(users)

# ═══════════════════════════════════════════════════════════════════════════════
#                              SESSION STATE
# ═══════════════════════════════════════════════════════════════════════════════

sessions: Dict[int, Dict] = {}

def get_session(user_id: int) -> Dict:
    if user_id not in sessions:
        sessions[user_id] = {"state": STATE_IDLE}
    return sessions[user_id]

def reset_session(user_id: int) -> None:
    sessions.pop(user_id, None)

# ═══════════════════════════════════════════════════════════════════════════════
#                              UI COMPONENTS
# ═══════════════════════════════════════════════════════════════════════════════

HEADER = """
╔══════════════════════════════════════╗
║       FILE TOOLKIT BOT               ║
║          Dev: Levetche               ║
╚══════════════════════════════════════╝"""

DIVIDER = "━" * 40

def main_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("◈ COMBINER ◈", callback_data="combine"),
            InlineKeyboardButton("◈ SPLITTER ◈", callback_data="split"),
        ],
        [
            InlineKeyboardButton("◈ MAKE TXT ◈", callback_data="maketxt"),
            InlineKeyboardButton("◈ CSV→TXT ◈", callback_data="csvtotxt"),
        ],
        [
            InlineKeyboardButton("◈ RM COMMON ◈", callback_data="removedupe"),
            InlineKeyboardButton("◈ RENAME ◈", callback_data="rename"),
        ],
        [
            InlineKeyboardButton("▣ STATS", callback_data="stats"),
            InlineKeyboardButton("▣ HELP", callback_data="help"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("◄ BACK TO MENU", callback_data="menu")]]
    )

def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("◄ CANCEL", callback_data="menu")]]
    )

def combine_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("▶ COMBINE NOW", callback_data="do_combine")],
            [InlineKeyboardButton("✕ CLEAR FILES", callback_data="clear_combine")],
            [InlineKeyboardButton("◄ CANCEL", callback_data="cancel_combine")],
        ]
    )

def split_method_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("◈ BY MAX SIZE (MB)", callback_data="split_size")],
            [InlineKeyboardButton("◈ BY NUMBER OF FILES", callback_data="split_count")],
            [InlineKeyboardButton("◈ BY MAX LINES", callback_data="split_lines")],
            [InlineKeyboardButton("◄ CANCEL", callback_data="cancel_split")],
        ]
    )

def maketxt_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("▶ CREATE TXT", callback_data="do_maketxt")],
            [InlineKeyboardButton("✕ CLEAR LINES", callback_data="clear_maketxt")],
            [InlineKeyboardButton("◄ CANCEL", callback_data="cancel_maketxt")],
        ]
    )

def removedupe_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✕ CLEAR FILES", callback_data="clear_removedupe")],
            [InlineKeyboardButton("◄ CANCEL", callback_data="cancel_removedupe")],
        ]
    )

# ═══════════════════════════════════════════════════════════════════════════════
#                              HELPER: SAFE REPLY
# ═══════════════════════════════════════════════════════════════════════════════

_flood_until = 0.0

async def safe_send(client, chat_id, text, reply_markup=None, reply_to_message_id=None):
    """Send a message, swallowing FloodWait."""
    global _flood_until
    import time
    now = time.monotonic()
    if now < _flood_until:
        return None
    try:
        return await client.send_message(
            chat_id,
            text,
            reply_markup=reply_markup,
            reply_to_message_id=reply_to_message_id,
            disable_web_page_preview=True,
        )
    except FloodWait as e:
        _flood_until = now + e.value
        logger.warning("FloodWait %ds on send_message, skipping", e.value)
        return None

# ═══════════════════════════════════════════════════════════════════════════════
#                              FILE DOWNLOAD/UPLOAD HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

async def download_file_bytes(client, message: Message) -> Optional[bytes]:
    """Download a file via Pyrogram MTProto (up to 2GB). Returns bytes or None on error."""
    try:
        # in_memory=True returns a BytesIO-like object directly
        buf = await client.download_media(message, in_memory=True)
        if buf is None:
            return None
        # pyrogram returns io.BytesIO when in_memory=True
        if isinstance(buf, io.BytesIO):
            return buf.getvalue()
        if isinstance(buf, (bytes, bytearray)):
            return bytes(buf)
        # Fallback: read from file-like
        if hasattr(buf, "read"):
            return buf.read()
        return None
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        try:
            buf = await client.download_media(message, in_memory=True)
            if isinstance(buf, io.BytesIO):
                return buf.getvalue()
            if isinstance(buf, (bytes, bytearray)):
                return bytes(buf)
            if hasattr(buf, "read"):
                return buf.read()
        except Exception as ex:
            logger.error("Retry download failed: %s", ex)
        return None
    except Exception as e:
        logger.error("Download failed: %s", e)
        return None

async def send_document_bytes(client, chat_id, content: bytes, filename: str, caption: str = ""):
    """Send bytes as a document via Pyrogram MTProto (up to 2GB)."""
    bio = io.BytesIO(content)
    bio.name = filename
    await client.send_document(
        chat_id,
        document=bio,
        file_name=filename,
        caption=caption,
    )

async def send_document_file(client, chat_id, file_path: str, filename: str, caption: str = ""):
    """Send a file from disk by path (used for rename's binary passthrough)."""
    await client.send_document(
        chat_id,
        document=file_path,
        file_name=filename,
        caption=caption,
    )

# ═══════════════════════════════════════════════════════════════════════════════
#                              STATS DISPLAY
# ═══════════════════════════════════════════════════════════════════════════════

def build_stats_text() -> str:
    users = load_users()
    total = len(users)
    if total == 0:
        body = "    No users registered yet\n"
    else:
        body = ""
        for idx, (uid, data) in enumerate(users.items(), 1):
            name = f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()
            username = data.get("username", "")
            uname = f"@{username}" if username else "[no username]"
            body += f"  {idx:03d}. {name[:15]:<15} {uname}\n"
    return f"""
{HEADER}

         USER STATISTICS

{DIVIDER}
  Total Users: {total}
{DIVIDER}

{body}
{DIVIDER}"""

# ═══════════════════════════════════════════════════════════════════════════════
#                              START / HELP / STATS
# ═══════════════════════════════════════════════════════════════════════════════

WELCOME_TEXT = f"""
{HEADER}

  Welcome, {{name}}!

{DIVIDER}

  ◈ COMBINER
    Merge multiple TXT/CSV files
    into a single TXT file

  ◈ SPLITTER
    Split large TXT/CSV files
    by size, count, or lines

  ◈ MAKE TXT
    Convert text messages to TXT

  ◈ CSV→TXT
    Convert CSV file to TXT

  ◈ RM COMMON
    Remove lines common to
    2 files; returns 2 files

  ◈ RENAME
    Rename any file with full
    new name (incl. extension)

  ► Max file size: 2 GB
  ► Duplicates removed automatically

{DIVIDER}
      Select an option below
{DIVIDER}"""

HELP_TEXT = f"""
{HEADER}

           HELP GUIDE

{DIVIDER}

  ► COMBINER
    1. Select COMBINER
    2. Send multiple TXT/CSV files
    3. Click COMBINE NOW
    4. Receive merged TXT file

  ► SPLITTER
    1. Select SPLITTER
    2. Send a TXT/CSV file
    3. Choose split method
    4. Enter the value
    5. Receive split TXT files

  ► MAKE TXT
    1. Select MAKE TXT
    2. Send text messages
    3. Click CREATE TXT
    4. Receive TXT file

  ► CSV→TXT
    1. Select CSV→TXT
    2. Send a CSV file
    3. Receive TXT file

  ► RM COMMON
    1. Select RM COMMON
    2. Send 2 text files
    3. Lines common to BOTH
       files are removed
    4. Receive 2 output files
       (one per input)
    Whitespace trimmed when
    matching; order preserved

  ► RENAME
    1. Select RENAME
    2. Send any file (any type)
    3. Type a new full filename
       (incl. extension, e.g. .py)
    4. Receive file with new name
    No validation; no extension
    auto-appended; binary-safe

  ► COMMANDS
    /start  - Main menu
    /help   - This guide
    /stats  - User statistics
    /cancel - Cancel current op

  ► NOTE
    • Max file size: 2 GB
    • Duplicates removed automatically

{DIVIDER}"""

MENU_TEXT = f"""
{HEADER}

            MAIN MENU

{DIVIDER}

  ◈ COMBINER - Merge files
  ◈ SPLITTER - Split files
  ◈ MAKE TXT - Text to file
  ◈ CSV→TXT  - Convert CSV
  ◈ RM COMMON - Remove common lines
  ◈ RENAME   - Rename any file

  ► Max file size: 2 GB

{DIVIDER}
      Select an option below
{DIVIDER}"""

# ═══════════════════════════════════════════════════════════════════════════════
#                              APPLICATION
# ═══════════════════════════════════════════════════════════════════════════════

app = Client(
    "file_toolkit_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=8,
    max_concurrent_transmissions=10,
)

# ───────────────────────────────────────────────────────────────────────────────
# COMMAND HANDLERS
# ───────────────────────────────────────────────────────────────────────────────

@app.on_message(filters.command("start") & filters.private)
async def cmd_start(client: Client, message: Message):
    user = message.from_user
    register_user(user)
    reset_session(user.id)
    text = WELCOME_TEXT.format(name=user.first_name or "user")
    await message.reply(text, reply_markup=main_menu_keyboard(), disable_web_page_preview=True)

@app.on_message(filters.command("help") & filters.private)
async def cmd_help(client: Client, message: Message):
    register_user(message.from_user)
    await message.reply(HELP_TEXT, reply_markup=back_keyboard(), disable_web_page_preview=True)

@app.on_message(filters.command("stats") & filters.private)
async def cmd_stats(client: Client, message: Message):
    register_user(message.from_user)
    await message.reply(build_stats_text(), reply_markup=back_keyboard(), disable_web_page_preview=True)

@app.on_message(filters.command("cancel") & filters.private)
async def cmd_cancel(client: Client, message: Message):
    reset_session(message.from_user.id)
    await message.reply(
        "Operation cancelled. Use /start to begin again.",
        reply_markup=back_keyboard(),
    )

# ───────────────────────────────────────────────────────────────────────────────
# CALLBACK QUERY DISPATCHER
# ───────────────────────────────────────────────────────────────────────────────

@app.on_callback_query(filters.regex(r"^.+$"))
async def on_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    register_user(callback.from_user)
    sess = get_session(user_id)
    data = callback.data

    # ── MENU NAVIGATION ──
    if data == "menu":
        reset_session(user_id)
        sess = get_session(user_id)
        try:
            await callback.edit_message_text(MENU_TEXT, reply_markup=main_menu_keyboard())
        except Exception:
            pass
        await callback.answer()
        return

    if data == "help":
        try:
            await callback.edit_message_text(HELP_TEXT, reply_markup=back_keyboard())
        except Exception:
            pass
        await callback.answer()
        return

    if data == "stats":
        try:
            await callback.edit_message_text(build_stats_text(), reply_markup=back_keyboard())
        except Exception:
            pass
        await callback.answer()
        return

    # ── COMBINER ──
    if data == "combine":
        sess["state"] = STATE_COMBINE
        sess["combine_files"] = []
        text = f"""
{HEADER}

            COMBINER

{DIVIDER}

  ► Send TXT or CSV files
  ► Files will be merged by lines
  ► Output: single TXT file
  ► Max file size: 2 GB

  Files received: 0

{DIVIDER}
      Send your files below
{DIVIDER}"""
        await callback.edit_message_text(text, reply_markup=combine_keyboard())
        await callback.answer()
        return

    if data == "do_combine":
        files = sess.get("combine_files", [])
        if len(files) < 2:
            await callback.answer("Please send at least 2 files to combine!", show_alert=True)
            return
        await do_combine_files(client, callback, sess, user_id)
        await callback.answer()
        return

    if data == "clear_combine":
        sess["combine_files"] = []
        text = f"""
{HEADER}

            COMBINER

{DIVIDER}

  ► Files cleared!
  ► Send new TXT or CSV files

  Files received: 0

{DIVIDER}
      Send your files below
{DIVIDER}"""
        await callback.edit_message_text(text, reply_markup=combine_keyboard())
        await callback.answer()
        return

    if data == "cancel_combine":
        reset_session(user_id)
        await _go_menu(callback)
        await callback.answer()
        return

    # ── SPLITTER ──
    if data == "split":
        sess["state"] = STATE_SPLIT
        sess["split_file"] = None
        text = f"""
{HEADER}

            SPLITTER

{DIVIDER}

  ► Send a TXT or CSV file
  ► Choose split method
  ► Output: multiple TXT files
  ► Max file size: 2 GB

  Waiting for file...

{DIVIDER}
       Send your file below
{DIVIDER}"""
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◄ CANCEL", callback_data="cancel_split")]])
        await callback.edit_message_text(text, reply_markup=kb)
        await callback.answer()
        return

    if data == "cancel_split":
        reset_session(user_id)
        await _go_menu(callback)
        await callback.answer()
        return

    if data.startswith("split_") and data not in ("split_method_back",):
        method = data.replace("split_", "")
        sess["split_method"] = method
        method_names = {
            "size": "MAX SIZE (MB)",
            "count": "NUMBER OF FILES",
            "lines": "MAX LINES PER FILE",
        }
        prompts = {
            "size": "Enter maximum size per file in MB:",
            "count": "Enter number of files to split into:",
            "lines": "Enter maximum lines per file:",
        }
        m = method_names.get(method, method.upper())
        p = prompts.get(method, "Enter value:")
        text = f"""
{HEADER}

            SPLITTER

{DIVIDER}

  Method: {m}

  {p}

{DIVIDER}
       Type a number below
{DIVIDER}"""
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◄ BACK", callback_data="split_method_back")]])
        await callback.edit_message_text(text, reply_markup=kb)
        sess["state"] = STATE_SPLIT_VALUE
        await callback.answer()
        return

    if data == "split_method_back":
        text = f"""
{HEADER}

            SPLITTER

{DIVIDER}

  ► File received!
  ► Choose split method below

{DIVIDER}
      Select split method
{DIVIDER}"""
        await callback.edit_message_text(text, reply_markup=split_method_keyboard())
        sess["state"] = STATE_SPLIT_METHOD
        await callback.answer()
        return

    # ── MAKE TXT ──
    if data == "maketxt":
        sess["state"] = STATE_MAKETXT
        sess["maketxt_lines"] = []
        text = f"""
{HEADER}

            MAKE TXT

{DIVIDER}

  ► Send text messages
  ► Each message = one line
  ► Duplicates auto-removed

  Lines received: 0

{DIVIDER}
       Send your text below
{DIVIDER}"""
        await callback.edit_message_text(text, reply_markup=maketxt_keyboard())
        await callback.answer()
        return

    if data == "do_maketxt":
        lines = sess.get("maketxt_lines", [])
        if len(lines) < 1:
            await callback.answer("Please send at least 1 line of text!", show_alert=True)
            return
        await do_maketxt(client, callback, sess, user_id)
        await callback.answer()
        return

    if data == "clear_maketxt":
        sess["maketxt_lines"] = []
        text = f"""
{HEADER}

            MAKE TXT

{DIVIDER}

  ► Lines cleared!
  ► Send new text messages

  Lines received: 0

{DIVIDER}
       Send your text below
{DIVIDER}"""
        await callback.edit_message_text(text, reply_markup=maketxt_keyboard())
        await callback.answer()
        return

    if data == "cancel_maketxt":
        reset_session(user_id)
        await _go_menu(callback)
        await callback.answer()
        return

    # ── CSV TO TXT ──
    if data == "csvtotxt":
        sess["state"] = STATE_CSVTOTXT
        text = f"""
{HEADER}

           CSV → TXT

{DIVIDER}

  ► Send a CSV file
  ► Converts to TXT format
  ► Duplicates auto-removed
  ► Max file size: 2 GB

  Waiting for file...

{DIVIDER}
     Send your CSV file below
{DIVIDER}"""
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◄ CANCEL", callback_data="cancel_csvtotxt")]])
        await callback.edit_message_text(text, reply_markup=kb)
        await callback.answer()
        return

    if data == "cancel_csvtotxt":
        reset_session(user_id)
        await _go_menu(callback)
        await callback.answer()
        return

    # ── REMOVE COMMON LINES ──
    if data == "removedupe":
        sess["state"] = STATE_REMOVEDUPE
        sess["removedupe_files"] = []
        text = f"""
{HEADER}

        REMOVE COMMON LINES

{DIVIDER}

  ► Sends TWO text files
  ► Lines common to both are
    REMOVED from each output
  ► Whitespace trimmed when
    matching; order preserved
  ► Output: 2 separate files
  ► Max file size: 2 GB

  Files received: 0

{DIVIDER}
      Send your files below
{DIVIDER}"""
        await callback.edit_message_text(text, reply_markup=removedupe_keyboard())
        await callback.answer()
        return

    if data == "clear_removedupe":
        sess["removedupe_files"] = []
        text = f"""
{HEADER}

        REMOVE COMMON LINES

{DIVIDER}

  ► Files cleared!
  ► Send new text files

  Files received: 0

{DIVIDER}
      Send your files below
{DIVIDER}"""
        await callback.edit_message_text(text, reply_markup=removedupe_keyboard())
        await callback.answer()
        return

    if data == "cancel_removedupe":
        reset_session(user_id)
        await _go_menu(callback)
        await callback.answer()
        return

    # ── RENAME ──
    if data == "rename":
        sess["state"] = STATE_RENAME_FILE
        sess["rename_file"] = None
        text = f"""
{HEADER}

             RENAME

{DIVIDER}

  ► Send ANY file to rename
    (any type, any size up to 2GB)
  ► Then type the NEW full
    filename (incl. extension,
    e.g. .txt, .py, .csv)
  ► No validation enforced
  ► No extension auto-appended
  ► Binary-safe passthrough

  Waiting for file...

{DIVIDER}
       Send your file below
{DIVIDER}"""
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◄ CANCEL", callback_data="cancel_rename")]])
        await callback.edit_message_text(text, reply_markup=kb)
        await callback.answer()
        return

    if data == "cancel_rename":
        reset_session(user_id)
        await _go_menu(callback)
        await callback.answer()
        return

    await callback.answer()

async def _go_menu(callback: CallbackQuery):
    try:
        await callback.edit_message_text(MENU_TEXT, reply_markup=main_menu_keyboard())
    except Exception:
        pass

# ───────────────────────────────────────────────────────────────────────────────
# DOCUMENT HANDLER (dispatches by session state)
# ───────────────────────────────────────────────────────────────────────────────

@app.on_message(filters.document & filters.private)
async def on_document(client: Client, message: Message):
    if message.from_user is None:
        return
    user_id = message.from_user.id
    register_user(message.from_user)
    sess = get_session(user_id)
    state = sess.get("state", STATE_IDLE)

    doc = message.document
    file_name = (doc.file_name or "file").lower()
    file_size = doc.file_size or 0

    if file_size > MAX_FILE_SIZE_BYTES:
        await safe_send(client, message.chat.id,
            f"⚠ File too large! Maximum size is 2 GB. (got {file_size / 1024**3:.2f} GB)")
        return

    if state == STATE_COMBINE:
        await handle_combine_file(client, message, sess)
    elif state == STATE_SPLIT and sess.get("split_file") is None:
        await handle_split_file(client, message, sess)
    elif state == STATE_CSVTOTXT:
        await handle_csvtotxt_file(client, message, sess)
    elif state == STATE_REMOVEDUPE:
        await handle_removedupe_file(client, message, sess)
    elif state == STATE_RENAME_FILE:
        await handle_rename_file(client, message, sess)
    else:
        await safe_send(
            client, message.chat.id,
            "Use /start to access the menu and pick a feature first.",
            reply_markup=back_keyboard(),
        )

# ───────────────────────────────────────────────────────────────────────────────
# TEXT HANDLER (dispatches by session state)
# ───────────────────────────────────────────────────────────────────────────────

TEXT_EXCLUDE_CMDS = ["start", "help", "stats", "cancel"]

@app.on_message(filters.text & filters.private & ~filters.command(TEXT_EXCLUDE_CMDS))
async def on_text(client: Client, message: Message):
    if message.from_user is None:
        return
    user_id = message.from_user.id
    register_user(message.from_user)
    sess = get_session(user_id)
    state = sess.get("state", STATE_IDLE)

    if state == STATE_SPLIT_VALUE:
        await handle_split_value(client, message, sess)
    elif state == STATE_MAKETXT:
        await handle_maketxt_text(client, message, sess)
    elif state == STATE_RENAME_NAME:
        await handle_rename_name(client, message, sess)
    # Other states: ignore plain text

# ═══════════════════════════════════════════════════════════════════════════════
#                              COMBINER
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_combine_file(client: Client, message: Message, sess: Dict):
    doc = message.document
    file_name = (doc.file_name or "file").lower()
    if not (file_name.endswith(".txt") or file_name.endswith(".csv")):
        await safe_send(
            client, message.chat.id,
            "⚠ Only TXT and CSV files are supported for COMBINER!",
            reply_markup=combine_keyboard(),
        )
        return

    content = await download_file_bytes(client, message)
    if content is None:
        await safe_send(
            client, message.chat.id,
            "⚠ Failed to download file. Try again.",
            reply_markup=combine_keyboard(),
        )
        return

    files = sess.setdefault("combine_files", [])
    files.append({
        "name": doc.file_name or "file",
        "content": content.decode("utf-8", errors="ignore"),
    })
    count = len(files)
    file_list = "\n".join(f"  {i+1}. {f['name'][:30]}" for i, f in enumerate(files))
    text = f"""
{HEADER}

            COMBINER

{DIVIDER}
  Files received: {count}
{DIVIDER}

{file_list}

{DIVIDER}
   Send more files or click COMBINE
{DIVIDER}"""
    await safe_send(client, message.chat.id, text, reply_markup=combine_keyboard())

async def do_combine_files(client: Client, callback: CallbackQuery, sess: Dict, user_id: int):
    files = sess.get("combine_files", [])
    processing_text = f"""
{HEADER}

          PROCESSING

{DIVIDER}

      ▓▓▓▓▓▓░░░░ 50%

   Combining {len(files)} files...

{DIVIDER}"""
    try:
        await callback.edit_message_text(processing_text)
    except Exception:
        pass

    all_lines: List[str] = []
    for f in files:
        all_lines.extend(f["content"].splitlines())

    seen = set()
    unique_lines = []
    for line in all_lines:
        if line not in seen:
            seen.add(line)
            unique_lines.append(line)

    combined = "\n".join(unique_lines)
    if combined and not combined.endswith("\n"):
        combined += "\n"

    total_lines = len(unique_lines)
    dupes_removed = len(all_lines) - total_lines

    result_text = f"""
{HEADER}

           COMPLETED

{DIVIDER}

  ► Files combined: {len(files)}
  ► Total lines: {total_lines}
  ► Duplicates removed: {dupes_removed}
  ► Output format: TXT

{DIVIDER}"""
    try:
        await callback.edit_message_text(result_text, reply_markup=back_keyboard())
    except Exception:
        pass

    await send_document_bytes(
        client, callback.message.chat.id,
        combined.encode("utf-8"),
        "combined_output.txt",
        "► Combined file ready!",
    )
    reset_session(user_id)

# ═══════════════════════════════════════════════════════════════════════════════
#                              SPLITTER
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_split_file(client: Client, message: Message, sess: Dict):
    doc = message.document
    file_name = (doc.file_name or "file").lower()
    if not (file_name.endswith(".txt") or file_name.endswith(".csv")):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◄ CANCEL", callback_data="cancel_split")]])
        await safe_send(
            client, message.chat.id,
            "⚠ Only TXT and CSV files are supported for SPLITTER!",
            reply_markup=kb,
        )
        return

    content = await download_file_bytes(client, message)
    if content is None:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◄ CANCEL", callback_data="cancel_split")]])
        await safe_send(
            client, message.chat.id,
            "⚠ Failed to download file. Try again.",
            reply_markup=kb,
        )
        return

    sess["split_file"] = {
        "name": doc.file_name or "file",
        "content": content.decode("utf-8", errors="ignore"),
        "raw_size": len(content),
    }

    lines = sess["split_file"]["content"].count("\n") + 1
    size_kb = sess["split_file"]["raw_size"] / 1024

    text = f"""
{HEADER}

            SPLITTER

{DIVIDER}

  ► File: {sess['split_file']['name'][:28]}
  ► Size: {size_kb:.1f} KB
  ► Lines: {lines}

  Choose split method:

{DIVIDER}
       Select method below
{DIVIDER}"""
    await safe_send(client, message.chat.id, text, reply_markup=split_method_keyboard())
    sess["state"] = STATE_SPLIT_METHOD

async def handle_split_value(client: Client, message: Message, sess: Dict):
    raw = (message.text or "").strip()
    try:
        value = int(raw)
        if value <= 0:
            raise ValueError
    except ValueError:
        await safe_send(client, message.chat.id, "⚠ Please enter a valid positive number!")
        return

    method = sess.get("split_method")
    file_data = sess.get("split_file")
    if not file_data:
        await safe_send(
            client, message.chat.id,
            "⚠ No file found. Please start over.",
            reply_markup=back_keyboard(),
        )
        reset_session(message.from_user.id)
        return

    user_id = message.from_user.id
    file_name = file_data["name"]
    file_size_mb = file_data.get("raw_size", 0) / (1024 * 1024)
    logger.info("SPLIT user=%s file=%s size=%.1fMB method=%s value=%s",
                user_id, file_name, file_size_mb, method, value)

    content = file_data["content"]
    raw_lines = content.splitlines()
    logger.info("SPLIT user=%s deduplicating %d lines...", user_id, len(raw_lines))
    seen = set()
    unique_lines = []
    for line in raw_lines:
        if line not in seen:
            seen.add(line)
            unique_lines.append(line)
    dupes_removed = len(raw_lines) - len(unique_lines)
    lines = [line + "\n" for line in unique_lines]
    logger.info("SPLIT user=%s unique lines=%d dupes_removed=%d",
                user_id, len(unique_lines), dupes_removed)

    processing_text = f"""
{HEADER}

          PROCESSING

{DIVIDER}

      ▓▓▓▓▓▓░░░░ 50%

    Splitting file...

{DIVIDER}"""
    status_msg = await safe_send(client, message.chat.id, processing_text)

    chunks = []
    if method == "lines":
        for i in range(0, len(lines), value):
            chunks.append("".join(lines[i:i + value]))
    elif method == "count":
        if value > len(lines):
            value = len(lines)
        if value <= 0:
            chunks = ["".join(lines)] if lines else []
        else:
            chunk_size = len(lines) // value
            remainder = len(lines) % value
            start = 0
            for i in range(value):
                extra = 1 if i < remainder else 0
                end = start + chunk_size + extra
                chunk = lines[start:end]
                if chunk:
                    chunks.append("".join(chunk))
                start = end
    elif method == "size":
        max_bytes = value * 1024 * 1024  # MB → bytes
        current = ""
        current_len = 0
        for line in lines:
            line_len = len(line.encode("utf-8"))
            if current and current_len + line_len > max_bytes:
                chunks.append(current)
                current = line
                current_len = line_len
            else:
                current += line
                current_len += line_len
        if current:
            chunks.append(current)
    else:
        chunks = [content]

    if not chunks:
        chunks = [content]

    # Guard against runaway chunk counts (would take forever to send)
    MAX_CHUNKS = 500
    if len(chunks) > MAX_CHUNKS:
        logger.warning("SPLIT user=%s chunk count %d exceeds cap %d — aborting",
                       user_id, len(chunks), MAX_CHUNKS)
        abort_text = f"""
{HEADER}

           ⚠ TOO MANY PARTS

{DIVIDER}

  ► Requested: {len(chunks)} files
  ► Maximum allowed: {MAX_CHUNKS} files

  This would take too long to send.
  Try a larger size / fewer files.

{DIVIDER}"""
        if status_msg:
            try:
                await status_msg.edit_text(abort_text, reply_markup=back_keyboard())
            except Exception:
                pass
        reset_session(user_id)
        return

    logger.info("SPLIT user=%s split into %d chunks", user_id, len(chunks))

    result_text = f"""
{HEADER}

           COMPLETED

{DIVIDER}

  ► Files created: {len(chunks)}
  ► Duplicates removed: {dupes_removed}
  ► Output format: TXT

  Sending {len(chunks)} file(s)...

{DIVIDER}"""
    if status_msg:
        try:
            await status_msg.edit_text(result_text, reply_markup=back_keyboard())
        except Exception:
            pass
    else:
        await safe_send(client, message.chat.id, result_text, reply_markup=back_keyboard())

    base_name = os.path.splitext(file_data["name"])[0]
    ext = os.path.splitext(file_data["name"])[1] or ".txt"
    t0 = time.monotonic()
    for i, chunk in enumerate(chunks, 1):
        fname = f"{base_name}_part{i:03d}{ext}"
        logger.info("SPLIT user=%s sending part %d/%d (%s, %.1f KB)",
                    user_id, i, len(chunks), fname, len(chunk.encode("utf-8")) / 1024)
        await send_document_bytes(
            client, message.chat.id,
            chunk.encode("utf-8"),
            fname,
            f"► Part {i} of {len(chunks)}",
        )
        await asyncio.sleep(0.3)
    logger.info("SPLIT user=%s done — %d files sent in %.1fs",
                user_id, len(chunks), time.monotonic() - t0)

    reset_session(user_id)

# ═══════════════════════════════════════════════════════════════════════════════
#                              MAKE TXT
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_maketxt_text(client: Client, message: Message, sess: Dict):
    text = (message.text or "").strip()
    if not text:
        await safe_send(client, message.chat.id, "Please send some text.")
        return

    lines = sess.setdefault("maketxt_lines", [])
    lines.extend(text.splitlines())
    count = len(lines)
    preview = "\n".join(f"  {line[:34]}" for line in lines[-5:])
    body = f"""
{HEADER}

            MAKE TXT

{DIVIDER}
  Lines received: {count}
{DIVIDER}
  Last lines:
{preview}
{DIVIDER}
   Send more or click CREATE TXT
{DIVIDER}"""
    await safe_send(client, message.chat.id, body, reply_markup=maketxt_keyboard())

async def do_maketxt(client: Client, callback: CallbackQuery, sess: Dict, user_id: int):
    lines = sess.get("maketxt_lines", [])
    processing_text = f"""
{HEADER}

          PROCESSING

{DIVIDER}

      ▓▓▓▓▓▓░░░░ 50%

    Creating TXT file...

{DIVIDER}"""
    try:
        await callback.edit_message_text(processing_text)
    except Exception:
        pass

    seen = set()
    unique_lines = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            unique_lines.append(line)
    dupes_removed = len(lines) - len(unique_lines)

    content = "\n".join(unique_lines)
    if content and not content.endswith("\n"):
        content += "\n"

    result_text = f"""
{HEADER}

           COMPLETED

{DIVIDER}

  ► Total lines: {len(unique_lines)}
  ► Duplicates removed: {dupes_removed}
  ► Output format: TXT

{DIVIDER}"""
    try:
        await callback.edit_message_text(result_text, reply_markup=back_keyboard())
    except Exception:
        pass

    await send_document_bytes(
        client, callback.message.chat.id,
        content.encode("utf-8"),
        "output.txt",
        "► TXT file ready!",
    )
    reset_session(user_id)

# ═══════════════════════════════════════════════════════════════════════════════
#                              CSV → TXT
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_csvtotxt_file(client: Client, message: Message, sess: Dict):
    doc = message.document
    file_name = (doc.file_name or "file").lower()
    if not file_name.endswith(".csv"):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◄ CANCEL", callback_data="cancel_csvtotxt")]])
        await safe_send(
            client, message.chat.id,
            "⚠ Only CSV files are supported!",
            reply_markup=kb,
        )
        return

    content = await download_file_bytes(client, message)
    if content is None:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◄ CANCEL", callback_data="cancel_csvtotxt")]])
        await safe_send(
            client, message.chat.id,
            "⚠ Failed to download file. Try again.",
            reply_markup=kb,
        )
        return

    text_decoded = content.decode("utf-8", errors="ignore")
    processing_text = f"""
{HEADER}

          PROCESSING

{DIVIDER}

      ▓▓▓▓▓▓░░░░ 50%

   Converting CSV to TXT...

{DIVIDER}"""
    status_msg = await safe_send(client, message.chat.id, processing_text)

    raw_lines = text_decoded.splitlines()
    seen = set()
    unique_lines = []
    for line in raw_lines:
        if line not in seen:
            seen.add(line)
            unique_lines.append(line)
    dupes_removed = len(raw_lines) - len(unique_lines)

    out = "\n".join(unique_lines)
    if out and not out.endswith("\n"):
        out += "\n"

    base_name = os.path.splitext(doc.file_name or "file")[0]
    result_text = f"""
{HEADER}

           COMPLETED

{DIVIDER}

  ► Total lines: {len(unique_lines)}
  ► Duplicates removed: {dupes_removed}
  ► Output format: TXT

{DIVIDER}"""
    if status_msg:
        try:
            await status_msg.edit_text(result_text, reply_markup=back_keyboard())
        except Exception:
            pass

    await send_document_bytes(
        client, message.chat.id,
        out.encode("utf-8"),
        f"{base_name}.txt",
        "► TXT file ready!",
    )
    reset_session(message.from_user.id)

# ═══════════════════════════════════════════════════════════════════════════════
#                              REMOVE COMMON LINES
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_removedupe_file(client: Client, message: Message, sess: Dict):
    doc = message.document
    content = await download_file_bytes(client, message)
    if content is None:
        await safe_send(
            client, message.chat.id,
            "⚠ Failed to download file. Try again.",
            reply_markup=removedupe_keyboard(),
        )
        return

    files = sess.setdefault("removedupe_files", [])
    files.append({
        "name": doc.file_name or "file",
        "content": content.decode("utf-8", errors="ignore"),
    })

    count = len(files)
    file_list = "\n".join(f"  {i+1}. {f['name'][:30]}" for i, f in enumerate(files))

    if count < 2:
        text = f"""
{HEADER}

        REMOVE COMMON LINES

{DIVIDER}
  Files received: {count}
{DIVIDER}

{file_list}

{DIVIDER}
    Send file 2 below to proceed
{DIVIDER}"""
        await safe_send(client, message.chat.id, text, reply_markup=removedupe_keyboard())
        return

    # Two files collected -> process
    await do_removedupe(client, message, sess, message.from_user.id)

async def do_removedupe(client: Client, message: Message, sess: Dict, user_id: int):
    files = sess.get("removedupe_files", [])
    if len(files) < 2:
        await safe_send(
            client, message.chat.id,
            "⚠ Need exactly 2 files to process.",
            reply_markup=back_keyboard(),
        )
        reset_session(user_id)
        return

    status_msg = await safe_send(
        client, message.chat.id,
        f"""
{HEADER}

          PROCESSING

{DIVIDER}

      ▓▓▓▓▓▓░░░░ 50%

   Removing common lines...

{DIVIDER}""",
    )

    lines1 = files[0]["content"].splitlines()
    lines2 = files[1]["content"].splitlines()

    trimmed1 = {ln.strip() for ln in lines1}
    trimmed2 = {ln.strip() for ln in lines2}
    common = trimmed1 & trimmed2

    out1 = [ln for ln in lines1 if ln.strip() not in common]
    out2 = [ln for ln in lines2 if ln.strip() not in common]

    out1_text = "\n".join(out1)
    if out1_text and not out1_text.endswith("\n"):
        out1_text += "\n"
    out2_text = "\n".join(out2)
    if out2_text and not out2_text.endswith("\n"):
        out2_text += "\n"

    common_count = len(common)

    base1 = os.path.splitext(files[0]["name"])[0]
    base2 = os.path.splitext(files[1]["name"])[0]

    result_text = f"""
{HEADER}

           COMPLETED

{DIVIDER}

  ► Files in: 2
  ► File 1 lines: {len(out1)} (of {len(lines1)})
  ► File 2 lines: {len(out2)} (of {len(lines2)})
  ► Common removed: {common_count}
  ► Output: 2 TXT files

{DIVIDER}"""
    if status_msg:
        try:
            await status_msg.edit_text(result_text, reply_markup=back_keyboard())
        except Exception:
            pass
    else:
        await safe_send(client, message.chat.id, result_text, reply_markup=back_keyboard())

    await send_document_bytes(
        client, message.chat.id,
        out1_text.encode("utf-8"),
        f"{base1}_unique.txt",
        "► File 1 (common removed)",
    )
    await asyncio.sleep(0.3)
    await send_document_bytes(
        client, message.chat.id,
        out2_text.encode("utf-8"),
        f"{base2}_unique.txt",
        "► File 2 (common removed)",
    )
    reset_session(user_id)

# ═══════════════════════════════════════════════════════════════════════════════
#                              RENAME
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_rename_file(client: Client, message: Message, sess: Dict):
    doc = message.document
    content = await download_file_bytes(client, message)
    if content is None:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◄ CANCEL", callback_data="cancel_rename")]])
        await safe_send(
            client, message.chat.id,
            "⚠ Failed to download file. Try again.",
            reply_markup=kb,
        )
        return

    size_kb = len(content) / 1024
    sess["rename_file"] = {
        "name": doc.file_name or "file",
        "content": content,
        "size": len(content),
    }

    text = f"""
{HEADER}

             RENAME

{DIVIDER}

  ► File: {(doc.file_name or 'file')[:30]}
  ► Size: {size_kb:.1f} KB

  Now type the NEW full filename
  (including extension, e.g. .txt,
  .py, .csv, .html, etc.)

  ► No validation enforced
  ► No extension auto-appended
  ► Use EXACTLY what you type
  ► Original file content unchanged

{DIVIDER}
       Type the new name below
{DIVIDER}"""
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("◄ CANCEL", callback_data="cancel_rename")]])
    await safe_send(client, message.chat.id, text, reply_markup=kb)
    sess["state"] = STATE_RENAME_NAME

async def handle_rename_name(client: Client, message: Message, sess: Dict):
    new_name = (message.text or "").strip()
    file_data = sess.get("rename_file")
    if not file_data:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◄ BACK TO MENU", callback_data="menu")]])
        await safe_send(
            client, message.chat.id,
            "⚠ No file to rename. Please start over with /start.",
            reply_markup=kb,
        )
        reset_session(message.from_user.id)
        return

    if not new_name:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◄ CANCEL", callback_data="cancel_rename")]])
        await safe_send(
            client, message.chat.id,
            "⚠ Filename cannot be empty. Type a new filename below.",
            reply_markup=kb,
        )
        return

    status_msg = await safe_send(
        client, message.chat.id,
        f"""
{HEADER}

          PROCESSING

{DIVIDER}

      ▓▓▓▓▓▓░░░░ 50%

   Renaming file...

{DIVIDER}""",
    )

    result_text = f"""
{HEADER}

           COMPLETED

{DIVIDER}

  ► Original: {file_data['name'][:30]}
  ► New name: {new_name[:30]}
  ► Size: {file_data['size']/1024:.1f} KB

{DIVIDER}"""
    if status_msg:
        try:
            await status_msg.edit_text(result_text, reply_markup=back_keyboard())
        except Exception:
            pass
    else:
        await safe_send(client, message.chat.id, result_text, reply_markup=back_keyboard())

    await send_document_bytes(
        client, message.chat.id,
        file_data["content"],
        new_name,
        f"► Renamed: {file_data['name']} → {new_name}",
    )
    reset_session(message.from_user.id)

# ═══════════════════════════════════════════════════════════════════════════════
#                              MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    print("═" * 50)
    print("  FILE TOOLKIT BOT - RUNNING (Pyrogram MTProto)")
    print(f"  Max file size: 2 GB")
    print("═" * 50)
    app.run()

if __name__ == "__main__":
    main()
