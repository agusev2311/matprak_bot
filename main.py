import telebot
from telebot import types
import sqlite3
import time
import datetime
import html
import io
import re
import sys
import sql_return
import sorting_123
import json
import os
import parsing_gpt
from dateutil.relativedelta import relativedelta
from threading import Thread, Lock
from collections import Counter
# import prog
import zipfile
import requests

LOGS_DIR = os.path.join(os.getcwd(), "logs")
SESSION_LOGS_DIR = os.path.join(LOGS_DIR, "sessions")
POLLING_ERRORS_LOG_PATH = os.path.join(LOGS_DIR, "polling_errors.log")
os.makedirs(SESSION_LOGS_DIR, exist_ok=True)


class TeeStream:
    def __init__(self, *streams):
        self.streams = streams
        self.lock = Lock()
        self.encoding = getattr(streams[0], "encoding", "utf-8") if streams else "utf-8"

    def write(self, data):
        with self.lock:
            for stream in self.streams:
                stream.write(data)
                stream.flush()
        return len(data)

    def flush(self):
        with self.lock:
            for stream in self.streams:
                stream.flush()

    def isatty(self):
        return any(getattr(stream, "isatty", lambda: False)() for stream in self.streams)


SESSION_LOG_STAMP = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
SESSION_LOG_PATH = os.path.join(SESSION_LOGS_DIR, f"console_{SESSION_LOG_STAMP}.log")
session_log_stream = open(SESSION_LOG_PATH, "a", encoding="utf-8", buffering=1)
sys.stdout = TeeStream(sys.stdout, session_log_stream)
sys.stderr = TeeStream(sys.stderr, session_log_stream)

print("main.py started")
print(f"session log started: {SESSION_LOG_PATH}")

with open('config.json', 'r') as file:
    config = json.load(file)

sql_return.init_db()
sql_return.init_files_db()
sql_return.initialize_lesson_notification_baseline()

is_polling = True

bot = telebot.TeleBot(config["tg-token"])

GPT_SQL_ALLOWED_EXTRA_USER_ID = 930442932
MAX_UPLOAD_SIZE_BYTES = 15 * 1024 * 1024
try:
    LESSON_NOTIFICATION_POLL_SECONDS = max(10, int(config.get("lesson_notification_poll_seconds", 30)))
except Exception:
    LESSON_NOTIFICATION_POLL_SECONDS = 30

CHATGPT_CUSTOM_EMOJI_ID = "5438315589087037978"
CHECK_CUSTOM_EMOJI_ID = "5429501538806548545"
CROSS_CUSTOM_EMOJI_ID = "5416076321442777828"
BROADCAST_ALLOWED_CONTENT_TYPES = {
    "text", "photo", "document", "video", "audio", "voice", "animation", "sticker"
}
SOLUTION_SUBMISSION_ALLOWED_CONTENT_TYPES = {
    "text", "photo", "document"
}

gpt_sql_requests_lock = Lock()
gpt_sql_requests = {}
gpt_sql_request_seq = 0
lesson_notifications_lock = Lock()
broadcast_drafts_lock = Lock()
broadcast_drafts = {}
broadcast_draft_seq = 0
solution_submission_sessions_lock = Lock()
solution_submission_sessions = {}

def get_admin_id() -> int:
    return int(config["admin_id"])


def can_use_gpt_lesson_button(user_id: int) -> bool:
    return int(user_id) in {get_admin_id(), GPT_SQL_ALLOWED_EXTRA_USER_ID}


def next_gpt_sql_request_id() -> int:
    global gpt_sql_request_seq
    with gpt_sql_requests_lock:
        gpt_sql_request_seq += 1
        return gpt_sql_request_seq


def get_course_title(course_id: int) -> str:
    course = sql_return.find_course_id(course_id)
    if not course:
        return str(course_id)
    return str(course[1])


def is_course_admin_or_dev(user_id: int, course_id: int) -> bool:
    course = sql_return.find_course_id(course_id)
    if not course:
        return False
    developer_ids = (course[4] or "").split()
    return (
        int(user_id) == get_admin_id()
        or str(user_id) == str(course[2])
        or str(user_id) in developer_ids
    )


def can_access_course_materials(user_id: int, course_id: int) -> bool:
    course = sql_return.find_course_id(course_id)
    if not course:
        return False
    if is_course_admin_or_dev(user_id, course_id):
        return True
    student_ids = (course[3] or "").split()
    return str(user_id) in student_ids


def custom_emoji_html(custom_emoji_id: str, fallback_emoji: str) -> str:
    return f'<tg-emoji emoji-id="{custom_emoji_id}">{fallback_emoji}</tg-emoji>'


CHECK_HTML = custom_emoji_html(CHECK_CUSTOM_EMOJI_ID, "✅")
CROSS_HTML = custom_emoji_html(CROSS_CUSTOM_EMOJI_ID, "❌")
CHATGPT_HTML = custom_emoji_html(CHATGPT_CUSTOM_EMOJI_ID, "🤖")
CUSTOM_EMOJI_HTML_RE = re.compile(r'<tg-emoji\b[^>]*>(.*?)</tg-emoji>', re.DOTALL)


def strip_custom_emoji_html(text: str) -> str:
    return CUSTOM_EMOJI_HTML_RE.sub(lambda match: match.group(1), text)


def can_retry_without_custom_emoji(error: Exception) -> bool:
    error_text = str(error).lower()
    return (
        "custom emoji" in error_text
        or "can't parse entities" in error_text
        or "emoji-id" in error_text
    )


_raw_send_message = bot.send_message
_raw_edit_message_text = bot.edit_message_text
_raw_send_document = bot.send_document
_raw_inline_keyboard_button_to_dict = types.InlineKeyboardButton.to_dict


def send_message_with_custom_emoji_fallback(chat_id, text, *args, **kwargs):
    try:
        return _raw_send_message(chat_id, text, *args, **kwargs)
    except Exception as error:
        if isinstance(text, str) and "<tg-emoji" in text and can_retry_without_custom_emoji(error):
            log(f"custom_emoji_fallback: send_message chat_id={chat_id} error={error}")
            return _raw_send_message(chat_id, strip_custom_emoji_html(text), *args, **kwargs)
        raise


def edit_message_text_with_custom_emoji_fallback(text, *args, **kwargs):
    try:
        return _raw_edit_message_text(text, *args, **kwargs)
    except Exception as error:
        if isinstance(text, str) and "<tg-emoji" in text and can_retry_without_custom_emoji(error):
            log(f"custom_emoji_fallback: edit_message_text error={error}")
            return _raw_edit_message_text(strip_custom_emoji_html(text), *args, **kwargs)
        raise


def send_document_with_custom_emoji_fallback(chat_id, document, *args, **kwargs):
    try:
        return _raw_send_document(chat_id, document, *args, **kwargs)
    except Exception as error:
        caption = kwargs.get("caption")
        if isinstance(caption, str) and "<tg-emoji" in caption and can_retry_without_custom_emoji(error):
            fallback_kwargs = dict(kwargs)
            fallback_kwargs["caption"] = strip_custom_emoji_html(caption)
            log(f"custom_emoji_fallback: send_document chat_id={chat_id} error={error}")
            return _raw_send_document(chat_id, document, *args, **fallback_kwargs)
        raise


bot.send_message = send_message_with_custom_emoji_fallback
bot.edit_message_text = edit_message_text_with_custom_emoji_fallback
bot.send_document = send_document_with_custom_emoji_fallback


def inline_keyboard_button_to_dict_with_extras(self):
    json_dict = _raw_inline_keyboard_button_to_dict(self)
    style = getattr(self, "style", None)
    icon_custom_emoji_id = getattr(self, "icon_custom_emoji_id", None)
    if style is not None:
        json_dict["style"] = style
    if icon_custom_emoji_id is not None:
        json_dict["icon_custom_emoji_id"] = icon_custom_emoji_id
    return json_dict


types.InlineKeyboardButton.to_dict = inline_keyboard_button_to_dict_with_extras


def ui_button(text: str, callback_data: str | None = None, style: str | None = None, icon_custom_emoji_id: str | None = None, **kwargs):
    button_kwargs = dict(kwargs)
    if callback_data is not None:
        button_kwargs["callback_data"] = callback_data
    button = types.InlineKeyboardButton(text, **button_kwargs)
    if style is not None:
        button.style = style
    if icon_custom_emoji_id is not None:
        button.icon_custom_emoji_id = icon_custom_emoji_id
    return button


def verdict_button_custom_emoji_id(verdict) -> str | None:
    if verdict == "accept":
        return CHECK_CUSTOM_EMOJI_ID
    if verdict == "reject":
        return CROSS_CUSTOM_EMOJI_ID
    return None


def next_broadcast_draft_id() -> int:
    global broadcast_draft_seq
    with broadcast_drafts_lock:
        broadcast_draft_seq += 1
        return broadcast_draft_seq


def has_active_solution_submission(user_id: int) -> bool:
    with solution_submission_sessions_lock:
        session = solution_submission_sessions.get(int(user_id))
        return bool(session and session.get("status") == "collecting")


def get_solution_submission_session(user_id: int):
    with solution_submission_sessions_lock:
        session = solution_submission_sessions.get(int(user_id))
        if not session:
            return None
        return dict(session)


def cancel_solution_submission_session(user_id: int):
    with solution_submission_sessions_lock:
        return solution_submission_sessions.pop(int(user_id), None)


def start_solution_submission_session(user_id: int, chat_id: int, task, prompt_message_id: int):
    task_id, lesson_id, task_title, _, _, task_description = task
    course_id = sql_return.get_course_from_lesson_id(lesson_id)
    session = {
        "user_id": int(user_id),
        "chat_id": int(chat_id),
        "course_id": int(course_id),
        "lesson_id": int(lesson_id),
        "task_id": int(task_id),
        "task_title": str(task_title or "Без названия"),
        "task_description": str(task_description or ""),
        "task_snapshot": tuple(task),
        "prompt_message_id": int(prompt_message_id),
        "status": "collecting",
        "text_chunks": [],
        "attachments": [],
        "processed_message_ids": set(),
        "started_at": time.time(),
    }
    with solution_submission_sessions_lock:
        solution_submission_sessions[int(user_id)] = session
    return dict(session)


def update_solution_submission_session(user_id: int, updater):
    with solution_submission_sessions_lock:
        session = solution_submission_sessions.get(int(user_id))
        if not session:
            return None
        updater(session)
        return dict(session)


def mark_solution_submission_finalizing(user_id: int):
    with solution_submission_sessions_lock:
        session = solution_submission_sessions.get(int(user_id))
        if not session or session.get("status") != "collecting":
            return None
        session["status"] = "finalizing"
        return dict(session)


def build_solution_submission_markup():
    markup = types.InlineKeyboardMarkup()
    markup.row(
        ui_button("Отправить решение", callback_data="solution_submit_finish", style="success", icon_custom_emoji_id=CHECK_CUSTOM_EMOJI_ID),
        ui_button("Отменить", callback_data="solution_submit_cancel", style="danger", icon_custom_emoji_id=CROSS_CUSTOM_EMOJI_ID),
    )
    return markup


def build_solution_submission_text(task, session: dict) -> str:
    task_id, _, task_title, task_status, task_deadline, task_description = task
    task_status_label = TASK_STATUS_LABELS.get(task_status, str(task_status or "Неизвестно"))
    text_count = len(session.get("text_chunks") or [])
    file_count = len(session.get("attachments") or [])
    text_status = f"{text_count} сообщ." if text_count else "нет"
    file_status = f"{file_count} шт." if file_count else "нет"

    return (
        "<b>Сдача решения</b>\n"
        "Отправляйте текст решения и любое количество фото/документов отдельными сообщениями или альбомом.\n"
        "Когда всё будет готово, нажмите кнопку <b>Отправить решение</b>.\n"
        "Для быстрой отмены можно отправить <code>/cancel</code>.\n\n"
        f"<b>Текст уже добавлен:</b> {html.escape(text_status)}\n"
        f"<b>Файлов уже добавлено:</b> {html.escape(file_status)}\n\n"
        f"📌 <b>Название задачи</b>: {html.escape(str(task_title or 'Без названия'))}\n"
        f"🔖 <b>Статус</b>: {html.escape(task_status_label)}\n"
        f"⏰ <b>Дедлайн</b>: {html.escape(format_deadline(task_deadline))}\n"
        f"📝 <b>Текст задачи</b>: {html.escape(str(task_description or 'Нет текста задачи'))}"
    )


def refresh_solution_submission_prompt(user_id: int):
    session = get_solution_submission_session(user_id)
    if not session:
        return
    task = session.get("task_snapshot")
    if not task:
        return
    try:
        bot.edit_message_text(
            build_solution_submission_text(task, session),
            chat_id=session["chat_id"],
            message_id=session["prompt_message_id"],
            parse_mode="HTML",
            reply_markup=build_solution_submission_markup(),
        )
    except Exception:
        pass


def build_solution_answer_text(session: dict) -> str:
    text_chunks = [str(chunk).strip() for chunk in session.get("text_chunks") or [] if str(chunk).strip()]
    if not text_chunks:
        return ""
    return "\n\n".join(text_chunks)


def normalize_user_action_text(value, max_len: int = 240) -> str:
    text = " ".join(str(value).split())
    if len(text) > max_len:
        return f"{text[:max_len - 3]}..."
    return text


def format_user_for_log(from_user) -> str:
    user_id = getattr(from_user, "id", "unknown")
    username = getattr(from_user, "username", None)
    telegram_name = " ".join(
        part
        for part in [getattr(from_user, "first_name", ""), getattr(from_user, "last_name", "")]
        if part
    ).strip()

    db_name = ""
    try:
        db_user = sql_return.get_user_name(int(user_id))
        if db_user:
            db_name = " ".join(part for part in db_user if part).strip()
    except Exception:
        db_name = ""

    resolved_name = db_name or telegram_name or "unknown_name"
    username_part = f"@{username}" if username else "no_username"
    return f"{resolved_name} ({username_part}, id={user_id})"


def log_user_action(from_user, action: str, details: str = "") -> None:
    safe_action = normalize_user_action_text(action, 120)
    safe_details = normalize_user_action_text(details)
    message = f"user_action: {safe_action} | {format_user_for_log(from_user)}"
    if safe_details:
        message += f" | {safe_details}"
    log(message)


def callback_action_name(callback_data: str) -> str:
    action_map = (
        ("reg_approve_", "registration.approve"),
        ("reg_deny_", "registration.deny"),
        ("reg_ban_", "registration.ban"),
        ("mm_send", "menu.send"),
        ("mm_check", "menu.check"),
        ("mm_courses_", "menu.courses"),
        ("mm_answers_", "menu.answers"),
        ("mm_main_menu", "menu.main"),
        ("course_", "course.open"),
        ("add_student_", "course.add_student_prompt"),
        ("add_developer_", "course.add_developer_prompt"),
        ("content_", "course.content"),
        ("gpt_add_lesson_", "gpt_lesson.start"),
        ("attach_lesson_file_", "lesson.attach_prompt"),
        ("download_lesson_file_", "lesson.download"),
        ("download_solution_file_", "solution.file_download"),
        ("toggle_task_", "task.toggle_status"),
        ("lesson_", "lesson.open"),
        ("task_", "task.open"),
        ("send-course_", "solution.select_course"),
        ("send-task_", "solution.select_lesson"),
        ("send-final_", "solution.select_task"),
        ("check-course-all_", "check.all_courses"),
        ("check-course_", "check.course"),
        ("check-add-comment_", "check.comment_prompt"),
        ("check-final", "check.final_verdict"),
        ("create_course", "course.create_prompt"),
        ("create_lesson", "lesson.create_prompt"),
        ("create_task", "task.create_prompt"),
        ("solution_submit_finish", "solution.submit_finish"),
        ("solution_submit_cancel", "solution.submit_cancel"),
        ("solution", "solution.open"),
        ("self_reject", "solution.self_reject"),
        ("undo_self_reject", "solution.self_reject_undo"),
        ("admin_panel_open", "admin.panel_open"),
        ("admin_panel_backup", "admin.backup"),
        ("admin_panel_broadcast", "admin.broadcast_prompt"),
        ("admin_panel_stop", "admin.stop"),
        ("admin_panel_ban", "admin.ban_prompt"),
        ("admin_panel_unban", "admin.unban_prompt"),
        ("admin_panel_conf_stop", "admin.stop_confirm"),
        ("admin_broadcast_confirm_", "admin.broadcast_confirm"),
        ("admin_broadcast_cancel_", "admin.broadcast_cancel"),
        ("gptsql_accept_", "gpt_lesson.sql_accept"),
        ("gptsql_reject_", "gpt_lesson.sql_reject"),
        ("gptsql_retry_", "gpt_lesson.sql_retry"),
        ("stats_", "vpn.stats"),
    )
    for prefix, action in action_map:
        if callback_data.startswith(prefix):
            return action
    return "callback.unknown"


def save_lesson_source_file(message):
    if message.content_type not in ("photo", "document"):
        raise ValueError("Нужно отправить фотографию листка или PDF-файл.")

    if not os.path.exists("files"):
        os.makedirs("files")

    if message.content_type == "photo":
        file_info = bot.get_file(message.photo[-1].file_id)
        if file_info.file_size > MAX_UPLOAD_SIZE_BYTES:
            raise ValueError("Файл слишком большой. Максимальный размер - 15 МБ.")

        downloaded_file = bot.download_file(file_info.file_path)
        file_extension = os.path.splitext(file_info.file_path)[1].lower() or ".jpg"
        if file_extension not in [".jpg", ".jpeg", ".png", ".webp"]:
            file_extension = ".jpg"
        original_file_name = f"photo{file_extension}"
    else:
        file_info = bot.get_file(message.document.file_id)
        if file_info.file_size > MAX_UPLOAD_SIZE_BYTES:
            raise ValueError("Файл слишком большой. Максимальный размер - 15 МБ.")

        mime_type = (message.document.mime_type or "").lower()
        original_file_name = message.document.file_name or "document.pdf"
        file_extension = os.path.splitext(original_file_name)[1].lower()
        if file_extension != ".pdf" and mime_type != "application/pdf":
            raise ValueError("Для документа поддерживается только формат PDF.")
        file_extension = ".pdf"
        downloaded_file = bot.download_file(file_info.file_path)

    new_file_name = f'{sql_return.next_name("files")}{file_extension}'
    save_path = f"files/{new_file_name}"

    with open(save_path, "wb") as new_file:
        new_file.write(downloaded_file)

    sql_return.save_file(message.content_type, original_file_name, save_path, message.from_user.id)

    return {
        "file_path": save_path,
        "file_type": message.content_type,
        "stored_file_name": new_file_name,
        "original_file_name": original_file_name,
    }


def save_lesson_attachment_file(message):
    if message.content_type not in ("photo", "document"):
        raise ValueError("Нужно отправить документ или фотографию.")

    if not os.path.exists("files"):
        os.makedirs("files")

    if message.content_type == "photo":
        file_info = bot.get_file(message.photo[-1].file_id)
        if file_info.file_size > MAX_UPLOAD_SIZE_BYTES:
            raise ValueError("Файл слишком большой. Максимальный размер - 15 МБ.")

        downloaded_file = bot.download_file(file_info.file_path)
        file_extension = os.path.splitext(file_info.file_path)[1].lower() or ".jpg"
        if file_extension not in [".jpg", ".jpeg", ".png", ".webp"]:
            file_extension = ".jpg"
        original_file_name = f"lesson_photo{file_extension}"
    else:
        file_info = bot.get_file(message.document.file_id)
        if file_info.file_size > MAX_UPLOAD_SIZE_BYTES:
            raise ValueError("Файл слишком большой. Максимальный размер - 15 МБ.")

        downloaded_file = bot.download_file(file_info.file_path)
        original_file_name = message.document.file_name or os.path.basename(file_info.file_path) or "lesson_file"
        file_extension = os.path.splitext(original_file_name)[1].lower()
        if not file_extension:
            file_extension = os.path.splitext(file_info.file_path)[1].lower()
        if not file_extension:
            file_extension = ".bin"

    new_file_name = f'{sql_return.next_name("files")}{file_extension}'
    save_path = f"files/{new_file_name}"

    with open(save_path, "wb") as new_file:
        new_file.write(downloaded_file)

    sql_return.save_file(
        message.content_type,
        original_file_name,
        save_path,
        message.from_user.id
    )

    return {
        "file_id": os.path.splitext(new_file_name)[0],
        "file_path": save_path,
        "file_type": message.content_type,
        "stored_file_name": new_file_name,
        "original_file_name": original_file_name,
    }


def save_solution_attachment_file(attachment: dict, creator_id: int):
    content_type = attachment.get("content_type")
    if content_type not in ("photo", "document"):
        raise ValueError("К решению можно прикреплять только фотографии и документы.")

    if not os.path.exists("files"):
        os.makedirs("files")

    telegram_file_id = attachment.get("telegram_file_id")
    if not telegram_file_id:
        raise ValueError("Не удалось определить Telegram file_id для вложения.")

    file_info = bot.get_file(telegram_file_id)
    if file_info.file_size > MAX_UPLOAD_SIZE_BYTES:
        raise ValueError("Файл слишком большой. Максимальный размер - 15 МБ.")

    downloaded_file = bot.download_file(file_info.file_path)

    if content_type == "photo":
        file_extension = os.path.splitext(file_info.file_path)[1].lower() or ".jpg"
        if file_extension not in [".jpg", ".jpeg", ".png", ".webp"]:
            file_extension = ".jpg"
        original_file_name = attachment.get("original_file_name") or f"solution_photo{file_extension}"
    else:
        original_file_name = attachment.get("original_file_name") or os.path.basename(file_info.file_path) or "solution_file"
        file_extension = os.path.splitext(original_file_name)[1].lower()
        if not file_extension:
            file_extension = os.path.splitext(file_info.file_path)[1].lower()
        if not file_extension:
            file_extension = ".bin"

    new_file_name = f'{sql_return.next_name("files")}{file_extension}'
    save_path = f"files/{new_file_name}"

    with open(save_path, "wb") as new_file:
        new_file.write(downloaded_file)

    file_id = sql_return.save_file(content_type, original_file_name, save_path, creator_id)
    return {
        "file_id": file_id,
        "file_path": save_path,
        "file_type": content_type,
        "stored_file_name": new_file_name,
        "original_file_name": original_file_name,
    }


def cleanup_saved_solution_files(saved_files: list[dict]):
    for file_data in saved_files:
        file_id = file_data.get("file_id")
        file_path = file_data.get("file_path")
        try:
            if file_id:
                sql_return.delete_file(file_id)
        except Exception:
            pass
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass


def get_lesson_file_id(lesson_data) -> str | None:
    if not lesson_data or len(lesson_data) <= 5:
        return None
    return lesson_data[5]


def send_saved_file_to_chat(chat_id: int, file_info, caption: str | None = None):
    if not file_info:
        raise ValueError("Файл не найден.")

    file_type = file_info[2]
    file_name = file_info[3]
    file_path = file_info[4]

    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)

    if file_type == "photo":
        with open(file_path, "rb") as photo:
            send_kwargs = {"caption": caption}
            if caption and "<" in caption and ">" in caption:
                send_kwargs["parse_mode"] = "HTML"
            bot.send_photo(chat_id, photo, **send_kwargs)
    else:
        with open(file_path, "rb") as document:
            send_kwargs = {"caption": caption}
            if caption and "<" in caption and ">" in caption:
                send_kwargs["parse_mode"] = "HTML"
            if file_name:
                send_kwargs["visible_file_name"] = file_name
            bot.send_document(chat_id, document, **send_kwargs)


def chunk_items(items, chunk_size: int):
    for start in range(0, len(items), chunk_size):
        yield items[start:start + chunk_size]


def build_solution_media_caption(solution_data: dict, comment_override: str | None = None) -> str:
    comment = solution_data.get("comment") if comment_override is None else comment_override
    plain_verdict_labels = {
        "accept": "Принято",
        "reject": "Отклонено",
        "self_reject": "Отменено автором",
        None: "Ожидает проверки",
    }
    lines = [
        f"<b>Решение #{solution_data['answer_id']}</b>",
        f"<b>Вердикт:</b> {html.escape(plain_verdict_labels.get(solution_data.get('verdict'), 'Неизвестно'))}",
        f"<b>Курс:</b> {html.escape(str(solution_data.get('course_name') or 'Неизвестно'))}",
        f"<b>Урок:</b> {html.escape(str(solution_data.get('lesson_title') or 'Неизвестно'))}",
        f"<b>Задача #{solution_data['task_id']}:</b> {html.escape(str(solution_data.get('task_title') or 'Без названия'))}",
    ]
    if comment:
        lines.append(f"<b>Комментарий:</b> {html.escape(shorten_text(comment, 180))}")
    answer_text = str(solution_data.get("answer_text") or "").strip()
    if answer_text:
        lines.append(f"<b>Текст решения:</b> {html.escape(shorten_text(answer_text, 220))}")
    caption = "\n".join(lines)
    if len(caption) <= 1024:
        return caption
    fallback_lines = lines[:5]
    if comment:
        fallback_lines.append(f"<b>Комментарий:</b> {html.escape(shorten_text(comment, 100))}")
    return "\n".join(fallback_lines)[:1024]


def send_solution_files_preview(chat_id: int, solution_data: dict, comment_override: str | None = None):
    file_infos = get_solution_file_infos(solution_data)
    if not file_infos:
        return

    file_groups = []
    seen_types = []
    grouped_files = {"photo": [], "document": []}
    for file_info in file_infos:
        file_type = file_info[2]
        if file_type not in grouped_files:
            continue
        grouped_files[file_type].append(file_info)
        if file_type not in seen_types:
            seen_types.append(file_type)

    for file_type in seen_types:
        for group in chunk_items(grouped_files[file_type], 10):
            file_groups.append((file_type, group))

    caption_html = build_solution_media_caption(solution_data, comment_override)
    caption_used = False

    for file_type, group in file_groups:
        if len(group) == 1:
            file_info = group[0]
            send_saved_file_to_chat(
                chat_id,
                file_info,
                caption=caption_html if not caption_used else None,
            )
            caption_used = True
            continue

        media_items = []
        opened_files = []
        try:
            for index, file_info in enumerate(group):
                file_name = file_info[3]
                file_path = file_info[4]
                if not os.path.exists(file_path):
                    raise FileNotFoundError(file_path)
                opened_file = open(file_path, "rb")
                opened_files.append(opened_file)
                input_file = types.InputFile(opened_file, file_name=file_name or None)
                caption = caption_html if not caption_used and index == 0 else None
                parse_mode = "HTML" if caption else None
                if file_type == "photo":
                    media_items.append(types.InputMediaPhoto(input_file, caption=caption, parse_mode=parse_mode))
                else:
                    media_items.append(types.InputMediaDocument(input_file, caption=caption, parse_mode=parse_mode))
            bot.send_media_group(chat_id, media_items)
            caption_used = True
        finally:
            for opened_file in opened_files:
                try:
                    opened_file.close()
                except Exception:
                    pass


VERDICT_LABELS = {
    "accept": f"{CHECK_HTML} Принято",
    "reject": f"{CROSS_HTML} Отклонено",
    "self_reject": "💔 Отменено автором",
    None: "⌛️ Ожидает проверки",
}

VERDICT_ICONS = {
    "accept": "",
    "reject": "",
    "self_reject": "💔",
    None: "⌛️",
}

TASK_STATUS_LABELS = {
    "open": "Открыта",
    "close": "Закрыта",
    "arc": "Закрыта",
    "dev": "В разработке",
}


def shorten_text(value, max_len: int = 32) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return "Без названия"
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def truncate_block(value, max_len: int = 1200) -> str:
    text = str(value or "").strip()
    if not text:
        return "Нет"
    if len(text) <= max_len:
        return text
    return text[:max_len - 12].rstrip() + "\n... [обрезано]"


def format_deadline(deadline_value) -> str:
    if not deadline_value:
        return "Не указан"
    try:
        deadline_date = datetime.datetime.fromtimestamp(float(deadline_value) / 1000.0)
        return deadline_date.strftime('%d-%m-%Y %H:%M')
    except Exception:
        return str(deadline_value)


def safe_delete_message(chat_id: int, message_id: int | None):
    if not message_id:
        return
    try:
        bot.delete_message(chat_id, message_id)
    except Exception:
        pass


def build_main_menu_markup(user_id: int):
    markup = types.InlineKeyboardMarkup()
    markup.add(ui_button("✏️ Отправить решение", callback_data='mm_send'))
    markup.add(ui_button("🔍 Принять решение", callback_data='mm_check_0', style="primary"))
    markup.add(ui_button("📃 Все курсы", callback_data='mm_courses_0'))
    markup.add(ui_button("🗂 Все решения", callback_data='mm_answers_0'))
    if can_use_vpn_stats(user_id):
        markup.add(ui_button("🌐 VPN статистика", callback_data='stats_GiB', style="primary"))
    if int(user_id) == get_admin_id():
        markup.add(ui_button("🔑 Панель админа", callback_data="admin_panel_open", style="primary"))
    return markup


def build_pagination_buttons(prefix: str, page: int, total_pages: int):
    if total_pages <= 1:
        return []

    buttons = []
    if page > 0:
        buttons.append(types.InlineKeyboardButton("⏪", callback_data=f"{prefix}_0"))
        buttons.append(types.InlineKeyboardButton("⬅️", callback_data=f"{prefix}_{page - 1}"))

    buttons.append(types.InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data=f"{prefix}_{page}"))

    if page < total_pages - 1:
        buttons.append(types.InlineKeyboardButton("➡️", callback_data=f"{prefix}_{page + 1}"))
        buttons.append(types.InlineKeyboardButton("⏩", callback_data=f"{prefix}_{total_pages - 1}"))

    return buttons


def get_solution_file_infos(solution_data: dict | None) -> list[tuple]:
    if not solution_data:
        return []
    answer_id = solution_data.get("answer_id")
    if answer_id is None:
        return []
    return sql_return.get_student_answer_files(answer_id, solution_data.get("files_id"))


def get_solution_file_info(files_id):
    file_ids = sql_return.parse_file_ids_field(files_id)
    if not file_ids:
        return None
    return sql_return.get_file(file_ids[0])


def solution_owner_name(solution_data: dict) -> str:
    first_name = solution_data.get("student_first_name") or "Неизвестный"
    last_name = solution_data.get("student_last_name") or "пользователь"
    return f"{first_name} {last_name}".strip()


def can_access_solution(user_id: int, solution_data: dict | None) -> bool:
    if not solution_data:
        return False
    if int(user_id) == int(solution_data["student_id"]):
        return True
    return is_course_admin_or_dev(user_id, int(solution_data["course_id"]))


def build_solution_list_button_text(solution_data: dict, viewer_id: int) -> str:
    role_icon = "👨‍🎓" if int(solution_data["student_id"]) == int(viewer_id) else "👨‍🏫"
    file_count = int(solution_data.get("file_count") or 0)
    file_icon = f"📎{file_count}" if file_count else ""
    status_icon = VERDICT_ICONS.get(solution_data.get("verdict"), "⌛️")

    if int(solution_data["student_id"]) == int(viewer_id):
        owner_part = ""
    else:
        owner_part = shorten_text(solution_owner_name(solution_data), 12) + " • "

    body = (
        f"{owner_part}"
        f"{shorten_text(solution_data.get('course_name'), 14)} / "
        f"{shorten_text(solution_data.get('lesson_title'), 14)} / "
        f"#{solution_data.get('task_id')} {shorten_text(solution_data.get('task_title'), 12)}"
    )
    prefix = f"{role_icon}{file_icon}"
    if status_icon:
        prefix += status_icon
    return shorten_text(f"{prefix} {body}", 64)


def build_solution_detail_text(solution_data: dict, comment_override: str | None = None) -> str:
    comment = solution_data.get("comment") if comment_override is None else comment_override
    file_infos = get_solution_file_infos(solution_data)
    if file_infos:
        visible_names = [str(file_info[3] or file_info[4] or f"Файл {index + 1}") for index, file_info in enumerate(file_infos[:8])]
        file_name = "\n".join(f"{index + 1}. {name}" for index, name in enumerate(visible_names))
        if len(file_infos) > len(visible_names):
            file_name += f"\n... и ещё {len(file_infos) - len(visible_names)}"
    else:
        file_name = "Нет"
    answer_text = truncate_block(solution_data.get("answer_text"), 1400)
    task_text = truncate_block(solution_data.get("task_description"), 1400)

    return (
        f"<b>Решение #{solution_data['answer_id']}</b>\n"
        f"<b>Вердикт:</b> {VERDICT_LABELS.get(solution_data.get('verdict'), 'Неизвестно')}\n"
        f"<b>Отправил:</b> {html.escape(solution_owner_name(solution_data))}\n"
        f"<b>Время отправки:</b> {html.escape(str(solution_data.get('submission_date') or 'Неизвестно'))}\n"
        f"<b>Курс:</b> {html.escape(str(solution_data.get('course_name') or 'Неизвестно'))}\n"
        f"<b>Урок:</b> {html.escape(str(solution_data.get('lesson_title') or 'Неизвестно'))}\n"
        f"<b>Задача #{solution_data['task_id']}:</b> {html.escape(str(solution_data.get('task_title') or 'Без названия'))}\n"
        f"<b>Статус задачи:</b> {html.escape(TASK_STATUS_LABELS.get(solution_data.get('task_status'), str(solution_data.get('task_status') or 'Неизвестно')))}\n"
        f"<b>Дедлайн:</b> {html.escape(format_deadline(solution_data.get('task_deadline')))}\n"
        f"<b>Файлы решения:</b> {html.escape(str(len(file_infos)))}\n{html.escape(str(file_name))}\n"
        f"<b>Комментарий к вердикту:</b> {html.escape(str(comment if comment else 'Нет'))}\n\n"
        f"<b>Текст задачи:</b>\n{html.escape(task_text)}\n\n"
        f"<b>Текст решения:</b>\n{html.escape(answer_text)}"
    )


def show_solution_details(
    call,
    solution_data: dict,
    reply_markup,
    file_button_caption: str | None = None,
    comment_override: str | None = None,
    show_files_preview: bool = False,
):
    if not solution_data:
        bot.send_message(call.message.chat.id, "Решение не найдено.")
        return

    safe_delete_message(call.message.chat.id, call.message.message_id)

    if show_files_preview:
        try:
            send_solution_files_preview(call.message.chat.id, solution_data, comment_override)
        except FileNotFoundError:
            bot.send_message(call.message.chat.id, "Часть файлов решения есть в базе, но отсутствует на диске.")
        except Exception:
            bot.send_message(call.message.chat.id, "Не удалось открыть файлы решения как единый пакет. Попробуйте кнопку повторной отправки файлов.")

    bot.send_message(
        call.message.chat.id,
        build_solution_detail_text(solution_data, comment_override),
        reply_markup=reply_markup,
        parse_mode="HTML"
    )


def build_admin_panel_text(confirm_stop: bool = False) -> str:
    status_counts = sql_return.get_user_status_counts()
    lines = [
        "Панель администратора",
        "",
        f"Непроверенных решений: {sql_return.count_unchecked_solutions_total()}",
        f"Подтверждённых пользователей: {status_counts.get('approved', 0)}",
        f"Заявок в ожидании: {status_counts.get('pending', 0)}",
        f"Забаненных пользователей: {status_counts.get('banned', 0)}",
    ]
    if confirm_stop:
        lines.extend([
            "",
            "Подтвердите остановку бота.",
        ])
    return "\n".join(lines)


def build_admin_panel_markup(confirm_stop: bool = False):
    markup = types.InlineKeyboardMarkup()
    markup.row(
        ui_button("🔒 Забанить", callback_data='admin_panel_ban', style="danger", icon_custom_emoji_id=CROSS_CUSTOM_EMOJI_ID),
        ui_button("🔓 Разбанить", callback_data='admin_panel_unban', style="success", icon_custom_emoji_id=CHECK_CUSTOM_EMOJI_ID)
    )
    markup.add(ui_button("📣 Рассылка", callback_data="admin_panel_broadcast", style="primary"))
    markup.add(ui_button("📦 Отправить бэкап", callback_data="admin_panel_backup", style="primary"))
    if confirm_stop:
        markup.row(
            ui_button("Подтвердить", callback_data='admin_panel_stop', style="danger", icon_custom_emoji_id=CROSS_CUSTOM_EMOJI_ID),
            ui_button("↩️ Отменить", callback_data='admin_panel_open', style="primary")
        )
    else:
        markup.add(ui_button("🛑 Остановить бота", callback_data="admin_panel_conf_stop", style="danger", icon_custom_emoji_id=CROSS_CUSTOM_EMOJI_ID))
    markup.add(ui_button("🏠 Главное меню", callback_data="mm_main_menu"))
    return markup


def parse_user_ids_text(text: str) -> tuple[list[int], list[str]]:
    valid_ids = []
    invalid_tokens = []
    for token in re.split(r"[\s,;]+", text.strip()):
        if not token:
            continue
        try:
            valid_ids.append(int(token))
        except ValueError:
            invalid_tokens.append(token)
    return valid_ids, invalid_tokens


def build_broadcast_preview_html(message) -> str:
    content_type_names = {
        "text": "Текст",
        "photo": "Фото",
        "document": "Документ",
        "video": "Видео",
        "audio": "Аудио",
        "voice": "Голосовое сообщение",
        "animation": "Анимация",
        "sticker": "Стикер",
    }
    preview_html = message.html_text or message.html_caption
    if preview_html:
        quoted = f"<blockquote>{preview_html}</blockquote>"
    else:
        quoted = "<blockquote><i>Сообщение без текста или подписи.</i></blockquote>"

    return (
        "<b>Подтвердите рассылку</b>\n"
        f"<b>Тип сообщения:</b> {html.escape(content_type_names.get(message.content_type, message.content_type))}\n"
        "Сообщение будет отправлено всем зарегистрированным пользователям в точности как оригинал.\n\n"
        f"{quoted}"
    )


def build_broadcast_confirm_markup(draft_id: int):
    markup = types.InlineKeyboardMarkup()
    markup.row(
        ui_button("Отправить всем", callback_data=f"admin_broadcast_confirm_{draft_id}", style="danger", icon_custom_emoji_id=CHECK_CUSTOM_EMOJI_ID),
        ui_button("Отменить", callback_data=f"admin_broadcast_cancel_{draft_id}", style="primary")
    )
    markup.add(ui_button("🔑 Панель админа", callback_data="admin_panel_open"))
    return markup


def build_solution_view_markup(solution_data: dict, viewer_id: int, page: int = 0):
    markup = types.InlineKeyboardMarkup()
    file_count = int(solution_data.get("file_count") or 0)
    if file_count:
        caption = "📎 Показать файл ещё раз" if file_count == 1 else f"📎 Показать файлы ещё раз ({file_count})"
        markup.add(ui_button(caption, callback_data=f"download_solution_file_{solution_data['answer_id']}"))
    if int(solution_data["student_id"]) == int(viewer_id) and solution_data["verdict"] is None:
        markup.add(ui_button("💔 Отменить", callback_data=f"self_reject_{solution_data['answer_id']}_{page}", style="danger", icon_custom_emoji_id=CROSS_CUSTOM_EMOJI_ID))
    if int(solution_data["student_id"]) == int(viewer_id) and solution_data["verdict"] == "self_reject":
        markup.add(ui_button("❤️‍🩹 Восстановить", callback_data=f"undo_self_reject_{solution_data['answer_id']}_{page}", style="success", icon_custom_emoji_id=CHECK_CUSTOM_EMOJI_ID))
    markup.add(ui_button("🗂 Все решения", callback_data=f"mm_answers_{page}"))
    return markup


def build_check_solution_markup(solution_data: dict, check_type: str):
    answer_id = solution_data["answer_id"]
    markup = types.InlineKeyboardMarkup()
    markup.row(
        ui_button("Принять", callback_data=f"check-final_accept_{answer_id}", style="success", icon_custom_emoji_id=CHECK_CUSTOM_EMOJI_ID),
        ui_button("Отклонить", callback_data=f"check-final_reject_{answer_id}", style="danger", icon_custom_emoji_id=CROSS_CUSTOM_EMOJI_ID)
    )
    markup.add(ui_button("✍️ Добавить комментарий", callback_data=f"check-add-comment_{check_type}_{answer_id}", style="primary"))
    file_count = int(solution_data.get("file_count") or 0)
    if file_count:
        caption = "📎 Показать файл ещё раз" if file_count == 1 else f"📎 Показать файлы ещё раз ({file_count})"
        markup.add(ui_button(caption, callback_data=f"download_solution_file_{answer_id}"))
    markup.add(ui_button("⬅️ К проверке", callback_data="mm_check_0"))
    return markup


def get_notifiable_student_ids(course_id: int) -> list[int]:
    result = []
    raw_ids = sql_return.students_list(course_id).split()
    for student_id in raw_ids:
        try:
            student_id_int = int(student_id)
        except ValueError:
            continue
        user = sql_return.find_user_id(student_id_int)
        if user and user[3] == "approved":
            result.append(student_id_int)
    return result


def build_lesson_notification_markup(course_id: int, lesson_id: int, has_file: bool):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📘 Открыть урок", callback_data=f"lesson_{course_id}_{lesson_id}_0"))
    if has_file:
        markup.add(types.InlineKeyboardButton("📎 Получить файл", callback_data=f"download_lesson_file_{course_id}_{lesson_id}"))
    return markup


def send_new_lesson_notifications(lesson_data, source: str = "scanner") -> int:
    lesson_id = int(lesson_data[0])
    course_id = int(lesson_data[1])
    course = sql_return.find_course_id(course_id)
    if not course:
        sql_return.mark_lesson_notified(lesson_id, course_id, 0, f"{source}:missing_course")
        return 0

    lesson_title = str(lesson_data[2])
    lesson_file_id = get_lesson_file_id(lesson_data)
    course_title = str(course[1])
    student_ids = get_notifiable_student_ids(course_id)

    text = (
        f"📚 В курсе <b>{html.escape(course_title)}</b> появился новый урок.\n\n"
        f"<b>Урок:</b> {html.escape(lesson_title)}"
    )
    if lesson_file_id:
        text += "\n📎 К уроку прикреплён файл."

    markup = build_lesson_notification_markup(course_id, lesson_id, bool(lesson_file_id))
    sent_count = 0
    for student_id in student_ids:
        try:
            bot.send_message(student_id, text, parse_mode="HTML", reply_markup=markup)
            sent_count += 1
        except Exception as error:
            log(f"lesson notification failed: lesson_id={lesson_id} student_id={student_id} error={error}")

    sql_return.mark_lesson_notified(lesson_id, course_id, sent_count, source)
    sql_return.log_action(0, "lesson_notifications_sent", f"{lesson_id} {course_id} {sent_count} {source}")
    return sent_count


def process_pending_lesson_notifications(source: str = "scanner") -> int:
    if not lesson_notifications_lock.acquire(blocking=False):
        return 0

    try:
        pending_lessons = sql_return.get_unnotified_lessons()
        processed = 0
        for lesson_data in pending_lessons:
            send_new_lesson_notifications(lesson_data, source)
            processed += 1
        return processed
    finally:
        lesson_notifications_lock.release()


def lesson_notification_scheduler():
    while is_polling:
        try:
            process_pending_lesson_notifications("background")
        except Exception as error:
            log(f"lesson notification scheduler error: {error}")

        slept = 0
        while is_polling and slept < LESSON_NOTIFICATION_POLL_SECONDS:
            time.sleep(1)
            slept += 1


def get_gpt_sql_review_markup(request_id: int):
    markup = types.InlineKeyboardMarkup()
    markup.row(
        ui_button("Применить", callback_data=f"gptsql_accept_{request_id}", style="success", icon_custom_emoji_id=CHECK_CUSTOM_EMOJI_ID),
        ui_button("Отклонить", callback_data=f"gptsql_reject_{request_id}", style="danger", icon_custom_emoji_id=CROSS_CUSTOM_EMOJI_ID)
    )
    markup.add(ui_button("Отправить в ChatGPT повторно", callback_data=f"gptsql_retry_{request_id}", style="primary", icon_custom_emoji_id=CHATGPT_CUSTOM_EMOJI_ID))
    return markup


def format_sql_preview(sql_text: str, max_lines: int = 28, max_line_len: int = 180) -> str:
    preview_lines = []
    lines = str(sql_text or "").splitlines()

    for line in lines[:max_lines]:
        if len(line) > max_line_len:
            preview_lines.append(line[:max_line_len - 3] + "...")
        else:
            preview_lines.append(line)

    remaining = len(lines) - min(len(lines), max_lines)
    if remaining > 0:
        preview_lines.append(f"-- ... и ещё {remaining} строк(и)")

    return "\n".join(preview_lines).strip() or "-- пустой SQL --"


def send_gpt_sql_for_review(request_id: int, admin_feedback: str | None = None):
    with gpt_sql_requests_lock:
        request = gpt_sql_requests.get(request_id)
    if not request:
        return

    admin_id = get_admin_id()
    course_title = get_course_title(request["course_id"])
    user_name = sql_return.get_user_name(request["initiator_id"])
    initiator_text = f"{request['initiator_id']}"
    if user_name:
        initiator_text = f"{user_name[0]} {user_name[1]} ({request['initiator_id']})"

    file_caption = f"Заявка #{request_id}\nКурс: {course_title}\nОтправил: {initiator_text}"
    try:
        if request["file_type"] == "photo":
            with open(request["file_path"], "rb") as photo:
                bot.send_photo(admin_id, photo, caption=file_caption)
        else:
            with open(request["file_path"], "rb") as document:
                bot.send_document(
                    admin_id,
                    document,
                    visible_file_name=request["original_file_name"],
                    caption=file_caption
                )
    except Exception as error:
        bot.send_message(admin_id, f"⚠️ Не удалось приложить файл к заявке #{request_id}: {error}")

    sql_text = request.get("sql")
    if not sql_text:
        bot.send_message(admin_id, f"⚠️ У заявки #{request_id} отсутствует SQL.")
        return

    review_title = f"<b>Проверка SQL для заявки #{request_id}</b>\n<b>Курс:</b> {html.escape(course_title)}\n<b>Отправил:</b> {html.escape(initiator_text)}"
    if admin_feedback:
        review_title += f"\n<b>Комментарий для исправления:</b> {html.escape(admin_feedback)}"

    preview_text = format_sql_preview(sql_text)
    review_text = f"{review_title}\n\n<pre>{html.escape(preview_text)}</pre>"

    if len(review_text) > 3700 or sql_text.count("\n") > 30:
        sql_file = io.BytesIO(sql_text.encode("utf-8"))
        sql_file.name = f"gpt_lesson_request_{request_id}.sql"
        bot.send_document(admin_id, sql_file, caption=f"Полный SQL для заявки #{request_id}")
        review_text = f"{review_title}\n\n<pre>{html.escape(format_sql_preview(sql_text, max_lines=16, max_line_len=140))}</pre>\n\nПолный SQL отправлен отдельным `.sql`-файлом."

    bot.send_message(
        admin_id,
        review_text,
        parse_mode="HTML",
        reply_markup=get_gpt_sql_review_markup(request_id)
    )


def run_gpt_sql_generation(request_id: int, admin_feedback: str | None = None):
    with gpt_sql_requests_lock:
        request = gpt_sql_requests.get(request_id)
        if not request:
            return
        request["status"] = "processing"
        course_id = request["course_id"]
        file_path = request["file_path"]
        previous_sql = request.get("sql")
        initiator_id = request["initiator_id"]

    try:
        if admin_feedback:
            sql_text, sql_payload = parsing_gpt.fix_lesson_sql(
                lesson_file_path=file_path,
                course_id=course_id,
                previous_sql=previous_sql or "",
                admin_feedback=admin_feedback,
            )
        else:
            sql_text, sql_payload = parsing_gpt.generate_lesson_sql(
                lesson_file_path=file_path,
                course_id=course_id,
            )
    except Exception as error:
        with gpt_sql_requests_lock:
            request = gpt_sql_requests.get(request_id)
            if request:
                request["status"] = "error"

        error_text = f"{type(error).__name__}: {error}"
        bot.send_message(
            initiator_id,
            f"{CROSS_HTML} Не удалось подготовить SQL от ChatGPT: {html.escape(error_text)}",
            parse_mode="HTML"
        )
        if initiator_id != get_admin_id():
            bot.send_message(
                get_admin_id(),
                f"{CROSS_HTML} Ошибка ChatGPT/SQL в заявке #{request_id}: {html.escape(error_text)}",
                parse_mode="HTML"
            )
        return

    with gpt_sql_requests_lock:
        request = gpt_sql_requests.get(request_id)
        if not request:
            return
        request["status"] = "awaiting_admin"
        request["sql"] = sql_text
        request["sql_payload"] = sql_payload
        if admin_feedback:
            request["last_feedback"] = admin_feedback

    send_gpt_sql_for_review(request_id, admin_feedback)
    if admin_feedback:
        bot.send_message(initiator_id, f"🔁 SQL по заявке #{request_id} исправлен и снова отправлен администратору.")
    else:
        bot.send_message(
            initiator_id,
            f"{CHECK_HTML} SQL по заявке #{request_id} отправлен администратору на проверку.",
            parse_mode="HTML"
        )


def gpt_add_lesson_start(call, course_id: int):
    if not can_use_gpt_lesson_button(call.from_user.id):
        bot.send_message(call.message.chat.id, "У вас нет доступа к этой функции.")
        return
    if not sql_return.find_course_id(course_id):
        bot.send_message(call.message.chat.id, "Курс не найден.")
        return

    bot.edit_message_text(
        "Отправьте фото листка или PDF с задачами.\n\n"
        f"После загрузки я отправлю файл в {CHATGPT_HTML} и подготовлю SQL для проверки админом.\n"
        "Для отмены отправьте /cancel.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="HTML"
    )
    bot.register_next_step_handler(call.message, gpt_add_lesson_receive_file, course_id)


def gpt_add_lesson_receive_file(message, course_id: int):
    log_user_action(
        message.from_user,
        "gpt_lesson.file_upload_input",
        f"course_id={course_id}, content_type={message.content_type}"
    )
    if message.content_type == "text":
        command = (message.text or "").strip().lower()
        if command in ["/cancel", "cancel", "отмена"]:
            bot.send_message(message.chat.id, "Действие отменено.")
            return
        bot.send_message(message.chat.id, "Нужно отправить фото листка или PDF-файл. Для отмены отправьте /cancel.")
        bot.register_next_step_handler(message, gpt_add_lesson_receive_file, course_id)
        return

    if message.content_type not in ("photo", "document"):
        bot.send_message(message.chat.id, "Нужно отправить фото листка или PDF-файл. Для отмены отправьте /cancel.")
        bot.register_next_step_handler(message, gpt_add_lesson_receive_file, course_id)
        return

    try:
        file_data = save_lesson_source_file(message)
    except ValueError as error:
        bot.send_message(message.chat.id, str(error))
        bot.register_next_step_handler(message, gpt_add_lesson_receive_file, course_id)
        return
    except Exception as error:
        bot.send_message(message.chat.id, f"Ошибка при сохранении файла: {error}")
        return

    request_id = next_gpt_sql_request_id()
    with gpt_sql_requests_lock:
        gpt_sql_requests[request_id] = {
            "id": request_id,
            "course_id": course_id,
            "initiator_id": message.from_user.id,
            "file_path": file_data["file_path"],
            "file_type": file_data["file_type"],
            "stored_file_name": file_data["stored_file_name"],
            "original_file_name": file_data["original_file_name"],
            "sql": "",
            "sql_payload": None,
            "status": "queued",
            "created_at": time.time(),
        }

    sql_return.log_action(
        message.from_user.id,
        "gpt_lesson_request_created",
        f"{request_id} {course_id} {file_data['stored_file_name']}"
    )

    bot.send_message(
        message.chat.id,
        f"Файл получен. Запускаю {CHATGPT_HTML} и готовлю SQL (заявка #{request_id}). Это может занять до минуты.",
        parse_mode="HTML"
    )
    Thread(target=run_gpt_sql_generation, args=(request_id,), daemon=True).start()


def gpt_sql_accept(call, request_id: int):
    if call.from_user.id != get_admin_id():
        bot.send_message(call.message.chat.id, "Только админ может подтверждать такие заявки.")
        return

    with gpt_sql_requests_lock:
        request = gpt_sql_requests.get(request_id)
    if not request:
        bot.send_message(call.message.chat.id, f"Заявка #{request_id} уже обработана или не найдена.")
        return

    sql_text = request.get("sql")
    sql_payload = request.get("sql_payload")
    if not sql_text or not sql_payload:
        bot.send_message(call.message.chat.id, f"В заявке #{request_id} нет SQL для применения.")
        return

    try:
        lesson_id, task_ids = sql_return.create_lesson_with_tasks(
            request["course_id"],
            sql_payload["lesson_title"],
            sql_payload["tasks"],
        )
    except Exception as error:
        bot.send_message(
            call.message.chat.id,
            f"{CROSS_HTML} Ошибка применения SQL по заявке #{request_id}: {html.escape(str(error))}",
            parse_mode="HTML"
        )
        return

    with gpt_sql_requests_lock:
        gpt_sql_requests.pop(request_id, None)

    sql_return.log_action(
        call.from_user.id,
        "gpt_lesson_request_accepted",
        f"{request_id} lesson_id={lesson_id} tasks={len(task_ids)}"
    )
    bot.send_message(
        call.message.chat.id,
        f"{CHECK_HTML} SQL из заявки #{request_id} применён.\nУрок ID: {lesson_id}\nЗадач добавлено: {len(task_ids)}",
        parse_mode="HTML"
    )
    Thread(target=process_pending_lesson_notifications, args=("gpt_sql_accept",), daemon=True).start()

    if request["initiator_id"] != call.from_user.id:
        bot.send_message(
            request["initiator_id"],
            f"{CHECK_HTML} Админ подтвердил заявку #{request_id}. SQL применён, урок добавлен в базу.",
            parse_mode="HTML"
        )


def gpt_sql_reject(call, request_id: int):
    if call.from_user.id != get_admin_id():
        bot.send_message(call.message.chat.id, "Только админ может отклонять такие заявки.")
        return

    with gpt_sql_requests_lock:
        request = gpt_sql_requests.pop(request_id, None)

    if not request:
        bot.send_message(call.message.chat.id, f"Заявка #{request_id} уже обработана или не найдена.")
        return

    sql_return.log_action(call.from_user.id, "gpt_lesson_request_rejected", f"{request_id}")
    bot.send_message(call.message.chat.id, f"🗑 Заявка #{request_id} отклонена.")

    if request["initiator_id"] != call.from_user.id:
        bot.send_message(
            request["initiator_id"],
            f"{CROSS_HTML} Админ отклонил заявку #{request_id}.",
            parse_mode="HTML"
        )


def gpt_sql_retry(call, request_id: int):
    if call.from_user.id != get_admin_id():
        bot.send_message(call.message.chat.id, "Только админ может отправлять такие заявки на доработку.")
        return

    with gpt_sql_requests_lock:
        request = gpt_sql_requests.get(request_id)
    if not request:
        bot.send_message(call.message.chat.id, f"Заявка #{request_id} уже обработана или не найдена.")
        return

    bot.send_message(
        call.message.chat.id,
        f"Введите комментарий с ошибками для заявки #{request_id}. "
        f"Я отправлю его в {CHATGPT_HTML} для исправления SQL.\nДля отмены отправьте /cancel.",
        parse_mode="HTML"
    )
    bot.register_next_step_handler(call.message, gpt_sql_retry_feedback, request_id)


def gpt_sql_retry_feedback(message, request_id: int):
    log_user_action(
        message.from_user,
        "gpt_lesson.retry_feedback_input",
        f"request_id={request_id}, text={message.text or ''}"
    )
    if message.from_user.id != get_admin_id():
        bot.send_message(message.chat.id, "Только админ может отправлять такие заявки на доработку.")
        return

    feedback = (message.text or "").strip()
    if feedback.lower() in ["/cancel", "cancel", "отмена"]:
        bot.send_message(message.chat.id, "Повторная проверка отменена.")
        return
    if not feedback:
        bot.send_message(message.chat.id, "Комментарий пустой. Отправьте текст ошибки или /cancel.")
        bot.register_next_step_handler(message, gpt_sql_retry_feedback, request_id)
        return

    with gpt_sql_requests_lock:
        request = gpt_sql_requests.get(request_id)
        if not request:
            bot.send_message(message.chat.id, f"Заявка #{request_id} уже обработана или не найдена.")
            return
        if not request.get("sql"):
            bot.send_message(message.chat.id, f"В заявке #{request_id} пока нет SQL для исправления.")
            return

    sql_return.log_action(message.from_user.id, "gpt_lesson_request_retry", f"{request_id} {feedback}")
    bot.send_message(
        message.chat.id,
        f"🔄 Запросил исправление SQL у {CHATGPT_HTML} для заявки #{request_id}.",
        parse_mode="HTML"
    )
    Thread(target=run_gpt_sql_generation, args=(request_id, feedback), daemon=True).start()


def build_main_menu_only_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(ui_button("🏠 Главное меню", callback_data="mm_main_menu"))
    return markup


def close_solution_submission_prompt(session: dict, text: str, reply_markup=None):
    if not session:
        return
    try:
        bot.edit_message_text(
            text,
            chat_id=session["chat_id"],
            message_id=session["prompt_message_id"],
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    except Exception:
        pass


def notify_solution_reviewers(course_id: int, user_id: int):
    user_name = sql_return.get_user_name(user_id) or ("Неизвестный", "пользователь")
    reviewer_ids = []
    for raw_id in sql_return.developers_list(course_id).split():
        try:
            reviewer_ids.append(int(raw_id))
        except ValueError:
            continue
    for reviewer_id in reviewer_ids:
        bot.send_message(
            reviewer_id,
            f"Поступило новое решение для проверки от {user_name[0]} {user_name[1]}"
        )


def finalize_solution_submission(user_id: int) -> tuple[dict | None, int | None, str | None]:
    session = mark_solution_submission_finalizing(user_id)
    if not session:
        return None, None, "Активная сдача решения не найдена."

    answer_text = build_solution_answer_text(session)
    attachments = sorted(session.get("attachments") or [], key=lambda item: item.get("message_id", 0))

    if not answer_text and not attachments:
        update_solution_submission_session(user_id, lambda current: current.update({"status": "collecting"}))
        return session, None, "Нужно добавить текст решения или хотя бы один файл."

    saved_files = []
    try:
        file_ids = []
        for attachment in attachments:
            file_data = save_solution_attachment_file(attachment, user_id)
            saved_files.append(file_data)
            file_ids.append(file_data["file_id"])

        answer_id = sql_return.new_student_answer(
            session["task_id"],
            user_id,
            answer_text or None,
            file_ids=file_ids,
        )
    except ValueError as error:
        cleanup_saved_solution_files(saved_files)
        update_solution_submission_session(user_id, lambda current: current.update({"status": "collecting"}))
        return session, None, str(error)
    except Exception as error:
        cleanup_saved_solution_files(saved_files)
        update_solution_submission_session(user_id, lambda current: current.update({"status": "collecting"}))
        return session, None, f"Не удалось сохранить решение: {error}"

    cancel_solution_submission_session(user_id)
    try:
        notify_solution_reviewers(session["course_id"], user_id)
    except Exception:
        pass
    sql_return.log_action(user_id, "send_final", f"{session['task_id']} answer_id={answer_id} files={len(file_ids)}")
    return session, answer_id, None


def append_solution_submission_text(user_id: int, message_id: int, text: str) -> bool:
    stored = {"updated": False}
    clean_text = str(text or "").strip()
    if not clean_text:
        return False

    def updater(session):
        processed = session.setdefault("processed_message_ids", set())
        if message_id in processed:
            return
        processed.add(message_id)
        session.setdefault("text_chunks", []).append(clean_text)
        stored["updated"] = True

    update_solution_submission_session(user_id, updater)
    return stored["updated"]


def append_solution_submission_attachment(user_id: int, message) -> tuple[bool, str | None]:
    if message.content_type == "photo":
        if not message.photo:
            return False, "Не удалось прочитать фотографию."
        telegram_file_id = message.photo[-1].file_id
        original_file_name = f"solution_photo_{message.message_id}.jpg"
    elif message.content_type == "document":
        if not message.document:
            return False, "Не удалось прочитать документ."
        telegram_file_id = message.document.file_id
        original_file_name = message.document.file_name or f"solution_document_{message.message_id}"
    else:
        return False, "К решению можно прикреплять только фото и документы."

    try:
        file_info = bot.get_file(telegram_file_id)
    except Exception:
        return False, "Не удалось получить данные файла из Telegram. Попробуйте отправить его ещё раз."

    if file_info.file_size > MAX_UPLOAD_SIZE_BYTES:
        return False, "Файл слишком большой. Максимальный размер - 15 МБ."

    stored = {"updated": False, "error": None}

    def updater(session):
        processed = session.setdefault("processed_message_ids", set())
        if message.message_id in processed:
            return
        processed.add(message.message_id)

        session.setdefault("attachments", []).append({
            "message_id": message.message_id,
            "content_type": message.content_type,
            "telegram_file_id": telegram_file_id,
            "original_file_name": original_file_name,
            "media_group_id": message.media_group_id,
            "validated_size": file_info.file_size,
        })

        caption = (message.caption or "").strip()
        if caption:
            session.setdefault("text_chunks", []).append(caption)
        stored["updated"] = True

    update_solution_submission_session(user_id, updater)
    return stored["updated"], stored["error"]


def cancel_solution_submission_from_message(message, reopen_start: bool = False):
    session = cancel_solution_submission_session(message.from_user.id)
    if session:
        close_solution_submission_prompt(
            session,
            f"{CROSS_HTML} Сдача решения отменена.",
            reply_markup=build_main_menu_only_markup(),
        )
    if reopen_start:
        start(message)
    else:
        bot.send_message(message.chat.id, "Сдача решения отменена.", reply_markup=build_main_menu_only_markup())


@bot.message_handler(
    func=lambda message: has_active_solution_submission(message.from_user.id),
    content_types=[
        "text", "photo", "document", "audio", "video", "voice", "animation",
        "sticker", "location", "contact", "poll"
    ],
)
def handle_active_solution_submission(message):
    log_user_action(
        message.from_user,
        "solution.submit_collect",
        f"content_type={message.content_type}"
    )

    session = get_solution_submission_session(message.from_user.id)
    if not session:
        return

    if message.chat.id != session["chat_id"]:
        return

    if message.content_type == "text":
        command = (message.text or "").strip()
        lowered = command.lower()

        if lowered in {"/cancel", "/stop", "cancel", "stop"}:
            cancel_solution_submission_from_message(message)
            return
        if lowered == "/start":
            cancel_solution_submission_from_message(message, reopen_start=True)
            return
        if lowered in {"/done", "/finish", "готово"}:
            session_snapshot, answer_id, error_text = finalize_solution_submission(message.from_user.id)
            if error_text:
                bot.send_message(message.chat.id, error_text)
                refresh_solution_submission_prompt(message.from_user.id)
                return
            close_solution_submission_prompt(
                session_snapshot,
                f"{CHECK_HTML} Решение #{answer_id} отправлено на проверку.",
                reply_markup=build_main_menu_only_markup(),
            )
            bot.send_message(message.chat.id, "Решение отправлено на проверку", reply_markup=build_main_menu_only_markup())
            return
        if command.startswith("/"):
            bot.send_message(message.chat.id, "Во время сдачи используйте /done для отправки или /cancel для отмены.")
            return

        if append_solution_submission_text(message.from_user.id, message.message_id, command):
            refresh_solution_submission_prompt(message.from_user.id)
        return

    if message.content_type not in SOLUTION_SUBMISSION_ALLOWED_CONTENT_TYPES:
        bot.send_message(message.chat.id, "Во время сдачи решения поддерживаются только текст, фото и документы.")
        return

    stored, error_text = append_solution_submission_attachment(message.from_user.id, message)
    if error_text:
        bot.send_message(message.chat.id, error_text)
        return
    if stored:
        refresh_solution_submission_prompt(message.from_user.id)

@bot.message_handler(commands=["start"])
def start(message):
    log_user_action(message.from_user, "command.start")
    cancel_solution_submission_session(message.from_user.id)
    user = sql_return.find_user_id(message.from_user.id)
    if user and user[3] == "pending":
        bot.reply_to(message, "Вы уже подали заявку, ожидайте ответа администратора.")
    elif user and user[3] == "approved":
        bot.reply_to(
            message,
            f"""Здравствуйте, {message.from_user.first_name}!""",
            reply_markup=build_main_menu_markup(message.from_user.id)
        )
    elif user and user[3] == "banned":
        bot.reply_to(message, "Вы были забанены. Обратитесь к администратору")
    else:
        bot.reply_to(message, f"""Здравcтвуйте! Сейчас вы будете проходить регистрацию. Пожалуйста введите своё <b>имя</b> и <b>фамилию</b> (<u>обязательно в таком порядке</u>)\n\nПример: "Артём Гусев".""", parse_mode="HTML")
        bot.register_next_step_handler(message, register_name)

def register_name(message):
    raw_name = (message.text or "").strip()
    log_user_action(message.from_user, "registration.name_input", f"text={raw_name}")
    name = raw_name.split()
    if len(name) != 2:
        bot.reply_to(message, f"Вы ввели имя и фамилию неправильно. Введите их снова.")
        bot.register_next_step_handler(message, register_name)
        sql_return.log_action(message.from_user.id, "register_invalid_name", raw_name)
    else:
        sql_return.reg_user(int(message.from_user.id), name[0], name[1])

        bot.reply_to(message, "Мы отправили сообщение администратору. Теперь ожидайте подтверждения.")
        markup = types.InlineKeyboardMarkup()
        button1 = ui_button("Принять", callback_data=f'reg_approve_{message.from_user.id}', style="success", icon_custom_emoji_id=CHECK_CUSTOM_EMOJI_ID)
        button2 = ui_button("Отклонить", callback_data=f'reg_deny_{message.from_user.id}', style="danger", icon_custom_emoji_id=CROSS_CUSTOM_EMOJI_ID)
        button3 = ui_button("Забанить", callback_data=f'reg_ban_{message.from_user.id}', style="danger", icon_custom_emoji_id=CROSS_CUSTOM_EMOJI_ID)
        markup.add(button1)
        markup.add(button2, button3)
        bot.send_message(int(config["admin_id"]), f"@{message.from_user.username} ({message.from_user.id}) регистрируется как {name[0]} {name[1]}", reply_markup=markup)
        sql_return.log_action(message.from_user.id, "register", f"{name[0]} {name[1]}")

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    callback_data = call.data or ""
    log_user_action(
        call.from_user,
        callback_action_name(callback_data),
        f"callback_data={callback_data}"
    )

    user = sql_return.find_user_id(call.from_user.id)
    if user and user[3] == "banned":
        bot.answer_callback_query(call.id, "Вы были забанены. Обратитесь к администратору")
        return
    
    user_id = call.data.split('_')[-1]
    if call.data.startswith("reg_approve_"):
        sql_return.set_user_status(user_id, "approved")
        bot.send_message(user_id, "Ваша регистрация была одобрена! Введите /start для попадания в главное меню или /help для помощи.")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        sql_return.log_action(call.from_user.id, "approve_register", f"{user_id}")
    elif call.data.startswith("reg_deny_"):
        sql_return.delete_user(user_id)
        bot.send_message(user_id, "Ваша заявка была отклонена. Вы можете подать её снова.")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        sql_return.log_action(call.from_user.id, "deny_register", f"{user_id}")
    elif call.data.startswith("reg_ban_"):
        sql_return.set_user_status(user_id, "banned")
        bot.send_message(user_id, "Вы были забанены и не можете подать заявку снова. Рекомендую обратиться к администратору")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        sql_return.log_action(call.from_user.id, "ban_register", f"{user_id}")
    elif call.data.startswith("mm_send"):
        mm_send(call)
    elif call.data.startswith("mm_check"):
        mm_check(call, int(call.data.split("_")[-1]))
    elif call.data.startswith("mm_courses_"):
        mm_courses(call, int(call.data.split('_')[-1]))
    elif call.data.startswith("mm_answers_"):
        mm_answers(call, int(call.data.split('_')[-1]))
        # all_solutions(call, int(call.data.split("_")[-1]))
    elif call.data.startswith("mm_main_menu"):
        cancel_solution_submission_session(call.from_user.id)
        user = sql_return.find_user_id(call.from_user.id)

        if user and user[3] == "pending":
            bot.edit_message_text("Вы уже подали заявку, ожидайте ответа администратора.", chat_id=call.message.chat.id, message_id=call.message.message_id)
        elif user and user[3] == "approved":
            bot.edit_message_text(
                f"""Здравствуйте, {call.from_user.first_name}!""",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=build_main_menu_markup(call.from_user.id)
            )
        elif user and user[3] == "banned":
            bot.edit_message_text("Вы были забанены. Обратитесь к администратору", chat_id=call.message.chat.id, message_id=call.message.message_id)
        else:
            bot.edit_message_text(f"""Здравcтвуйте! Сейчас вы будете проходить регистрацию. Пожалуйста, введите своё <b>имя</b> и <b>фамилию</b> (<u>обязательно в таком порядке</u>)\n\nПример: "Артём Гусев".""", parse_mode="HTML", chat_id=call.message.chat.id, message_id=call.message.message_id)
            bot.register_next_step_handler(call.message, register_name)
    elif call.data.startswith("course_"):
        course_info(call)
    elif call.data.startswith("add_student_"):
        add_student(call)
    elif call.data.startswith("add_developer_"):
        add_developer(call)
    elif call.data.startswith("content_"):
        course_content(call, int(call.data.split('_')[-2]), int(call.data.split("_")[-1]))
    elif call.data.startswith("gpt_add_lesson_"):
        gpt_add_lesson_start(call, int(call.data.split("_")[-1]))
    elif call.data.startswith("attach_lesson_file_"):
        attach_lesson_file(
            call,
            int(call.data.split('_')[-2]),
            int(call.data.split('_')[-1]),
        )
    elif call.data.startswith("download_lesson_file_"):
        download_lesson_file(
            call,
            int(call.data.split('_')[-2]),
            int(call.data.split('_')[-1]),
        )
    elif call.data.startswith("download_solution_file_"):
        download_solution_file(call, int(call.data.split('_')[-1]))
    elif call.data.startswith("toggle_task_"):
        toggle_task_open_close(
            call,
            int(call.data.split('_')[-3]),
            int(call.data.split('_')[-2]),
            int(call.data.split('_')[-1]),
        )
    elif call.data.startswith("lesson_"):
        lesson_content(call, int(call.data.split('_')[-3]), int(call.data.split('_')[-2]), int(call.data.split("_")[-1]))
    elif call.data.startswith("task_"):
        task_info(call, int(call.data.split("_")[-3]), int(call.data.split("_")[-2]), int(call.data.split("_")[-1]))
    elif call.data.startswith("send-course_"):
        mm_send_lesson(call=call, course_id=int(call.data.split("_")[-2]), page=int(call.data.split("_")[-1]))
    elif call.data.startswith("send-task_"):
        mm_send_task(call, int(call.data.split("_")[-3]), int(call.data.split("_")[-2]), int(call.data.split("_")[-1]))
    elif call.data.startswith("send-final_"):
        mm_send_final(call, int(call.data.split("_")[-3]), int(call.data.split("_")[-2]), int(call.data.split("_")[-1]))
    elif call.data.startswith("check-course-all_"):
        check_all(call)
    elif call.data.startswith("check-course_"):
        check_course(call, int(call.data.split("_")[-1]))
    elif call.data.startswith("check-add-comment_"):
        bot.send_message(call.message.chat.id, "Введите комментарий (для пустого комментария введите \"None\")")
        bot.register_next_step_handler(call.message, check_add_comment, call, call.data.split("_")[-2], int(call.data.split("_")[-1]))
        # "check-add-comment_{type}_{task_data[0]}"
    elif call.data.startswith("check-final"):
        check_final(call, int(call.data.split("_")[-1]), call.data.split("_")[-2])
        # "check-final_accept_{task_data[0]"
        # "check-final_reject_{task_data[0]}"
    elif call.data.startswith("create_course"):
        create_course(call)
    elif call.data.startswith("create_lesson"):
        create_lesson(call)
    elif call.data.startswith("create_task"):
        create_task(call)
    elif call.data.startswith("solution_submit_finish"):
        session_snapshot, answer_id, error_text = finalize_solution_submission(call.from_user.id)
        if error_text:
            bot.send_message(call.message.chat.id, error_text)
            refresh_solution_submission_prompt(call.from_user.id)
        else:
            close_solution_submission_prompt(
                session_snapshot,
                f"{CHECK_HTML} Решение #{answer_id} отправлено на проверку.",
                reply_markup=build_main_menu_only_markup(),
            )
            bot.send_message(call.message.chat.id, "Решение отправлено на проверку", reply_markup=build_main_menu_only_markup())
    elif call.data.startswith("solution_submit_cancel"):
        session = cancel_solution_submission_session(call.from_user.id)
        if session:
            close_solution_submission_prompt(
                session,
                f"{CROSS_HTML} Сдача решения отменена.",
                reply_markup=build_main_menu_only_markup(),
            )
        bot.send_message(call.message.chat.id, "Сдача решения отменена.", reply_markup=build_main_menu_only_markup())
    elif call.data.startswith("solution"):
        parts = call.data.split("_")
        answer_id = int(parts[1]) if len(parts) > 2 else int(parts[-1])
        page = int(parts[2]) if len(parts) > 2 else 0
        solution(call, answer_id, page)
    elif call.data.startswith("self_reject"):
        parts = call.data.split("_")
        answer_id = int(parts[2]) if len(parts) > 3 else int(parts[-1])
        page = int(parts[3]) if len(parts) > 3 else 0
        self_reject(call, answer_id, page)
    elif call.data.startswith("undo_self_reject"):
        parts = call.data.split("_")
        answer_id = int(parts[3]) if len(parts) > 4 else int(parts[-1])
        page = int(parts[4]) if len(parts) > 4 else 0
        self_reject(call, answer_id, page, True)
    elif call.data.startswith("admin_panel_open"):
        admin_panel(call)
    elif call.data.startswith("admin_panel_backup"):
        admin_backup(call)
    elif call.data.startswith("admin_panel_broadcast"):
        admin_broadcast_start(call)
    elif call.data.startswith("admin_panel_stop"):
        stop(call)
    elif call.data.startswith("admin_panel_ban"):
        ban(call)
    elif call.data.startswith("admin_panel_unban"):
        unban(call)
    elif call.data.startswith("admin_panel_conf_stop"):
        stop_confirm(call)
    elif call.data.startswith("admin_broadcast_confirm_"):
        admin_broadcast_confirm(call, int(call.data.split("_")[-1]))
    elif call.data.startswith("admin_broadcast_cancel_"):
        admin_broadcast_cancel(call, int(call.data.split("_")[-1]))
    elif call.data.startswith("gptsql_accept_"):
        gpt_sql_accept(call, int(call.data.split("_")[-1]))
    elif call.data.startswith("gptsql_reject_"):
        gpt_sql_reject(call, int(call.data.split("_")[-1]))
    elif call.data.startswith("gptsql_retry_"):
        gpt_sql_retry(call, int(call.data.split("_")[-1]))
    elif call.data.startswith("stats_"):
        if not can_use_vpn_stats(call.from_user.id):
            bot.answer_callback_query(call.id, "no access")
            return

        unit = call.data.split("_", 1)[1]
        msg = build_vpn_stats(unit)
        try:
            bot.edit_message_text(
                msg,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=get_vpn_stats_keyboard(),
                parse_mode="HTML"
            )
        except Exception as e:
            if "message is not modified" not in str(e).lower():
                raise
    else:
        bot.answer_callback_query(call.id, "Обработчика для этой кнопки не существует.")
        bot.send_message(config["admin_id"], f"{call.from_user.id} ({call.from_user.username}; {sql_return.get_user_name(call.from_user.id)[0]} {sql_return.get_user_name(call.from_user.id)[1]}) использовал неизвестную кнопку: {call.data}")
        sql_return.log_action(call.from_user.id, "unknown_action", f"{call.data}")
    
    bot.answer_callback_query(call.id)

def mm_send(call, page=0):
    user = sql_return.find_user_id(call.from_user.id)

    if not user:
        bot.send_message(call.message.chat.id, "Вы не зарегистрированы.")
        return

    is_admin = (user[3] == "approved" and str(call.from_user.id) == config["admin_id"])

    all_courses = sql_return.all_courses()

    student_courses = []
    
    for course in all_courses:
        student_ids = course[3] if course[3] else ""
        developer_ids = course[4] if course[4] else ""
        
        if str(call.from_user.id) in student_ids.split():
            student_courses.append(course)

    filtered_courses = student_courses

    courses_per_page = 8
    total_pages = (len(filtered_courses) + courses_per_page - 1) // courses_per_page
    page_courses = filtered_courses[page * courses_per_page:(page + 1) * courses_per_page]

    markup = types.InlineKeyboardMarkup()
    for course in page_courses:
        markup.add(types.InlineKeyboardButton(f"👨‍🎓 {course[1]}", callback_data=f'send-course_{course[0]}_0'))

    navigation = []
    if page > 0:
        navigation.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f'mm_send_{page - 1}'))
    if page < total_pages - 1:
        navigation.append(types.InlineKeyboardButton("➡️ Вперед", callback_data=f'mm_send_{page + 1}'))

    markup.row(*navigation)
    markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="mm_main_menu"))
    bot.edit_message_text(f"Выберите курс для сдачи задания\nСтраница {page + 1} из {total_pages}:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

def mm_send_lesson(call, course_id, page=0):
    user = sql_return.find_user_id(call.from_user.id)

    if not user:
        bot.send_message(call.message.chat.id, "Вы не зарегистрированы.")
        return

    lessons = sql_return.lessons_in_course(course_id)

    if not lessons:  # Проверяем, что уроки существуют
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 К курсу", callback_data=f"mm_send"))
        bot.send_message(call.message.chat.id, "В этом курсе пока нет уроков.", reply_markup=markup)
        return

    lessons = list(reversed(lessons))  # Переворачиваем уроки

    courses_per_page = 8
    total_pages = (len(lessons) + courses_per_page - 1) // courses_per_page
    page_courses = lessons[page * courses_per_page:(page + 1) * courses_per_page]

    description = "Выберите урок для отправки решения:\n"

    markup = types.InlineKeyboardMarkup()
    for lesson in page_courses:
        markup.add(types.InlineKeyboardButton(f"{lesson[2]}", callback_data=f'send-task_{course_id}_{lesson[0]}_0'))

    navigation = []
    if page > 0:
        navigation.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f'send-course_{course_id}_{page - 1}'))
    if page < total_pages - 1:
        navigation.append(types.InlineKeyboardButton("➡️ Вперед", callback_data=f'send-course_{course_id}_{page + 1}'))

    markup.row(*navigation)
    markup.add(types.InlineKeyboardButton("🔙 К курсу", callback_data=f"mm_send"))

    bot.edit_message_text(f"{description}\nСтраница {page + 1} из {total_pages}:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

def mm_send_task(call, course_id, lesson_id, page=0):
    user = sql_return.find_user_id(call.from_user.id)

    if not user:
        bot.send_message(call.message.chat.id, "Вы не зарегистрированы.")
        return

    tasks_temp = sql_return.tasks_in_lesson(lesson_id)
    tasks = []
    for i in tasks_temp:
        if sql_return.is_task_open(i[0]):
            tasks.append(i)

    courses_per_page = 8
    total_pages = (len(tasks) + courses_per_page - 1) // courses_per_page
    page_courses = tasks[page * courses_per_page:(page + 1) * courses_per_page]

    description = "Содержание урока:\n"

    markup = types.InlineKeyboardMarkup()
    for lesson in page_courses:
        markup.add(types.InlineKeyboardButton(f"{lesson[2]}", callback_data=f'send-final_{lesson_id}_{course_id}_{lesson[0]}'))

    navigation = []
    if page > 0:
        navigation.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f'send-task_{course_id}_{lesson_id}_{page - 1}'))
    if page < total_pages - 1:
        navigation.append(types.InlineKeyboardButton("➡️ Вперед", callback_data=f'send-task_{course_id}_{lesson_id}_{page + 1}'))

    markup.row(*navigation)
    markup.add(types.InlineKeyboardButton("🔙 К содержанию курса", callback_data=f"send-course_{course_id}_0"))
    try:
        bot.edit_message_text(f"{description}\nСтраница {page + 1} из {total_pages}:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
    except:
        pass

def mm_send_final(call, lesson_id, course_id, task_id):
    task = sql_return.task_info(task_id)
    if not task:
        bot.edit_message_text("❗️ Задача не найдена", 
                              chat_id=call.message.chat.id, 
                              message_id=call.message.message_id)
        return

    cancel_solution_submission_session(call.from_user.id)
    session = start_solution_submission_session(
        call.from_user.id,
        call.message.chat.id,
        task,
        call.message.message_id,
    )
    bot.edit_message_text(
        build_solution_submission_text(task, session),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="HTML",
        reply_markup=build_solution_submission_markup(),
    )

def mm_check(call, page=0):
    user = sql_return.find_user_id(call.from_user.id)

    if not user:
        bot.send_message(call.message.chat.id, "Вы не зарегистрированы.")
        return

    is_admin = (user[3] == "approved" and str(call.from_user.id) == config["admin_id"])

    all_courses = sql_return.all_courses()

    developer_courses = []
    
    for course in all_courses:
        student_ids = course[3] if course[3] else ""
        developer_ids = course[4] if course[4] else ""
        
        if str(call.from_user.id) in developer_ids.split():
            developer_courses.append(course)

    filtered_courses = developer_courses

    courses_per_page = 8
    total_pages = (len(filtered_courses) + courses_per_page - 1) // courses_per_page
    page_courses = filtered_courses[page * courses_per_page:(page + 1) * courses_per_page]

    markup = types.InlineKeyboardMarkup()
    if page == 0 and total_pages != 0:
        markup.add(types.InlineKeyboardButton(f"🗂 Все решения", callback_data=f'check-course-all_'))
    for course in page_courses:
        markup.add(types.InlineKeyboardButton(f"👨‍🏫 {course[1]} ({sql_return.count_unchecked_solutions(int(course[0]))})", callback_data=f'check-course_{course[0]}'))

    navigation = []
    if page > 0:
        navigation.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f'mm_check_{page - 1}'))
    if page < total_pages - 1:
        navigation.append(types.InlineKeyboardButton("➡️ Вперед", callback_data=f'mm_check_{page + 1}'))

    markup.row(*navigation)
    markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="mm_main_menu"))
    bot.delete_message(call.message.chat.id, call.message.message_id)
    
    bot.send_message(call.message.chat.id, f"Выберите курс для принятия задания\nСтраница {page + 1} из {total_pages}:", reply_markup=markup)

def mm_answers(call, page=0):
    is_admin = int(call.from_user.id) == get_admin_id()
    solutions = sql_return.get_accessible_solution_details(call.from_user.id, include_all=is_admin)

    if not solutions:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="mm_main_menu"))
        safe_delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "У вас пока нет доступных решений.", reply_markup=markup)
        return

    solutions_per_page = 6
    total_pages = max(1, (len(solutions) + solutions_per_page - 1) // solutions_per_page)
    page = max(0, min(page, total_pages - 1))
    page_solutions = solutions[page * solutions_per_page:(page + 1) * solutions_per_page]

    markup = types.InlineKeyboardMarkup()
    for solution_data in page_solutions:
        button_text = build_solution_list_button_text(solution_data, call.from_user.id)
        markup.add(
            ui_button(
                button_text,
                callback_data=f"solution_{solution_data['answer_id']}_{page}",
                icon_custom_emoji_id=verdict_button_custom_emoji_id(solution_data.get("verdict"))
            )
        )

    pagination = build_pagination_buttons("mm_answers", page, total_pages)
    if pagination:
        markup.row(*pagination)
    markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="mm_main_menu"))

    text = (
        "Выберите решение для просмотра.\n"
        "Формат кнопки: роль, вердикт, наличие файла, затем курс / урок / номер задачи.\n"
        f"Страница {page + 1} из {total_pages}. Всего решений: {len(solutions)}."
    )

    safe_delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(call.message.chat.id, text, reply_markup=markup)

def solution(call, sol_id, page=0, show_files_preview: bool = True):
    solution_data = sql_return.get_solution_details(sol_id)
    if not can_access_solution(call.from_user.id, solution_data):
        bot.send_message(call.message.chat.id, "У вас нет доступа к этому решению.")
        return

    markup = build_solution_view_markup(solution_data, call.from_user.id, page)
    show_solution_details(
        call,
        solution_data,
        markup,
        file_button_caption=f"Файл решения #{sol_id}",
        show_files_preview=show_files_preview,
    )

def self_reject(call, sol_id, page=0, undo=False):
    solution_data = sql_return.get_solution_details(sol_id)
    if not solution_data or int(solution_data["student_id"]) != int(call.from_user.id):
        bot.send_message(call.message.chat.id, "Вы можете менять только свои решения.")
        return
    if undo:
        sql_return.undo_self_reject(sol_id)
    else:
        sql_return.self_reject(sol_id)
    solution(call, sol_id, page, show_files_preview=False)

def check_all(call):
    task_data = sql_return.last_student_answer_all(call.from_user.id)
    check_task(type=f"check-course-all_", call=call, task_data=task_data)

def check_course(call, course_id):
    task_data = sql_return.last_student_answer_course(course_id)
    check_task(type=f"check-course_{course_id}", call=call, task_data=task_data)

comment_for_answer_dict = dict([])

def check_task(type: str, call, task_data, comment: str = "None", show_files_preview: bool = True):
    if task_data is None:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="mm_check_0"))
        safe_delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(
            call.message.chat.id,
            "У вас нет непроверенных решений в этом разделе",
            reply_markup=markup
        )
        return

    if isinstance(task_data, dict):
        answer_id = task_data["answer_id"]
    else:
        answer_id = task_data[0]

    solution_data = sql_return.get_solution_details(answer_id)
    if not solution_data:
        bot.send_message(call.message.chat.id, "Решение не найдено.")
        return

    markup = build_check_solution_markup(solution_data, type)
    comment_to_show = None if comment == "None" else comment
    show_solution_details(
        call,
        solution_data,
        markup,
        file_button_caption=f"Файл решения #{answer_id}",
        comment_override=comment_to_show,
        show_files_preview=show_files_preview,
    )

def check_add_comment(message, call, type: str, task_id):
    log_user_action(
        message.from_user,
        "check.comment_input",
        f"type={type}, task_id={task_id}, text={message.text or ''}"
    )
    task_data = sql_return.get_student_answer_from_id(task_id)
    comment = message.text
    comment_for_answer_dict[message.from_user.id] = comment
    check_task(type, call, task_data, comment, show_files_preview=False)

def check_final(call, answer_id: int, verdict: str):
    try:
        comment = comment_for_answer_dict[call.from_user.id]
    except:
        comment = None
    if call.from_user.id in comment_for_answer_dict:
        del comment_for_answer_dict[call.from_user.id]
    if comment == "None":
        comment = None
    sql_return.check_student_answer(verdict, comment, answer_id)
    sa_data = sql_return.get_student_answer_from_id(answer_id)
    if verdict == "accept":
        verdict_message = f"{CHECK_HTML} Вердикт: верно"
    else:
        verdict_message = f"{CROSS_HTML} Вердикт: неверно"

    comment2 = ""
    if comment:
        comment2 = f"\n📜 Комментарий: {html.escape(comment)}"
    bot.send_message(
        sa_data[2],
        f"""🥳 Ваше решение проверено!

Курс: {html.escape(str(sql_return.get_course_name(sql_return.get_course_from_answer_id(answer_id)) or 'Неизвестно'))}
Урок: {html.escape(str(sql_return.get_lesson_name(sql_return.get_lesson_from_answer_id(answer_id)) or 'Неизвестно'))}
Задача: {html.escape(str(sql_return.get_task_name(sql_return.get_task_from_answer_id(answer_id)) or 'Неизвестно'))}
📝 Текст решения:\n{html.escape(str(sa_data[3] or 'Нет текста'))}
{verdict_message}{comment2}""",
        parse_mode="HTML"
    )

    sql_return.log_action(call.from_user.id, "check_final", f"{answer_id}")
    mm_check(call)

def mm_courses(call, page=0):

    user = sql_return.find_user_id(call.from_user.id)

    if not user:
        bot.send_message(call.message.chat.id, "Вы не зарегистрированы.")
        return

    is_admin = (user[3] == "approved" and str(call.from_user.id) == str(config["admin_id"]))

    all_courses = sql_return.all_courses()

    student_or_developer_courses = []
    other_courses = []
    
    for course in all_courses:
        student_ids = course[3] if course[3] else ""
        developer_ids = course[4] if course[4] else ""
        
        if str(call.from_user.id) in student_ids.split() or str(call.from_user.id) in developer_ids.split():
            student_or_developer_courses.append(course)
        else:
            other_courses.append(course)

    if is_admin:
        filtered_courses = student_or_developer_courses + other_courses
    else:
        filtered_courses = student_or_developer_courses

    courses_per_page = 8
    total_pages = (len(filtered_courses) + courses_per_page - 1) // courses_per_page
    page_courses = filtered_courses[page * courses_per_page:(page + 1) * courses_per_page]

    description = "Выберите курс:\n"
    description += "👨‍🎓 — Вы студент курса\n"
    description += "👨‍🏫 — Вы преподаватель курса\n"
    
    if is_admin:
        description += "🔑 — Вы администратор\n"

    markup = types.InlineKeyboardMarkup()
    for course in page_courses:
        student_ids = course[3] if course[3] else ""
        developer_ids = course[4] if course[4] else ""

        if str(call.from_user.id) in student_ids.split():
            emoji = "👨‍🎓" 
        elif str(call.from_user.id) in developer_ids.split():
            emoji = "👨‍🏫"
        elif is_admin:
            emoji = "🔑"
        else:
            emoji = "🚫"

        markup.add(types.InlineKeyboardButton(f"{emoji} {course[1]}", callback_data=f'course_{course[0]}'))

    navigation = []
    if page > 0:
        navigation.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f'mm_courses_{page - 1}'))
    if page < total_pages - 1:
        navigation.append(types.InlineKeyboardButton("➡️ Вперед", callback_data=f'mm_courses_{page + 1}'))

    markup.row(*navigation)
    if page == 0:
        markup.add(types.InlineKeyboardButton("➕ Создать курс", callback_data="create_course"))
    markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="mm_main_menu"))
    if total_pages > 1:
        bot.edit_message_text(f"{description}\nСтраница {page + 1} из {total_pages}:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
    else:
        bot.edit_message_text(f"{description}\nНа данный момент вы не состоите ни в одном из курсов", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

def course_info(call):
    course_id = int(call.data.split('_')[-1])
    course = sql_return.find_course_id(course_id)

    if not course:
        bot.send_message(call.message.chat.id, "Курс не найден.")
        return

    course_name = course[1]
    creator_id = course[2]
    student_ids = course[3] if course[3] else ""
    developer_ids = course[4] if course[4] else ""

    developers = sorting_123.sort([str(dev_id) for dev_id in developer_ids.split()])
    developer_names = []
    for dev_id in developers:
        user = sql_return.get_user_name(int(dev_id))
        if user:
            developer_names.append(f"{user[0]} {user[1]}")
        else:
            developer_names.append(f"Пользователь с ID {dev_id} не найден")

    students = sorting_123.sort([str(student_id) for student_id in student_ids.split()])
    student_names = []
    for student_id in students:
        user = sql_return.get_user_name(int(student_id))
        if user:
            student_names.append(f"{user[0]} {user[1]}")
        else:
            student_names.append(f"Пользователь с ID {student_id} не найден")
    
    creator_name = ""
    user = sql_return.get_user_name(int(creator_id))
    if user:
        creator_name = f"{user[0]} {user[1]}"
    else:
        creator_name = f"Пользователь с ID {student_id} не найден"

    course_info = f"📚 Курс: {course_name}\n\n"
    course_info += f"Создатель: \n{creator_name}\n\n"
    course_info += "👨‍🏫 Разработчики:\n" + "\n".join(developer_names) + "\n\n"
    course_info += "👨‍🎓 Студенты:\n" + "\n".join(student_names) + "\n"

    is_dev = sql_return.is_course_dev(call.from_user.id, developer_ids)

    markup = types.InlineKeyboardMarkup()
    if int(call.from_user.id) == int(config["admin_id"]) or is_dev:
        markup.add(types.InlineKeyboardButton("➕ Добавить ученика", callback_data=f'add_student_{course_id}'))
        markup.add(types.InlineKeyboardButton("➕ Добавить разработчика", callback_data=f'add_developer_{course_id}'))
    markup.add(types.InlineKeyboardButton("📂 Содержание", callback_data=f"content_{course_id}_0"))
    if can_use_gpt_lesson_button(call.from_user.id):
        markup.add(ui_button("Добавить урок", callback_data=f"gpt_add_lesson_{course_id}", style="primary", icon_custom_emoji_id=CHATGPT_CUSTOM_EMOJI_ID))
    markup.add(types.InlineKeyboardButton("📃 К курсам", callback_data="mm_courses_0"))

    bot.edit_message_text(course_info, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

def add_student(call):
    course_id = int(call.data.split('_')[-1])
    bot.reply_to(call.message, "Введите ID ученика, которого хотите добавить:")
    bot.register_next_step_handler(call.message, lambda message: add_student_to_course(message, course_id))

def add_student_to_course(message, course_id):
    log_user_action(
        message.from_user,
        "course.add_student_input",
        f"course_id={course_id}, student_id_raw={message.text or ''}"
    )
    try:
        student_id = int(message.text)
        student = sql_return.find_user_id(student_id)

        if not student:
            bot.reply_to(message, "Пользователь с таким ID не найден.")
            return
    
        student_ids = sql_return.students_list(course_id)
        if str(student_id) not in student_ids.split():
            new_student_ids = student_ids + f" {student_id}"
            sql_return.try_add_student_to_course(course_id, new_student_ids.strip())
            bot.reply_to(message, f"Ученик {student[1]} {student[2]} добавлен в курс!")
            sql_return.log_action(message.from_user.id, "add_student", f"{course_id} {student_id}")
        else:
            bot.reply_to(message, "Этот ученик уже находится в курсе.")
        
    except ValueError:
        bot.reply_to(message, "Неправильный ID. Попробуйте снова.")

def add_developer(call):
    course_id = int(call.data.split('_')[-1])
    bot.reply_to(call.message, "Введите ID разработчика, которого хотите добавить:")
    bot.register_next_step_handler(call.message, lambda message: add_developer_to_course(message, course_id))

def add_developer_to_course(message, course_id):
    log_user_action(
        message.from_user,
        "course.add_developer_input",
        f"course_id={course_id}, developer_id_raw={message.text or ''}"
    )
    try:
        developer_id = int(message.text)
        developer = sql_return.find_user_id(developer_id)

        if not developer:
            bot.reply_to(message, "Пользователь с таким ID не найден.")
            return

        developer_ids = sql_return.developers_list(course_id)
        if str(developer_id) not in developer_ids.split():
            new_developer_ids = developer_ids + f" {developer_id}"
            sql_return.try_add_developer_to_course(course_id, new_developer_ids.strip())
            bot.reply_to(message, f"Разработчик {developer[1]} {developer[2]} добавлен в курс!")
            sql_return.log_action(message.from_user.id, "add_developer", f"{course_id} {developer_id}")
        else:
            bot.reply_to(message, "Этот разработчик уже находится в курсе.")
    except ValueError:
        bot.reply_to(message, "Неправильный ID. Попробуйте снова.")

def course_content(call, course_id, page=0):
    user = sql_return.find_user_id(call.from_user.id)

    if not user:
        bot.send_message(call.message.chat.id, "Вы не зарегистрированы.")
        return

    is_admin = str(call.from_user.id) == str(config["admin_id"])
    is_dev = sql_return.is_course_dev(call.from_user.id, sql_return.developers_list(course_id))
    can_use_gpt = can_use_gpt_lesson_button(call.from_user.id)

    lessons = sql_return.lessons_in_course(course_id)

    if not lessons:  # Проверяем, что уроки существуют
        markup = types.InlineKeyboardMarkup()
        if is_admin or is_dev:
            markup.add(types.InlineKeyboardButton("➕ Создать урок", callback_data=f'create_lesson_{course_id}'))
        if can_use_gpt:
            markup.add(ui_button("Добавить урок", callback_data=f'gpt_add_lesson_{course_id}', style="primary", icon_custom_emoji_id=CHATGPT_CUSTOM_EMOJI_ID))
        markup.add(types.InlineKeyboardButton("🔙 К курсу", callback_data=f"course_{course_id}"))
        bot.send_message(call.message.chat.id, "В этом курсе пока нет уроков.", reply_markup=markup)
        return

    lessons = list(reversed(lessons))  # Переворачиваем уроки

    # all_courses = sql_return.all_courses()

    courses_per_page = 8
    total_pages = (len(lessons) + courses_per_page - 1) // courses_per_page
    page_courses = lessons[page * courses_per_page:(page + 1) * courses_per_page]

    description = "Содержание курса:\n"

    markup = types.InlineKeyboardMarkup()
    for lesson in page_courses:
        lesson_title = f"📎 {lesson[2]}" if get_lesson_file_id(lesson) else f"{lesson[2]}"
        markup.add(types.InlineKeyboardButton(lesson_title, callback_data=f'lesson_{course_id}_{lesson[0]}_0'))

    navigation = []
    if page > 0:
        navigation.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f'content_{course_id}_{page - 1}'))
    if page < total_pages - 1:
        navigation.append(types.InlineKeyboardButton("➡️ Вперед", callback_data=f'content_{course_id}_{page + 1}'))

    markup.row(*navigation)

    if (is_admin or is_dev) and page == 0:
        markup.add(types.InlineKeyboardButton("➕ Создать урок", callback_data=f'create_lesson_{course_id}'))
    if can_use_gpt and page == 0:
        markup.add(ui_button("Добавить урок", callback_data=f'gpt_add_lesson_{course_id}', style="primary", icon_custom_emoji_id=CHATGPT_CUSTOM_EMOJI_ID))

    markup.add(types.InlineKeyboardButton("🔙 К курсу", callback_data=f"course_{course_id}"))

    bot.edit_message_text(f"{description}\nСтраница {page + 1} из {total_pages}:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

def lesson_content(call, course_id, lesson_id, page=0):
    user = sql_return.find_user_id(call.from_user.id)

    if not user:
        bot.send_message(call.message.chat.id, "Вы не зарегистрированы.")
        return

    lesson_data = sql_return.get_lesson_from_id(lesson_id)
    if not lesson_data or int(lesson_data[1]) != int(course_id):
        bot.send_message(call.message.chat.id, "Урок не найден.")
        return

    is_admin = str(call.from_user.id) == str(config["admin_id"])
    is_dev = sql_return.is_course_dev(call.from_user.id, sql_return.developers_list(course_id))
    lesson_file_id = get_lesson_file_id(lesson_data)
    tasks = sql_return.tasks_in_lesson(lesson_id)

    courses_per_page = 8
    total_pages = max(1, (len(tasks) + courses_per_page - 1) // courses_per_page)
    page_courses = tasks[page * courses_per_page:(page + 1) * courses_per_page]

    description = f"Содержание урока: {lesson_data[2]}\n"
    if lesson_file_id:
        description += "\n📎 К уроку прикреплён файл."
    if not tasks:
        description += "\n\nВ этом уроке пока нет задач."

    markup = types.InlineKeyboardMarkup()
    if lesson_file_id:
        markup.add(types.InlineKeyboardButton("📎 Получить файл урока", callback_data=f'download_lesson_file_{course_id}_{lesson_id}'))

    for lesson in page_courses:
        verdict = sql_return.task_status_by_user(call.from_user.id, lesson[0])
        markup.add(types.InlineKeyboardButton(f"{verdict} {lesson[2]}", callback_data=f'task_{lesson[0]}_{lesson_id}_{course_id}'))

    navigation = []
    if page > 0:
        navigation.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f'lesson_{course_id}_{lesson_id}_{page - 1}'))
    if page < total_pages - 1:
        navigation.append(types.InlineKeyboardButton("➡️ Вперед", callback_data=f'lesson_{course_id}_{lesson_id}_{page + 1}'))

    if (is_admin or is_dev) and page == 0:
        attach_button_text = "♻️ Заменить файл урока" if lesson_file_id else "📤 Прикрепить файл к уроку"
        markup.add(types.InlineKeyboardButton(attach_button_text, callback_data=f'attach_lesson_file_{course_id}_{lesson_id}'))
        markup.add(types.InlineKeyboardButton("➕ Создать задачу", callback_data=f'create_task_{lesson_id}_{course_id}'))

    if navigation:
        markup.row(*navigation)
    markup.add(types.InlineKeyboardButton("🔙 К содержанию курса", callback_data=f"content_{course_id}_0"))
    try:
        bot.edit_message_text(f"{description}\nСтраница {page + 1} из {total_pages}:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
    except:
        pass

def task_info(call, task_id, lesson_id, course_id):
    sql_return.update_task_status(task_id)
    task = sql_return.task_info(task_id)
    
    if task:
        task_id, lesson_id, task_title, raw_task_status, task_deadline, task_description = task

        status_translation = {
            'open': 'Открыт',
            'close': 'Закрыт',
            'arc': 'Закрыт',
            'dev': 'В разработке'
        }
        task_status = status_translation.get(raw_task_status, 'Неизвестен')
        
        if task_deadline:
            # Преобразуем временную метку в объект datetime
            deadline_date = datetime.datetime.fromtimestamp(task_deadline / 1000)
            current_date = datetime.datetime.now()
            
            # Вычисляем количество дней до дедлайна
            seconds_left = (deadline_date - current_date).total_seconds()
            days_left = (deadline_date - current_date).total_seconds() / (60 * 60 * 24)
            
            print(deadline_date, current_date, days_left, seconds_left, (current_date - deadline_date).total_seconds())
            
            if days_left > 2:
                deadline_str = deadline_date.strftime('%d-%m-%Y %H:%M')
                time_left_str = f"{int(days_left)} дней"  # Преобразуем в целое число
                deadline_info = f"🔥 <b>Дедлайн через</b>: {time_left_str} ({deadline_str})"
            elif seconds_left < 0:
                deadline_str = deadline_date.strftime('%d-%m-%Y %H:%M')
                deadline_info = f"🗓 <b>Дедлайн</b>: {deadline_str}"
            else:
                time_left = relativedelta(deadline_date, current_date)
                time_left_str = f"{time_left.days} дней, {time_left.hours} часов, {time_left.minutes} минут"
                deadline_str = deadline_date.strftime('%d-%m-%Y %H:%M')
                deadline_info = f"🔥 <b>Дедлайн через</b>: {time_left_str} ({deadline_str})"
        else:
            deadline_info = "⏰ <b>Дедлайн</b>: Не указан"

        task_info_message = (f"📌 <b>Название задачи</b>: {task_title}\n"
                             f"🔖 <b>Статус</b>: {task_status}\n"
                             f"{deadline_info}\n"
                             f"📝 <b>Текст задачи</b>: {task_description if task_description else 'Нет текста задачи'}")
        
        markup = types.InlineKeyboardMarkup()
        is_admin = str(call.from_user.id) == str(config["admin_id"])
        is_dev = sql_return.is_course_dev(call.from_user.id, sql_return.developers_list(course_id))
        if is_admin or is_dev:
            toggle_task_text = "🔒 Закрыть задачу" if raw_task_status == "open" else "🔓 Открыть задачу"
            markup.add(types.InlineKeyboardButton(toggle_task_text, callback_data=f"toggle_task_{course_id}_{lesson_id}_{task_id}"))
        markup.add(types.InlineKeyboardButton("🔙 К списку задач", callback_data=f"lesson_{course_id}_{lesson_id}_0"))

        bot.edit_message_text(task_info_message, 
                              chat_id=call.message.chat.id, 
                              message_id=call.message.message_id, 
                              reply_markup=markup, 
                              parse_mode="HTML")
    else:
        bot.edit_message_text("❗️ Задача не найдена", 
                              chat_id=call.message.chat.id, 
                              message_id=call.message.message_id)

def toggle_task_open_close(call, course_id, lesson_id, task_id):
    user = sql_return.find_user_id(call.from_user.id)

    if not user:
        bot.send_message(call.message.chat.id, "Вы не зарегистрированы.")
        return

    is_admin = str(call.from_user.id) == str(config["admin_id"])
    is_dev = sql_return.is_course_dev(call.from_user.id, sql_return.developers_list(course_id))
    if not (is_admin or is_dev):
        bot.send_message(call.message.chat.id, "У вас нет прав на изменение статуса задачи.")
        return

    new_status = sql_return.toggle_task_status(task_id)
    if new_status is None:
        bot.send_message(call.message.chat.id, "Задача не найдена.")
        return

    sql_return.log_action(call.from_user.id, "toggle_task_status", f"{task_id} {new_status}")
    task_info(call, task_id, lesson_id, course_id)

def create_course(call):
    bot.edit_message_text(f"""🎓 Вы создаёте курс.
                          
📋 Информация о курсе:
👨‍🏫 Создатель курса: {sql_return.get_user_name(call.from_user.id)[0]} {sql_return.get_user_name(call.from_user.id)[1]} ({call.from_user.id})
📚 Название курса: -
👥 Разработчики: -

✏️ Пожалуйста, введите название курса:""", chat_id=call.message.chat.id, message_id=call.message.message_id)
    bot.register_next_step_handler(call.message, create_course_name, call.message.message_id)

def create_course_name(message, editing_message_id):
    log_user_action(
        message.from_user,
        "course.create_name_input",
        f"text={message.text or ''}"
    )
    name = message.text
    bot.delete_message(message.chat.id, message.message_id)
    bot.edit_message_text(f"""🎓 Вы создаёте курс.
                          
📋 Информация о курсе: 
👨‍🏫 Создатель курса: {sql_return.get_user_name(message.from_user.id)[0]} {sql_return.get_user_name(message.from_user.id)[1]} ({message.from_user.id})
📚 Название курса: {name}
👥 Разработчики: -

✏️ Пожалуйста, введите id разработчиков через пробел (для отмены введите "cancel" или "none" для отсутствия разработчиков):""", chat_id=message.chat.id, message_id=editing_message_id)
    bot.register_next_step_handler(message, create_course_developers, editing_message_id, name)

def create_course_developers(message, editing_message_id, course_name):
    log_user_action(
        message.from_user,
        "course.create_developers_input",
        f"course_name={course_name}, text={message.text or ''}"
    )
    developers = message.text.split()
    bot.delete_message(message.chat.id, message.message_id)

    if message.text.lower() == "cancel":
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="mm_main_menu"))
        bot.edit_message_text(f"{CROSS_HTML} Создание курса отменено", chat_id=message.chat.id, message_id=editing_message_id, reply_markup=markup, parse_mode="HTML")
        return
    
    if message.text.lower() == "none":
        sql_return.create_course(course_name, message.from_user.id, str(message.from_user.id))
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="mm_main_menu"))
        bot.edit_message_text(f"""{CHECK_HTML} Курс "{html.escape(course_name)}" успешно создан!""", chat_id=message.chat.id, message_id=editing_message_id, reply_markup=markup, parse_mode="HTML")
        return
        
    try:
        developers = [int(dev_id) for dev_id in developers]
    except ValueError:
        bot.edit_message_text(f"""🎓 Вы создаёте курс.
                          
📋 Информация о курсе: 
👨‍🏫 Создатель курса: {html.escape(str(sql_return.get_user_name(message.from_user.id)[0]))} {html.escape(str(sql_return.get_user_name(message.from_user.id)[1]))} ({message.from_user.id})
📚 Название курса: {html.escape(course_name)}
👥 Разработчики: -

{CROSS_HTML} Ошибка: ID разработчиков должны быть числами. Пожалуйста, введите ID через пробел (например: 123456789 987654321)""", chat_id=message.chat.id, message_id=editing_message_id, parse_mode="HTML")
        bot.register_next_step_handler(message, create_course_developers, editing_message_id, course_name)
        return
    
    if message.from_user.id not in developers:
        developers.insert(0, message.from_user.id)
    else:
        developers.remove(message.from_user.id)
        developers.insert(0, message.from_user.id)
        
    sql_return.create_course(course_name, message.from_user.id, " ".join(map(str, developers)))
    sql_return.log_action(message.from_user.id, "create_course", f"{sql_return.last_course_id()} {course_name} {message.from_user.id} {developers}")
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="mm_main_menu"))
    bot.edit_message_text(f"""{CHECK_HTML} Курс "{html.escape(course_name)}" успешно создан!""", chat_id=message.chat.id, message_id=editing_message_id, reply_markup=markup, parse_mode="HTML")

def create_lesson(call):
    bot.edit_message_text(f"""🎓 Вы создаёте урок.
                          
📋 Информация о уроке:
📚 Название урока: -

✏️ Пожалуйста, введите название урока:""", chat_id=call.message.chat.id, message_id=call.message.message_id)
    bot.register_next_step_handler(call.message, create_lesson_name, call.message.message_id, call.data.split('_')[-1])

def create_lesson_name(message, editing_message_id, course_id):
    log_user_action(
        message.from_user,
        "lesson.create_name_input",
        f"course_id={course_id}, text={message.text or ''}"
    )
    name = message.text
    bot.delete_message(message.chat.id, message.message_id)
    sql_return.create_lesson(course_id, name)
    sql_return.log_action(message.from_user.id, "create_lesson", f"{sql_return.last_lesson_id()} {course_id} {name}")
    Thread(target=process_pending_lesson_notifications, args=("create_lesson",), daemon=True).start()
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 К списку уроков", callback_data=f"content_{course_id}_0"))
    bot.edit_message_text(f"""{CHECK_HTML} Урок "{html.escape(name)}" успешно создан!""", chat_id=message.chat.id, message_id=editing_message_id, reply_markup=markup, parse_mode="HTML")

def attach_lesson_file(call, course_id: int, lesson_id: int):
    if not is_course_admin_or_dev(call.from_user.id, course_id):
        bot.send_message(call.message.chat.id, "Только админ и разработчики курса могут прикреплять файлы к уроку.")
        return

    lesson_data = sql_return.get_lesson_from_id(lesson_id)
    if not lesson_data or int(lesson_data[1]) != int(course_id):
        bot.send_message(call.message.chat.id, "Урок не найден.")
        return

    bot.send_message(
        call.message.chat.id,
        "Отправьте документ или фотографию, которую нужно прикрепить к уроку.\n"
        "Для отмены отправьте `cancel` или `/stop`.",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(call.message, receive_lesson_file, course_id, lesson_id)

def receive_lesson_file(message, course_id: int, lesson_id: int):
    log_user_action(
        message.from_user,
        "lesson.attach_file_input",
        f"course_id={course_id}, lesson_id={lesson_id}, content_type={message.content_type}"
    )

    if not is_course_admin_or_dev(message.from_user.id, course_id):
        bot.send_message(message.chat.id, "Только админ и разработчики курса могут прикреплять файлы к уроку.")
        return

    lesson_data = sql_return.get_lesson_from_id(lesson_id)
    if not lesson_data or int(lesson_data[1]) != int(course_id):
        bot.send_message(message.chat.id, "Урок не найден.")
        return

    if message.content_type == "text" and (message.text or "").strip().lower() in {"cancel", "/stop", "stop"}:
        bot.send_message(message.chat.id, "Прикрепление файла отменено.")
        return

    if message.content_type not in ("photo", "document"):
        bot.send_message(message.chat.id, "Нужно отправить документ или фотографию.")
        bot.register_next_step_handler(message, receive_lesson_file, course_id, lesson_id)
        return

    try:
        file_data = save_lesson_attachment_file(message)
        sql_return.set_lesson_file(lesson_id, file_data["file_id"])
        sql_return.log_action(
            message.from_user.id,
            "attach_lesson_file",
            f"{lesson_id} {file_data['file_id']}"
        )
    except ValueError as error:
        bot.send_message(message.chat.id, str(error))
        bot.register_next_step_handler(message, receive_lesson_file, course_id, lesson_id)
        return
    except telebot.apihelper.ApiTelegramException as error:
        if "file is too big" in str(error).lower():
            bot.send_message(message.chat.id, "Файл слишком большой для загрузки через Telegram API.")
        else:
            bot.send_message(message.chat.id, "Не удалось обработать файл. Попробуйте ещё раз.")
        bot.register_next_step_handler(message, receive_lesson_file, course_id, lesson_id)
        return

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 К уроку", callback_data=f"lesson_{course_id}_{lesson_id}_0"))
    bot.send_message(
        message.chat.id,
        f'Файл успешно прикреплён к уроку "{lesson_data[2]}".',
        reply_markup=markup
    )

def download_lesson_file(call, course_id: int, lesson_id: int):
    if not can_access_course_materials(call.from_user.id, course_id):
        bot.send_message(call.message.chat.id, "У вас нет доступа к материалам этого курса.")
        return

    lesson_data = sql_return.get_lesson_from_id(lesson_id)
    if not lesson_data or int(lesson_data[1]) != int(course_id):
        bot.send_message(call.message.chat.id, "Урок не найден.")
        return

    lesson_file_id = get_lesson_file_id(lesson_data)
    if not lesson_file_id:
        bot.send_message(call.message.chat.id, "К этому уроку пока не прикреплён файл.")
        return

    file_info = sql_return.get_file(lesson_file_id)
    if not file_info:
        bot.send_message(call.message.chat.id, "Не удалось найти прикреплённый файл.")
        return

    try:
        send_saved_file_to_chat(
            call.message.chat.id,
            file_info,
            caption=f'Материалы к уроку "{lesson_data[2]}"'
        )
        sql_return.log_action(call.from_user.id, "download_lesson_file", f"{lesson_id} {lesson_file_id}")
    except FileNotFoundError:
        bot.send_message(call.message.chat.id, "Файл найден в базе, но отсутствует на диске.")
    except Exception:
        bot.send_message(call.message.chat.id, "Не удалось отправить файл. Попробуйте позже.")


def download_solution_file(call, answer_id: int):
    solution_data = sql_return.get_solution_details(answer_id)
    if not can_access_solution(call.from_user.id, solution_data):
        bot.send_message(call.message.chat.id, "У вас нет доступа к файлу этого решения.")
        return

    if not get_solution_file_infos(solution_data):
        bot.send_message(call.message.chat.id, "К этому решению не прикреплены файлы.")
        return

    try:
        send_solution_files_preview(call.message.chat.id, solution_data)
        sql_return.log_action(call.from_user.id, "download_solution_file", f"{answer_id} files={solution_data.get('file_count', 0)}")
    except FileNotFoundError:
        bot.send_message(call.message.chat.id, "Файл найден в базе, но отсутствует на диске.")
    except Exception:
        bot.send_message(call.message.chat.id, "Не удалось отправить файлы решения единым сообщением или альбомом. Попробуйте позже.")

def create_task(call):
    bot.edit_message_text(f"""🎓 Вы создаёте задачу.
                          
📋 Информация о задаче:
📚 Название задачи: -
📝 Текст задачи: - 

✏️ Пожалуйста, введите название задачи:""", chat_id=call.message.chat.id, message_id=call.message.message_id)
    bot.register_next_step_handler(call.message, create_task_name, call.message.message_id, call.data.split('_')[-2], call.data.split('_')[-1])

def create_task_name(message, editing_message_id, lesson_id, course_id):
    log_user_action(
        message.from_user,
        "task.create_name_input",
        f"course_id={course_id}, lesson_id={lesson_id}, text={message.text or ''}"
    )
    task_name = message.text
    bot.delete_message(message.chat.id, message.message_id)
    bot.edit_message_text(f"""🎓 Вы создаёте задачу.
                          
📋 Информация о задаче:
📚 Название задачи: {task_name}
📝 Текст задачи: - 

✏️ Пожалуйста, введите текст задачи:""", chat_id=message.chat.id, message_id=editing_message_id)
    bot.register_next_step_handler(message, create_task_description, editing_message_id, lesson_id, course_id, task_name)

def create_task_description(message, editing_message_id, lesson_id, course_id, task_name):
    log_user_action(
        message.from_user,
        "task.create_description_input",
        f"course_id={course_id}, lesson_id={lesson_id}, task_name={task_name}, text={message.text or ''}"
    )
    task_description = message.text
    bot.delete_message(message.chat.id, message.message_id)
    sql_return.create_task(lesson_id, course_id, task_name, task_description)
    sql_return.log_action(message.from_user.id, "create_task", f"{sql_return.last_task_id()} {lesson_id} {course_id} {task_name} {task_description}")
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 К списку задач", callback_data=f"lesson_{course_id}_{lesson_id}_0"))
    bot.edit_message_text(f"""{CHECK_HTML} Задача "{html.escape(task_name)}" успешно создана!""", chat_id=message.chat.id, message_id=editing_message_id, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(commands=["support"])
def support(message):
    log_user_action(message.from_user, "command.support")
    bot.reply_to(message, f"Поддержка находится в лс у @agusev2311")

@bot.message_handler(commands=["help"])
def help(message):
    log_user_action(message.from_user, "command.help")
    text = """Список всех команд в боте и faq:
Команды:
/start - регистрация или главное меню

/support - поддержка

/help - этот список
"""
    bot.send_message(message.chat.id, text)

@bot.message_handler(commands=["why_only_one_file"])
def why_only_one_file(message):
    log_user_action(message.from_user, "command.why_only_one_file")
    text = """Теперь к решению можно прикреплять несколько файлов.

Как это работает сейчас:

1. Откройте задачу и начните сдачу решения.
2. Отправьте текст решения одним или несколькими сообщениями.
3. Прикрепите нужное количество фото и документов отдельными сообщениями или альбомом.
4. Когда всё будет загружено, нажмите кнопку отправки решения или отправьте /done.

Для отмены используйте /cancel.
"""
    bot.send_message(message.chat.id, text)

VPN_STATS_ALLOWED_USERS = {962799806, 1133611562}
VPN_STATS_UNITS = {
    "B": ("Bytes", 1),
    "KiB": ("Kibibytes", 1024),
    "MiB": ("Mebibytes", 1024 ** 2),
    "GiB": ("Gibibytes", 1024 ** 3),
    "TiB": ("Tebibytes", 1024 ** 4),
}
VPN_STATS_SERVERS = [
    {
        "name": "🇩🇪 Germany VPN",
        "domain": "195.62.49.206",
        "metrics_url": "http://195.62.49.206:9090/metrics",
        "link": "http://195.62.49.206:9090",
    }
]


def can_use_vpn_stats(user_id) -> bool:
    return int(user_id) in VPN_STATS_ALLOWED_USERS


def format_vpn_bytes(bytes_count, unit="GiB"):
    if bytes_count < 0:
        return "N/A"

    name, divider = VPN_STATS_UNITS.get(unit, VPN_STATS_UNITS["GiB"])
    value = bytes_count / divider
    return f"{value:.2f} {name}"


def build_vpn_stats(unit="GiB"):
    unit = unit if unit in VPN_STATS_UNITS else "GiB"
    result_msg = f"🌐 VPN STATS ({unit})\n\n"

    for server in VPN_STATS_SERVERS:
        try:
            req = requests.get(server["metrics_url"], timeout=5)
            req.raise_for_status()
            txt = req.text

            recv = -1
            send = -1

            for line in txt.splitlines():
                if line.startswith("process_network_receive_bytes_total"):
                    recv = int(float(line.split()[1]))
                elif line.startswith("process_network_transmit_bytes_total"):
                    send = int(float(line.split()[1]))

            result_msg += (
                f"🔹 {server['name']}\n"
                f"🌍 {server['domain']}\n"
                f"🔗 {server['link']}\n"
                f"⬇ Receive: {format_vpn_bytes(recv, unit)}\n"
                f"⬆ Transmit: {format_vpn_bytes(send, unit)}\n\n"
            )
        except Exception as e:
            result_msg += (
                f"🔹 {server['name']}\n"
                f"{CROSS_HTML} Error: {html.escape(str(e))}\n\n"
            )

    return result_msg


def get_vpn_stats_keyboard():
    kb = types.InlineKeyboardMarkup()
    kb.add(
        ui_button("Bytes", callback_data="stats_B"),
        ui_button("KiB", callback_data="stats_KiB"),
        ui_button("MiB", callback_data="stats_MiB"),
        ui_button("GiB", callback_data="stats_GiB", style="primary"),
        ui_button("TiB", callback_data="stats_TiB"),
    )
    kb.add(ui_button("🏠 Главное меню", callback_data="mm_main_menu"))
    return kb


@bot.message_handler(commands=["vpnstats"])
def vpn_stats(message):
    if not can_use_vpn_stats(message.from_user.id):
        bot.send_message(message.chat.id, "no access")
        return

    msg = build_vpn_stats("GiB")
    bot.send_message(message.chat.id, msg, reply_markup=get_vpn_stats_keyboard(), parse_mode="HTML")


def ban(call):
    if call.from_user.id != get_admin_id():
        return
    prompt = bot.send_message(
        call.message.chat.id,
        "Введите ID пользователей для бана через пробел, запятую или новую строку.\nДля отмены отправьте /cancel."
    )
    bot.register_next_step_handler(prompt, ban_enter)

def ban_enter(message):
    if message.from_user.id != get_admin_id():
        return
    log_user_action(
        message.from_user,
        "admin.ban_input",
        f"target_ids={message.text or ''}"
    )
    text = (message.text or "").strip()
    if text.lower() in {"/cancel", "cancel"}:
        bot.send_message(message.chat.id, "Бан отменён.", reply_markup=build_admin_panel_markup())
        return

    user_ids, invalid_tokens = parse_user_ids_text(text)
    updated = []
    missing = []
    skipped = []
    for user_id in user_ids:
        if user_id == get_admin_id():
            skipped.append(str(user_id))
            continue
        if not sql_return.find_user_id(user_id):
            missing.append(str(user_id))
            continue
        sql_return.set_user_status(user_id, "banned")
        updated.append(str(user_id))

    sql_return.log_action(message.from_user.id, "ban", f"updated={updated} missing={missing} invalid={invalid_tokens} skipped={skipped}")

    summary = [
        "Результат бана:",
        f"Забанено: {', '.join(updated) if updated else 'никого'}",
    ]
    if missing:
        summary.append(f"Не найдены: {', '.join(missing)}")
    if invalid_tokens:
        summary.append(f"Некорректный ввод: {', '.join(invalid_tokens)}")
    if skipped:
        summary.append(f"Пропущены: {', '.join(skipped)}")

    bot.send_message(message.chat.id, "\n".join(summary), reply_markup=build_admin_panel_markup())

def unban(call):
    if call.from_user.id != get_admin_id():
        return
    prompt = bot.send_message(
        call.message.chat.id,
        "Введите ID пользователей для разбана через пробел, запятую или новую строку.\nДля отмены отправьте /cancel."
    )
    bot.register_next_step_handler(prompt, unban_enter)

def unban_enter(message):
    if message.from_user.id != get_admin_id():
        return
    log_user_action(
        message.from_user,
        "admin.unban_input",
        f"target_ids={message.text or ''}"
    )
    text = (message.text or "").strip()
    if text.lower() in {"/cancel", "cancel"}:
        bot.send_message(message.chat.id, "Разбан отменён.", reply_markup=build_admin_panel_markup())
        return

    user_ids, invalid_tokens = parse_user_ids_text(text)
    updated = []
    missing = []
    for user_id in user_ids:
        if not sql_return.find_user_id(user_id):
            missing.append(str(user_id))
            continue
        sql_return.set_user_status(user_id, "approved")
        updated.append(str(user_id))

    sql_return.log_action(message.from_user.id, "unban", f"updated={updated} missing={missing} invalid={invalid_tokens}")

    summary = [
        "Результат разбана:",
        f"Разбанено: {', '.join(updated) if updated else 'никого'}",
    ]
    if missing:
        summary.append(f"Не найдены: {', '.join(missing)}")
    if invalid_tokens:
        summary.append(f"Некорректный ввод: {', '.join(invalid_tokens)}")

    bot.send_message(message.chat.id, "\n".join(summary), reply_markup=build_admin_panel_markup())

def stop_confirm(call):
    if call.from_user.id == get_admin_id():
        bot.edit_message_text(
            build_admin_panel_text(confirm_stop=True),
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=build_admin_panel_markup(confirm_stop=True)
        )
    else:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="mm_main_menu"))
        bot.edit_message_text(
            "У вас нет доступа к панели администратора.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=markup
        )
        bot.send_message(config["admin_id"], f"Пользователь {call.from_user.id} попытался открыть подтверждение остановки.")

def stop(call):
    global is_polling
   
    if call.from_user.id == get_admin_id():
        bot.send_message(call.message.chat.id, "Подождите...")
        broadcast(f"{CROSS_HTML} Бот временно закрыт на технические работы.")
        is_polling = False
        bot.send_message(call.message.chat.id, "Бот успешно отправил все сообщения.")
        bot.stop_polling()

def broadcast(message: str):
    for i in sql_return.all_users():
        try:
            kwargs = {}
            if "<tg-emoji" in message or "<blockquote>" in message:
                kwargs["parse_mode"] = "HTML"
            bot.send_message(i[0], message, **kwargs)
        except:
            pass

def admin_panel(call):
    if call.from_user.id == get_admin_id():
        bot.edit_message_text(
            build_admin_panel_text(),
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=build_admin_panel_markup()
        )
    else:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="mm_main_menu"))
        bot.edit_message_text(
            "У вас нет доступа к панели администратора.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=markup
        )
        bot.send_message(config["admin_id"], f"Пользователь {call.from_user.id} попытался открыть панель администратора.")

def admin_backup(call):
    if call.from_user.id != config["admin_id"]:
        return
    bot.send_message(call.message.chat.id, "Запускаю бэкап, сейчас пришлю архивы.")
    Thread(target=backup_databases_and_files_split, daemon=True).start()

def admin_broadcast_start(call):
    if call.from_user.id != get_admin_id():
        return
    prompt = bot.send_message(
        call.message.chat.id,
        "Отправьте одно сообщение, которое нужно разослать всем пользователям.\n"
        "Поддерживаются текст, фото, документы, видео, аудио, голосовые, анимации и стикеры.\n"
        "Для отмены отправьте /cancel."
    )
    bot.register_next_step_handler(prompt, admin_broadcast_receive)

def admin_broadcast_receive(message):
    if message.from_user.id != get_admin_id():
        return

    log_user_action(
        message.from_user,
        "admin.broadcast_input",
        f"content_type={message.content_type}"
    )

    if message.content_type == "text" and (message.text or "").strip().lower() in {"/cancel", "cancel"}:
        bot.send_message(message.chat.id, "Рассылка отменена.", reply_markup=build_admin_panel_markup())
        return

    if message.content_type not in BROADCAST_ALLOWED_CONTENT_TYPES:
        bot.send_message(
            message.chat.id,
            "Этот тип сообщения пока не поддерживается для рассылки. Попробуйте другой формат или /cancel."
        )
        bot.register_next_step_handler(message, admin_broadcast_receive)
        return

    draft_id = next_broadcast_draft_id()
    with broadcast_drafts_lock:
        broadcast_drafts[draft_id] = {
            "draft_id": draft_id,
            "from_chat_id": message.chat.id,
            "message_id": message.message_id,
            "created_by": message.from_user.id,
            "content_type": message.content_type,
            "created_at": time.time(),
        }

    bot.send_message(
        message.chat.id,
        build_broadcast_preview_html(message),
        parse_mode="HTML",
        reply_markup=build_broadcast_confirm_markup(draft_id)
    )

def admin_broadcast_confirm(call, draft_id: int):
    if call.from_user.id != get_admin_id():
        return

    with broadcast_drafts_lock:
        draft = broadcast_drafts.pop(draft_id, None)

    if not draft:
        bot.send_message(call.message.chat.id, "Черновик рассылки не найден или уже обработан.")
        return

    status_message = bot.send_message(call.message.chat.id, "Начинаю рассылку...")
    sent_count = 0
    failed_count = 0
    for user in sql_return.all_users():
        user_id = user[0]
        try:
            bot.copy_message(
                user_id,
                draft["from_chat_id"],
                draft["message_id"]
            )
            sent_count += 1
        except Exception as error:
            failed_count += 1
            log(f"broadcast failed: user_id={user_id} error={error}")

    sql_return.log_action(call.from_user.id, "admin_broadcast", f"draft_id={draft_id} sent={sent_count} failed={failed_count}")
    safe_delete_message(call.message.chat.id, call.message.message_id)
    safe_delete_message(status_message.chat.id, status_message.message_id)
    bot.send_message(
        call.message.chat.id,
        f"{CHECK_HTML} Рассылка завершена.\nОтправлено: {sent_count}\nОшибок: {failed_count}",
        parse_mode="HTML",
        reply_markup=build_admin_panel_markup()
    )

def admin_broadcast_cancel(call, draft_id: int):
    if call.from_user.id != get_admin_id():
        return

    with broadcast_drafts_lock:
        broadcast_drafts.pop(draft_id, None)

    safe_delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(
        call.message.chat.id,
        "Рассылка отменена.",
        reply_markup=build_admin_panel_markup()
    )

broadcast(f"{CHECK_HTML} Бот снова работает!")

# def infinite_update():
#     print("infinite_update started")
#     while True:
#         try:
#             prog.update_sheet()
#         except Exception as e:
#             # try:
#             #     bot.send_message(config["admin_id"], f"Произошла ошибка в infinite_update: {str(e)}")
#             # except:
#             #     pass
#             sql_return.bug_report(str(e))
#         time.sleep(60 * 3)
#         if not is_polling:
#             break

# update_thread = Thread(target=infinite_update)
# update_thread.start()

# === Settings ===
# Держи меньше лимита Telegram (на практике часто режут по 40–50MB).
try:
    MAX_PART_MB = int(config.get("backup_max_part_mb", 45))
except Exception:
    MAX_PART_MB = 45
MAX_PART_BYTES = MAX_PART_MB * 1024 * 1024
try:
    ZIP_COMPRESSLEVEL = int(config.get("backup_compresslevel", 9))
except Exception:
    ZIP_COMPRESSLEVEL = 9

ERROR_ADMIN_SILENCE_SECONDS = 60 * 10
POLLING_RETRY_SLEEP_SECONDS = 5
POLLING_BACKOFF_MAX_SECONDS = 60

error_stats_lock = Lock()
error_counts = Counter()
error_stats_since = datetime.datetime.now()
last_admin_error_at = {}

def log(msg: str) -> None:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)

def normalize_error_message(msg: str) -> str:
    return " ".join(msg.split())

def error_signature(context: str, msg: str) -> str:
    clean_msg = normalize_error_message(msg)
    if len(clean_msg) > 200:
        clean_msg = f"{clean_msg[:200]}..."
    return f"{context}: {clean_msg}"

def is_transient_polling_error(msg: str) -> bool:
    msg_l = msg.lower()
    for substr in (
        "remote end closed connection without response",
        "remote disconnected",
        "connection aborted",
        "read timed out",
        "connect timeout",
        "connection reset by peer",
        "max retries exceeded",
        "temporarily unavailable",
        "bad status line",
        "eof occurred in violation of protocol",
    ):
        if substr in msg_l:
            return True
    return False

def record_error(signature: str) -> None:
    global error_stats_since
    now = datetime.datetime.now()
    with error_stats_lock:
        if not error_counts:
            error_stats_since = now
        error_counts[signature] += 1

def append_error_log(line: str) -> None:
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(POLLING_ERRORS_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def notify_admin_rate_limited(signature: str, message: str) -> None:
    now = time.time()
    last = last_admin_error_at.get(signature, 0)
    if now - last < ERROR_ADMIN_SILENCE_SECONDS:
        return
    last_admin_error_at[signature] = now
    try:
        bot.send_message(config["admin_id"], f"Произошла ошибка: {message}")
    except Exception:
        log("error: failed to notify admin about error")

def consume_error_stats():
    global error_stats_since
    with error_stats_lock:
        snapshot = dict(error_counts)
        error_counts.clear()
        since = error_stats_since
        error_stats_since = datetime.datetime.now()
    return since, error_stats_since, snapshot

def send_daily_error_summary(only_if_errors: bool = True) -> None:
    since, until, snapshot = consume_error_stats()
    if only_if_errors and not snapshot:
        return
    if not snapshot:
        summary = (
            "Ежедневная статистика ошибок "
            f"({since.strftime('%Y-%m-%d %H:%M:%S')} – {until.strftime('%Y-%m-%d %H:%M:%S')}): "
            f"ошибок нет {CHECK_HTML}"
        )
    else:
        lines = [
            "Ежедневная статистика ошибок "
            f"({since.strftime('%Y-%m-%d %H:%M:%S')} – {until.strftime('%Y-%m-%d %H:%M:%S')})"
        ]
        for sig, count in sorted(snapshot.items(), key=lambda x: -x[1])[:20]:
            lines.append(f"{count}× {sig}")
        summary = "\n".join(lines)
    try:
        kwargs = {"parse_mode": "HTML"} if "<tg-emoji" in summary else {}
        bot.send_message(config["admin_id"], summary, **kwargs)
    except Exception:
        log("error: failed to send daily error summary")

def handle_polling_error(e: Exception) -> None:
    msg = str(e)
    signature = error_signature("polling", msg)
    log(f"polling error: {msg}")
    record_error(signature)
    append_error_log(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {signature}")
    try:
        sql_return.bug_report(signature)
    except Exception:
        pass
    if not is_transient_polling_error(msg):
        notify_admin_rate_limited(signature, msg)

def safe_int(x, default=0) -> int:
    try:
        return int(x)
    except Exception:
        return default

def send_file_to_admin(path: str, caption: str = "") -> None:
    admin_id = safe_int(config.get("admin_id"))
    with open(path, "rb") as f:
        kwargs = {"caption": caption}
        if "<tg-emoji" in caption:
            kwargs["parse_mode"] = "HTML"
        bot.send_document(admin_id, f, **kwargs)

def backup_make_db_zip() -> str:
    """Создаёт zip с users.db/files.db (обычно маленький) и возвращает имя архива."""
    archive_name = f"backup_db_{datetime.datetime.now().strftime('%Y-%m-%d')}.zip"
    with zipfile.ZipFile(archive_name, "w", zipfile.ZIP_DEFLATED, compresslevel=ZIP_COMPRESSLEVEL) as zipf:
        added = 0
        for db_file in ("users.db", "files.db"):
            if os.path.exists(db_file):
                zipf.write(db_file)
                added += 1
                log(f"backup: added {db_file}")
    size = os.path.getsize(archive_name)
    log(f"backup: DB ZIP READY name={archive_name} files={added} size={size} bytes")
    return archive_name

def backup_make_files_zip_single(max_bytes: int):
    """
    Пытается собрать весь files/ в один zip.
    Возвращает (archive_name, added_files, size_bytes) или (None, added_files, size_bytes).
    """
    if not os.path.isdir("files"):
        log("backup: folder 'files' not found, skipping files backup")
        return None, 0, 0

    base_date = datetime.datetime.now().strftime("%Y-%m-%d")
    archive_name = f"backup_files_{base_date}.zip"
    added = 0

    with zipfile.ZipFile(archive_name, "w", zipfile.ZIP_DEFLATED, compresslevel=ZIP_COMPRESSLEVEL) as zipf:
        for root, dirs, files in os.walk("files"):
            for filename in files:
                path = os.path.join(root, filename)
                try:
                    os.path.getsize(path)
                except OSError as e:
                    log(f"backup: skip unreadable {path}: {e!r}")
                    continue
                try:
                    zipf.write(path)
                    added += 1
                except Exception as e:
                    log(f"backup: failed to add {path}: {e!r}")

    try:
        size = os.path.getsize(archive_name)
    except OSError:
        size = 0
    log(f"backup: FILES ZIP READY name={archive_name} files={added} size={size} bytes")

    if size <= max_bytes:
        return archive_name, added, size

    log(f"backup: FILES ZIP too large ({size} bytes), will split")
    try:
        os.remove(archive_name)
    except Exception:
        pass
    return None, added, size

def backup_make_files_splits(max_part_bytes: int = MAX_PART_BYTES):
    """
    Создаёт несколько zip-частей для папки files/ так, чтобы каждая часть была <= max_part_bytes (примерно).
    Возвращает (parts, added_files).
    """
    base_date = datetime.datetime.now().strftime("%Y-%m-%d")
    parts = []
    added = 0
    part_idx = 1

    zipf = None
    archive_name = None
    current_size = 0

    def new_zip():
        nonlocal part_idx, archive_name, zipf, current_size
        if zipf is not None:
            zipf.close()
        archive_name = f"backup_files_{base_date}_part{part_idx}.zip"
        zipf = zipfile.ZipFile(archive_name, "w", zipfile.ZIP_DEFLATED, compresslevel=ZIP_COMPRESSLEVEL)
        parts.append(archive_name)
        current_size = 0
        log(f"backup: opened {archive_name}")
        part_idx += 1

    if not os.path.isdir("files"):
        log("backup: folder 'files' not found, skipping files backup")
        return [], 0

    new_zip()

    for root, dirs, files in os.walk("files"):
        for filename in files:
            path = os.path.join(root, filename)

            try:
                file_size = os.path.getsize(path)
            except OSError as e:
                log(f"backup: skip unreadable {path}: {e!r}")
                continue

            # Если файл сам по себе огромный — кладём его в отдельную часть.
            if file_size > max_part_bytes:
                # Закрываем текущую часть (если она пустая/не пустая — не важно), открываем новую
                new_zip()
                try:
                    zipf.write(path)
                    added += 1
                    log(f"backup: added HUGE file {path} size={file_size} bytes")
                except Exception as e:
                    log(f"backup: failed to add HUGE file {path}: {e!r}")
                # После huge-файла начинаем ещё одну новую часть, чтобы не мешать дальше
                new_zip()
                continue

            # Если уже набрали лимит — начинаем новый архив
            if current_size >= max_part_bytes:
                new_zip()

            try:
                zipf.write(path)
                try:
                    zipf.fp.flush()
                except Exception:
                    pass
                try:
                    current_size = zipf.fp.tell()
                except Exception:
                    try:
                        current_size = os.path.getsize(archive_name)
                    except Exception:
                        current_size += file_size
                added += 1
            except Exception as e:
                log(f"backup: failed to add {path}: {e!r}")

    if zipf is not None:
        zipf.close()

    # Логи размеров частей
    for p in parts:
        try:
            log(f"backup: PART READY name={p} size={os.path.getsize(p)} bytes")
        except OSError:
            pass

    return parts, added


def backup_make_logs_zip_single(max_bytes: int):
    if not os.path.isdir(LOGS_DIR):
        log("backup: folder 'logs' not found, skipping logs backup")
        return None, 0, 0

    base_date = datetime.datetime.now().strftime("%Y-%m-%d")
    archive_name = f"backup_logs_{base_date}.zip"
    added = 0

    with zipfile.ZipFile(archive_name, "w", zipfile.ZIP_DEFLATED, compresslevel=ZIP_COMPRESSLEVEL) as zipf:
        for root, dirs, files in os.walk(LOGS_DIR):
            for filename in files:
                path = os.path.join(root, filename)
                try:
                    os.path.getsize(path)
                except OSError as e:
                    log(f"backup: skip unreadable log {path}: {e!r}")
                    continue
                try:
                    arcname = os.path.relpath(path, start=os.getcwd())
                    zipf.write(path, arcname=arcname)
                    added += 1
                except Exception as e:
                    log(f"backup: failed to add log {path}: {e!r}")

    try:
        size = os.path.getsize(archive_name)
    except OSError:
        size = 0
    log(f"backup: LOGS ZIP READY name={archive_name} files={added} size={size} bytes")

    if size <= max_bytes:
        return archive_name, added, size

    log(f"backup: LOGS ZIP too large ({size} bytes), will split")
    try:
        os.remove(archive_name)
    except Exception:
        pass
    return None, added, size


def backup_make_logs_splits(max_part_bytes: int = MAX_PART_BYTES):
    base_date = datetime.datetime.now().strftime("%Y-%m-%d")
    parts = []
    added = 0
    part_idx = 1

    zipf = None
    archive_name = None
    current_size = 0

    def new_zip():
        nonlocal part_idx, archive_name, zipf, current_size
        if zipf is not None:
            zipf.close()
        archive_name = f"backup_logs_{base_date}_part{part_idx}.zip"
        zipf = zipfile.ZipFile(archive_name, "w", zipfile.ZIP_DEFLATED, compresslevel=ZIP_COMPRESSLEVEL)
        parts.append(archive_name)
        current_size = 0
        log(f"backup: opened {archive_name}")
        part_idx += 1

    if not os.path.isdir(LOGS_DIR):
        log("backup: folder 'logs' not found, skipping logs backup")
        return [], 0

    new_zip()

    for root, dirs, files in os.walk(LOGS_DIR):
        for filename in files:
            path = os.path.join(root, filename)

            try:
                file_size = os.path.getsize(path)
            except OSError as e:
                log(f"backup: skip unreadable log {path}: {e!r}")
                continue

            if file_size > max_part_bytes:
                new_zip()
                try:
                    arcname = os.path.relpath(path, start=os.getcwd())
                    zipf.write(path, arcname=arcname)
                    added += 1
                    log(f"backup: added HUGE log {path} size={file_size} bytes")
                except Exception as e:
                    log(f"backup: failed to add HUGE log {path}: {e!r}")
                new_zip()
                continue

            if current_size >= max_part_bytes:
                new_zip()

            try:
                arcname = os.path.relpath(path, start=os.getcwd())
                zipf.write(path, arcname=arcname)
                try:
                    zipf.fp.flush()
                except Exception:
                    pass
                try:
                    current_size = zipf.fp.tell()
                except Exception:
                    try:
                        current_size = os.path.getsize(archive_name)
                    except Exception:
                        current_size += file_size
                added += 1
            except Exception as e:
                log(f"backup: failed to add log {path}: {e!r}")

    if zipf is not None:
        zipf.close()

    for part in parts:
        try:
            log(f"backup: LOG PART READY name={part} size={os.path.getsize(part)} bytes")
        except OSError:
            pass

    return parts, added

def backup_cleanup(paths):
    for p in paths:
        try:
            os.remove(p)
            log(f"backup: removed {p}")
        except Exception as e:
            log(f"backup: failed to remove {p}: {e!r}")

def backup_databases_and_files_split():
    """
    Делает:
    1) zip БД -> отправляет
    2) zip-части files/ -> отправляет по одной (если есть)
    3) zip-части logs/ -> отправляет по одной (если есть)
    """
    created = []
    try:
        log("backup: START")

        # 1) БД
        db_zip = backup_make_db_zip()
        created.append(db_zip)
        send_file_to_admin(db_zip, caption=f"Backup DB {CHECK_HTML}")
        log("backup: DB SENT")

        # 2) files/ (try single zip, else split)
        files_zip, added_files, size = backup_make_files_zip_single(MAX_PART_BYTES)
        if files_zip:
            created.append(files_zip)
            caption = f"Backup files {CHECK_HTML}\nSize: {size} bytes"
            send_file_to_admin(files_zip, caption=caption)
            log(f"backup: SENT {files_zip}")
        else:
            parts, added_files = backup_make_files_splits(MAX_PART_BYTES)
            created.extend(parts)

            if parts:
                total_parts = len(parts)
                log(f"backup: sending {total_parts} file parts, files_count={added_files}")
                for i, part in enumerate(parts, 1):
                    size = os.path.getsize(part)
                    caption = f"Backup files {CHECK_HTML} ({i}/{total_parts})\nSize: {size} bytes"
                    send_file_to_admin(part, caption=caption)
                    log(f"backup: SENT {part} ({i}/{total_parts})")
            else:
                log("backup: no files parts to send")

        # 3) logs/
        logs_zip, added_logs, size = backup_make_logs_zip_single(MAX_PART_BYTES)
        if logs_zip:
            created.append(logs_zip)
            caption = f"Backup logs {CHECK_HTML}\nFiles: {added_logs}\nSize: {size} bytes"
            send_file_to_admin(logs_zip, caption=caption)
            log(f"backup: SENT {logs_zip}")
        else:
            log_parts, added_logs = backup_make_logs_splits(MAX_PART_BYTES)
            created.extend(log_parts)

            if log_parts:
                total_parts = len(log_parts)
                log(f"backup: sending {total_parts} log parts, files_count={added_logs}")
                for i, part in enumerate(log_parts, 1):
                    size = os.path.getsize(part)
                    caption = f"Backup logs {CHECK_HTML} ({i}/{total_parts})\nFiles: {added_logs}\nSize: {size} bytes"
                    send_file_to_admin(part, caption=caption)
                    log(f"backup: SENT {part} ({i}/{total_parts})")
            else:
                log("backup: no logs parts to send")

        backup_cleanup(created)
        log("backup: DONE")

    except Exception as e:
        log(f"backup ERROR: {repr(e)}")
        try:
            sql_return.bug_report(f"Backup error: {repr(e)}")
        except Exception:
            pass
        # На всякий случай чистим то, что успели создать
        backup_cleanup(created)

def backup_scheduler():
    # Сразу один бэкап при старте
    backup_databases_and_files_split()
    send_daily_error_summary(only_if_errors=True)

    while is_polling:
        now = datetime.datetime.now()
        next_midnight = (now + datetime.timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        sleep_seconds = max(1, (next_midnight - now).total_seconds())
        log(f"backup: next run at {next_midnight.strftime('%Y-%m-%d %H:%M:%S')} (sleep {int(sleep_seconds)}s)")
        time.sleep(sleep_seconds)

        if not is_polling:
            break

        backup_databases_and_files_split()
        send_daily_error_summary(only_if_errors=True)

# Запуск планировщика в отдельном потоке
backup_thread = Thread(target=backup_scheduler, daemon=True)
backup_thread.start()

lesson_notification_thread = Thread(target=lesson_notification_scheduler, daemon=True)
lesson_notification_thread.start()

backoff_seconds = POLLING_RETRY_SLEEP_SECONDS
while is_polling:
    log("polling started")
    try:
        bot.polling(none_stop=True)
        backoff_seconds = POLLING_RETRY_SLEEP_SECONDS
    except Exception as e:
        handle_polling_error(e)
        time.sleep(backoff_seconds)
        backoff_seconds = min(backoff_seconds * 2, POLLING_BACKOFF_MAX_SECONDS)
