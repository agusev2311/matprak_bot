import telebot
from telebot import types
import sqlite3
import time
import datetime
import html
import io
import re
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

print("main.py started")

with open('config.json', 'r') as file:
    config = json.load(file)

sql_return.init_db()
sql_return.init_files_db()

is_polling = True

bot = telebot.TeleBot(config["tg-token"])

GPT_SQL_ALLOWED_EXTRA_USER_ID = 930442932
MAX_UPLOAD_SIZE_BYTES = 15 * 1024 * 1024

gpt_sql_requests_lock = Lock()
gpt_sql_requests = {}
gpt_sql_request_seq = 0

TASKS_COLUMN_ALIASES = {
    "text": "description",
    "task_text": "description",
    "problem_text": "description",
    "number": "title",
    "task_number": "title",
    "name": "title",
}

LESSONS_COLUMN_ALIASES = {
    "name": "title",
    "lesson_name": "title",
    "text": "title",
    "state": "status",
}

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
        ("solution", "solution.open"),
        ("self_reject", "solution.self_reject"),
        ("undo_self_reject", "solution.self_reject_undo"),
        ("admin_panel_open", "admin.panel_open"),
        ("admin_panel_backup", "admin.backup"),
        ("admin_panel_stop", "admin.stop"),
        ("admin_panel_ban", "admin.ban_prompt"),
        ("admin_panel_unban", "admin.unban_prompt"),
        ("admin_panel_conf_stop", "admin.stop_confirm"),
        ("gptsql_accept_", "gpt_lesson.sql_accept"),
        ("gptsql_reject_", "gpt_lesson.sql_reject"),
        ("gptsql_retry_", "gpt_lesson.sql_retry"),
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

    sql_return.save_file(message.content_type, new_file_name, save_path, message.from_user.id)

    return {
        "file_path": save_path,
        "file_type": message.content_type,
        "stored_file_name": new_file_name,
        "original_file_name": original_file_name,
    }


def split_sql_statements(sql_text: str) -> list[str]:
    statements = []
    current = []
    in_single_quote = False
    in_double_quote = False
    index = 0

    while index < len(sql_text):
        char = sql_text[index]

        if char == "'" and not in_double_quote:
            if in_single_quote and index + 1 < len(sql_text) and sql_text[index + 1] == "'":
                current.append(char)
                current.append(sql_text[index + 1])
                index += 2
                continue
            in_single_quote = not in_single_quote
        elif char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote

        if char == ";" and not in_single_quote and not in_double_quote:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)

        index += 1

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)

    return statements


def split_sql_csv(items_text: str) -> list[str]:
    items = []
    current = []
    depth = 0
    in_single_quote = False
    in_double_quote = False
    index = 0

    while index < len(items_text):
        char = items_text[index]

        if char == "'" and not in_double_quote:
            if in_single_quote and index + 1 < len(items_text) and items_text[index + 1] == "'":
                current.append(char)
                current.append(items_text[index + 1])
                index += 2
                continue
            in_single_quote = not in_single_quote
        elif char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
        elif char == "(" and not in_single_quote and not in_double_quote:
            depth += 1
        elif char == ")" and not in_single_quote and not in_double_quote and depth > 0:
            depth -= 1

        if char == "," and depth == 0 and not in_single_quote and not in_double_quote:
            item = "".join(current).strip()
            if item:
                items.append(item)
            current = []
        else:
            current.append(char)

        index += 1

    tail = "".join(current).strip()
    if tail:
        items.append(tail)

    return items


def normalize_identifier(identifier: str) -> str:
    return identifier.strip().strip('`"[]').lower()


def normalize_lessons_insert_statement(statement: str) -> str:
    match = re.match(
        r"^\s*INSERT\s+INTO\s+lessons\s*\((.*?)\)\s*VALUES\s*\((.*)\)\s*$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return statement

    columns = split_sql_csv(match.group(1))
    values = split_sql_csv(match.group(2))

    if len(columns) != len(values):
        raise ValueError("В INSERT INTO lessons количество колонок и значений не совпадает.")

    mapped_values = {}
    for raw_column, value in zip(columns, values):
        column = normalize_identifier(raw_column)
        normalized_column = LESSONS_COLUMN_ALIASES.get(column, column)
        if normalized_column not in {"id", "course_id", "title", "status", "open_date"}:
            raise ValueError(f"Недопустимая колонка lessons: {raw_column}")
        if normalized_column not in mapped_values:
            mapped_values[normalized_column] = value

    if "course_id" not in mapped_values:
        raise ValueError("В INSERT INTO lessons отсутствует course_id.")
    if "title" not in mapped_values:
        mapped_values["title"] = "'Новый урок'"
    if "status" not in mapped_values:
        mapped_values["status"] = "'open'"

    ordered_columns = ["id", "course_id", "title", "status", "open_date"]
    final_columns = [col for col in ordered_columns if col in mapped_values]
    final_values = [mapped_values[col] for col in final_columns]
    return f"INSERT INTO lessons ({', '.join(final_columns)}) VALUES ({', '.join(final_values)})"


def normalize_tasks_insert_statement(statement: str, default_title_index: int) -> tuple[str, int]:
    match = re.match(
        r"^\s*INSERT\s+INTO\s+tasks\s*\((.*?)\)\s*VALUES\s*\((.*)\)\s*$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return statement, default_title_index

    columns = split_sql_csv(match.group(1))
    values = split_sql_csv(match.group(2))

    if len(columns) != len(values):
        raise ValueError("В INSERT INTO tasks количество колонок и значений не совпадает.")

    mapped_values = {}
    for raw_column, value in zip(columns, values):
        column = normalize_identifier(raw_column)
        normalized_column = TASKS_COLUMN_ALIASES.get(column, column)

        if normalized_column not in {"id", "lesson_id", "title", "status", "deadline", "description"}:
            raise ValueError(f"Недопустимая колонка tasks: {raw_column}")

        if normalized_column not in mapped_values:
            mapped_values[normalized_column] = value

    if "lesson_id" not in mapped_values:
        raise ValueError("В INSERT INTO tasks отсутствует lesson_id.")
    if "title" not in mapped_values:
        mapped_values["title"] = f"'Задача {default_title_index}'"
        default_title_index += 1
    if "status" not in mapped_values:
        mapped_values["status"] = "'open'"
    if "description" not in mapped_values:
        mapped_values["description"] = "NULL"

    ordered_columns = ["id", "lesson_id", "title", "status", "deadline", "description"]
    final_columns = [col for col in ordered_columns if col in mapped_values]
    final_values = [mapped_values[col] for col in final_columns]
    statement_sql = f"INSERT INTO tasks ({', '.join(final_columns)}) VALUES ({', '.join(final_values)})"
    return statement_sql, default_title_index


def normalize_lesson_sql(sql_text: str) -> str:
    if not sql_text or not sql_text.strip():
        raise ValueError("Пустой SQL.")

    statements = split_sql_statements(sql_text)
    if not statements:
        raise ValueError("SQL не содержит команд.")

    normalized = []
    lessons_count = 0
    tasks_count = 0
    default_title_index = 1

    for statement in statements:
        compact = statement.strip()
        if not compact:
            continue

        if re.match(r"^\s*INSERT\s+INTO\s+lessons\b", compact, flags=re.IGNORECASE):
            normalized.append(normalize_lessons_insert_statement(compact))
            lessons_count += 1
            continue

        if re.match(r"^\s*INSERT\s+INTO\s+tasks\b", compact, flags=re.IGNORECASE):
            statement_sql, default_title_index = normalize_tasks_insert_statement(compact, default_title_index)
            normalized.append(statement_sql)
            tasks_count += 1
            continue

        if re.match(r"^\s*(BEGIN|COMMIT|END|ROLLBACK)\b", compact, flags=re.IGNORECASE):
            continue

        raise ValueError(f"Недопустимая SQL-команда: {compact[:80]}")

    if lessons_count == 0:
        raise ValueError("В SQL нет INSERT INTO lessons.")
    if tasks_count == 0:
        raise ValueError("В SQL нет INSERT INTO tasks.")

    return ";\n\n".join(normalized) + ";"


def get_gpt_sql_review_markup(request_id: int):
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ Применить", callback_data=f"gptsql_accept_{request_id}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"gptsql_reject_{request_id}")
    )
    markup.add(types.InlineKeyboardButton("🔁 На повторную проверку", callback_data=f"gptsql_retry_{request_id}"))
    return markup


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

    sql_text = request.get("sql", "").strip()
    if not sql_text:
        bot.send_message(admin_id, f"⚠️ У заявки #{request_id} пустой SQL.")
        return

    truncated = False
    sql_for_message = sql_text
    if len(sql_for_message) > 3000:
        truncated = True
        sql_for_message = sql_for_message[:3000] + "\n-- ...обрезано..."

    review_title = f"Проверка SQL для заявки #{request_id}\nКурс: {course_title}"
    if admin_feedback:
        review_title += f"\nКомментарий для исправления: {html.escape(admin_feedback)}"

    review_text = f"{review_title}\n\n<pre>{html.escape(sql_for_message)}</pre>"
    if truncated:
        sql_file = io.BytesIO(sql_text.encode("utf-8"))
        sql_file.name = f"gpt_request_{request_id}.sql"
        bot.send_document(admin_id, sql_file, caption=f"Полный SQL для заявки #{request_id}")
        review_text += "\n\nПолный SQL отправлен отдельным файлом."

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
        previous_sql = request.get("sql", "")
        initiator_id = request["initiator_id"]

    try:
        if admin_feedback:
            sql_text = parsing_gpt.fix_lesson_sql(
                lesson_file_path=file_path,
                course_id=course_id,
                previous_sql=previous_sql,
                admin_feedback=admin_feedback,
            )
        else:
            sql_text = parsing_gpt.generate_lesson_sql(
                lesson_file_path=file_path,
                course_id=course_id,
            )
        sql_text = normalize_lesson_sql(sql_text)
    except Exception as error:
        with gpt_sql_requests_lock:
            request = gpt_sql_requests.get(request_id)
            if request:
                request["status"] = "error"

        error_text = f"{type(error).__name__}: {error}"
        bot.send_message(initiator_id, f"❌ Не удалось получить SQL от GPT: {error_text}")
        if initiator_id != get_admin_id():
            bot.send_message(get_admin_id(), f"❌ Ошибка GPT в заявке #{request_id}: {error_text}")
        return

    with gpt_sql_requests_lock:
        request = gpt_sql_requests.get(request_id)
        if not request:
            return
        request["status"] = "awaiting_admin"
        request["sql"] = sql_text
        if admin_feedback:
            request["last_feedback"] = admin_feedback

    send_gpt_sql_for_review(request_id, admin_feedback)
    if admin_feedback:
        bot.send_message(initiator_id, f"🔁 SQL по заявке #{request_id} исправлен и снова отправлен администратору.")
    else:
        bot.send_message(initiator_id, f"✅ SQL по заявке #{request_id} отправлен администратору на проверку.")


def gpt_add_lesson_start(call, course_id: int):
    if not can_use_gpt_lesson_button(call.from_user.id):
        bot.send_message(call.message.chat.id, "У вас нет доступа к этой функции.")
        return
    if not sql_return.find_course_id(course_id):
        bot.send_message(call.message.chat.id, "Курс не найден.")
        return

    bot.edit_message_text(
        "Отправьте фото листка или PDF с задачами.\n\n"
        "После загрузки я отправлю файл в GPT и подготовлю SQL для проверки админом.\n"
        "Для отмены отправьте /cancel.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
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
        f"Файл получен. Запускаю GPT и готовлю SQL (заявка #{request_id}). Это может занять до минуты."
    )
    Thread(target=run_gpt_sql_generation, args=(request_id,), daemon=True).start()


def gpt_sql_accept(call, request_id: int):
    if call.from_user.id != get_admin_id():
        bot.send_message(call.message.chat.id, "Только админ может подтверждать SQL.")
        return

    with gpt_sql_requests_lock:
        request = gpt_sql_requests.get(request_id)
    if not request:
        bot.send_message(call.message.chat.id, f"Заявка #{request_id} уже обработана или не найдена.")
        return

    sql_text = request.get("sql", "").strip()
    if not sql_text:
        bot.send_message(call.message.chat.id, f"В заявке #{request_id} нет SQL для выполнения.")
        return

    try:
        sql_to_execute = normalize_lesson_sql(sql_text)
        if sql_to_execute != sql_text:
            with gpt_sql_requests_lock:
                if request_id in gpt_sql_requests:
                    gpt_sql_requests[request_id]["sql"] = sql_to_execute

        with sqlite3.connect(config["db-name"]) as conn:
            conn.executescript(sql_to_execute)
            conn.commit()
    except Exception as error:
        bot.send_message(call.message.chat.id, f"❌ Ошибка применения SQL по заявке #{request_id}: {error}")
        return

    with gpt_sql_requests_lock:
        gpt_sql_requests.pop(request_id, None)

    sql_return.log_action(call.from_user.id, "gpt_lesson_request_accepted", f"{request_id}")
    bot.send_message(call.message.chat.id, f"✅ SQL из заявки #{request_id} применен к базе.")

    if request["initiator_id"] != call.from_user.id:
        bot.send_message(request["initiator_id"], f"✅ Админ подтвердил заявку #{request_id}. SQL применен к базе.")


def gpt_sql_reject(call, request_id: int):
    if call.from_user.id != get_admin_id():
        bot.send_message(call.message.chat.id, "Только админ может отклонять SQL.")
        return

    with gpt_sql_requests_lock:
        request = gpt_sql_requests.pop(request_id, None)

    if not request:
        bot.send_message(call.message.chat.id, f"Заявка #{request_id} уже обработана или не найдена.")
        return

    sql_return.log_action(call.from_user.id, "gpt_lesson_request_rejected", f"{request_id}")
    bot.send_message(call.message.chat.id, f"🗑 Заявка #{request_id} отклонена.")

    if request["initiator_id"] != call.from_user.id:
        bot.send_message(request["initiator_id"], f"❌ Админ отклонил заявку #{request_id}.")


def gpt_sql_retry(call, request_id: int):
    if call.from_user.id != get_admin_id():
        bot.send_message(call.message.chat.id, "Только админ может отправлять SQL на доработку.")
        return

    with gpt_sql_requests_lock:
        request = gpt_sql_requests.get(request_id)
    if not request:
        bot.send_message(call.message.chat.id, f"Заявка #{request_id} уже обработана или не найдена.")
        return

    bot.send_message(
        call.message.chat.id,
        f"Введите комментарий с ошибками для заявки #{request_id}. "
        "Я отправлю его в GPT для исправления SQL.\nДля отмены отправьте /cancel."
    )
    bot.register_next_step_handler(call.message, gpt_sql_retry_feedback, request_id)


def gpt_sql_retry_feedback(message, request_id: int):
    log_user_action(
        message.from_user,
        "gpt_lesson.retry_feedback_input",
        f"request_id={request_id}, text={message.text or ''}"
    )
    if message.from_user.id != get_admin_id():
        bot.send_message(message.chat.id, "Только админ может отправлять SQL на доработку.")
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
    bot.send_message(message.chat.id, f"🔄 Запросил исправление SQL у GPT для заявки #{request_id}.")
    Thread(target=run_gpt_sql_generation, args=(request_id, feedback), daemon=True).start()

@bot.message_handler(commands=["start"])
def start(message):
    log_user_action(message.from_user, "command.start")
    user = sql_return.find_user_id(message.from_user.id)
    if user and user[3] == "pending":
        bot.reply_to(message, "Вы уже подали заявку, ожидайте ответа администратора.")
    elif user and user[3] == "approved":
        markup = types.InlineKeyboardMarkup()
        button1 = types.InlineKeyboardButton("✏️ Отправить решение", callback_data=f'mm_send')
        button2 = types.InlineKeyboardButton("🔍 Принять решение", callback_data=f'mm_check_0')
        button3 = types.InlineKeyboardButton("📃 Все курсы", callback_data=f'mm_courses_0')
        button4 = types.InlineKeyboardButton("🗂 Все решения", callback_data=f"mm_answers_0")
        button5 = types.InlineKeyboardButton("🔑 Панель админа", callback_data="admin_panel_open")
        markup.add(button1)
        markup.add(button2)
        markup.add(button3)
        markup.add(button4)
        if message.from_user.id == config["admin_id"]:
            markup.add(button5)
        bot.reply_to(message, f"""Здравствуйте, {message.from_user.first_name}!""", reply_markup=markup)
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
        button1 = types.InlineKeyboardButton("✅ Принять", callback_data=f'reg_approve_{message.from_user.id}')
        button2 = types.InlineKeyboardButton("🟡 Отклонить", callback_data=f'reg_deny_{message.from_user.id}')
        button3 = types.InlineKeyboardButton("❌ Забанить", callback_data=f'reg_ban_{message.from_user.id}')
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
        user = sql_return.find_user_id(call.from_user.id)

        if user and user[3] == "pending":
            bot.edit_message_text("Вы уже подали заявку, ожидайте ответа администратора.", chat_id=call.message.chat.id, message_id=call.message.message_id)
        elif user and user[3] == "approved":
            markup = types.InlineKeyboardMarkup()
            button1 = types.InlineKeyboardButton("✏️ Отправить решение", callback_data=f'mm_send')
            button2 = types.InlineKeyboardButton("🔍 Принять решение", callback_data=f'mm_check_0')
            button3 = types.InlineKeyboardButton("📃 Все курсы", callback_data=f'mm_courses_0')
            button4 = types.InlineKeyboardButton("🗂 Все решения", callback_data=f"mm_answers_0")
            button5 = types.InlineKeyboardButton("🔑 Панель админа", callback_data="admin_panel_open")
            markup.add(button1)
            markup.add(button2)
            markup.add(button3)
            markup.add(button4)
            if call.from_user.id == config["admin_id"]:
                markup.add(button5)
            bot.edit_message_text(f"""Здравствуйте, {call.from_user.first_name}!""", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
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
    elif call.data.startswith("solution"):
        solution(call, int(call.data.split("_")[-1]))
    elif call.data.startswith("self_reject"):
        self_reject(call, int(call.data.split("_")[-1]))
    elif call.data.startswith("undo_self_reject"):
        self_reject(call, int(call.data.split("_")[-1]), True)
    elif call.data.startswith("admin_panel_open"):
        admin_panel(call)
    elif call.data.startswith("admin_panel_backup"):
        admin_backup(call)
    elif call.data.startswith("admin_panel_stop"):
        stop(call)
    elif call.data.startswith("admin_panel_ban"):
        ban(call)
    elif call.data.startswith("admin_panel_unban"):
        unban(call)
    elif call.data.startswith("admin_panel_conf_stop"):
        stop_confirm(call)
    elif call.data.startswith("gptsql_accept_"):
        gpt_sql_accept(call, int(call.data.split("_")[-1]))
    elif call.data.startswith("gptsql_reject_"):
        gpt_sql_reject(call, int(call.data.split("_")[-1]))
    elif call.data.startswith("gptsql_retry_"):
        gpt_sql_retry(call, int(call.data.split("_")[-1]))
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

new_student_answer_dict = dict([])

def mm_send_final(call, lesson_id, course_id, task_id):
    task = sql_return.task_info(task_id)
    
    if task:
        task_id, lesson_id, task_title, task_status, task_deadline, task_description = task

        status_translation = {
            'open': 'Открыт',
            'arc': 'Архивирован',
            'dev': 'В разработке'
        }
        task_status = status_translation.get(task_status, 'Неизвестен')

        # if task_deadline:
        #     deadline_date = datetime.datetime.strptime(task_deadline, '%Y-%m-%d %H:%M')
        #     current_date = datetime.datetime.now()
        #     days_left = (deadline_date - current_date).total_seconds() / (60 * 60 * 24)
        #     if task_status == 'Архивирован' or deadline_date < current_date:
        #         deadline_str = deadline_date.strftime('%d-%m-%Y %H:%M')
        #         deadline_info = f"🗓 <b>Дедлайн</b>: {deadline_str}"
        #     elif days_left < 2:
        #         deadline_str = deadline_date.strftime('%d-%m-%Y %H:%M')
        #         deadline_info = f"🔥 <b>Дедлайн через</b>: {time_left_str} ({deadline_str})"
        #     else:
        #         time_left = relativedelta(deadline_date, current_date)
        #         time_left_str = f"{time_left.days} дней, {time_left.hours} часов, {time_left.minutes} минут"
        #         deadline_str = deadline_date.strftime('%d-%m-%Y %H:%M')
        #         deadline_info = f"⏰ <b>Дедлайн через</b>: {time_left_str} ({deadline_str})"
        # else:
        deadline_info = "⏰ <b>Дедлайн</b>: Не указан"

        task_info_message = (f"Вы начали сдачу решения для задачи, приведённой ниже. Если вы хотите отменить это действие, напишите вместо текста решения \"/stop\" или \"/start\".\n\nПрикрепить к решению можно максимум 1 файл (документ / изображение). Подробнее - /why_only_one_file\n\n"
                             f"📌 <b>Название задачи</b>: {task_title}\n"
                             f"🔖 <b>Статус</b>: {task_status}\n"
                             f"{deadline_info}\n"
                             f"📝 <b>Текст задачи</b>: {task_description if task_description else 'Нет текста задачи'}")

        bot.edit_message_text(task_info_message, 
                              chat_id=call.message.chat.id, 
                              message_id=call.message.message_id, 
                              parse_mode="HTML")

        bot.register_next_step_handler(call.message, mm_send_final_2, lesson_id, course_id, task_id, call.from_user.id)
        # new_student_answer_dict[call.message.from_user.id] == [lesson_id, course_id, task_id]
    else:
        bot.edit_message_text("❗️ Задача не найдена", 
                              chat_id=call.message.chat.id, 
                              message_id=call.message.message_id)

last_time_student_answer_dict = {}

def mm_send_final_2(message, lesson_id, course_id, task_id, user_id):
    log_user_action(
        message.from_user,
        "solution.submit_input",
        f"task_id={task_id}, lesson_id={lesson_id}, course_id={course_id}, content_type={message.content_type}"
    )
    if user_id not in last_time_student_answer_dict:
        last_time_student_answer_dict[user_id] = time.time()
    else:
        if time.time() - last_time_student_answer_dict[user_id] < 10:
            return
        last_time_student_answer_dict[user_id] = time.time()
    if message.content_type == 'text':
        answer_text = message.text
        if "/why_only_one_file" in answer_text:
            why_only_one_file(message)
            return
        if answer_text in ["/stop", "Stop", "stop"]:
            bot.send_message(message.chat.id, "Отменено")
            return
        if answer_text == "/start":
            start(message)
            return
        sql_return.new_student_answer(task_id, user_id, answer_text)
        markup = types.InlineKeyboardMarkup()
        button1 = types.InlineKeyboardButton("🏠 Главное меню", callback_data=f'mm_main_menu')
        markup.add(button1)
        bot.send_message(message.chat.id, "Решение отправлено на проверку", reply_markup=markup)
        for i in sql_return.developers_list(course_id).split():
            bot.send_message(i, f"Поступило новое решение для проверки от {sql_return.get_user_name(user_id)[0]} {sql_return.get_user_name(user_id)[1]}")
        sql_return.log_action(user_id, "send_final", f"{task_id}")
    elif message.content_type == 'document' or message.content_type == 'photo':
        answer_text = message.caption
        if answer_text == "Stop":
            bot.send_message(message.chat.id, "Отменено")
            return
        if not os.path.exists('files'):
            os.makedirs('files')
        try:
            file_id = message.document.file_id if message.content_type == 'document' else message.photo[-1].file_id
            file_info = bot.get_file(file_id)
            
            if file_info.file_size > 15 * 1024 * 1024:
                bot.reply_to(message, "Файл слишком большой. Максимальный размер - 15 МБ.")
                return
            
            downloaded_file = bot.download_file(file_info.file_path)
            
            file_extension = os.path.splitext(file_info.file_path)[1]
            
            new_file_name = f'{sql_return.next_name("files")}{file_extension}'
            save_path = f'files/{new_file_name}'
            
            with open(save_path, 'wb') as new_file:
                new_file.write(downloaded_file)
            sql_return.save_file(message.content_type, new_file_name, save_path, message.from_user.id)

            bot.reply_to(message, f"Файл сохранен как {new_file_name} (текст сообщения: {message.caption})")

            sql_return.new_student_answer(task_id, user_id, answer_text, new_file_name)
            markup = types.InlineKeyboardMarkup()
            button1 = types.InlineKeyboardButton("🏠 Главное меню", callback_data=f'mm_main_menu')
            markup.add(button1)
            bot.send_message(message.chat.id, "Решение отправлено на проверку", reply_markup=markup)
            for i in sql_return.developers_list(course_id).split():
                bot.send_message(i, f"Поступило новое решение для проверки от {sql_return.get_user_name(user_id)[0]} {sql_return.get_user_name(user_id)[1]}")
            sql_return.log_action(user_id, "send_final", f"{task_id}")
        except telebot.apihelper.ApiTelegramException as e:
            if "file is too big" in str(e):
                bot.reply_to(message, "Файл слишком большой для загрузки через Telegram API.")
            else:
                bot.reply_to(message, "Произошла ошибка при обработке файла.")
    else:
        bot.send_message(message.chat.id, "Некорректный тип сообщения")

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
    solutions = sql_return.get_accessible_solutions(user_id=call.from_user.id)
    solutions = list(reversed(solutions))

    courses_per_page = 8
    total_pages = (len(solutions) + courses_per_page - 1) // courses_per_page
    page_courses = solutions[page * courses_per_page:(page + 1) * courses_per_page]

    markup = types.InlineKeyboardMarkup()

    for solution in page_courses:
        if solution[2] != call.from_user.id:
            if solution[6] == "accept":
                markup.add(types.InlineKeyboardButton(f"👨‍🏫✅ {solution[0]}", callback_data=f'solution_{solution[0]}'))
            elif solution[6] == "reject":
                markup.add(types.InlineKeyboardButton(f"👨‍🏫❌ {solution[0]}", callback_data=f'solution_{solution[0]}'))
            elif solution[6] == "self_reject":
                markup.add(types.InlineKeyboardButton(f"👨‍🏫💔 {solution[0]}", callback_data=f'solution_{solution[0]}'))
            else:
                markup.add(types.InlineKeyboardButton(f"👨‍🏫⌛️ {solution[0]}", callback_data=f'solution_{solution[0]}'))
        elif solution[2] == call.from_user.id:
            if solution[6] == "accept":
                markup.add(types.InlineKeyboardButton(f"👨‍🎓✅ {solution[0]}", callback_data=f'solution_{solution[0]}'))
            elif solution[6] == "reject":
                markup.add(types.InlineKeyboardButton(f"👨‍🎓❌ {solution[0]}", callback_data=f'solution_{solution[0]}'))
            elif solution[6] == "self_reject":
                markup.add(types.InlineKeyboardButton(f"👨‍🎓💔 {solution[0]}", callback_data=f'solution_{solution[0]}'))
            else:
                markup.add(types.InlineKeyboardButton(f"👨‍🎓⌛️ {solution[0]}", callback_data=f'solution_{solution[0]}'))
        else:
            markup.add(types.InlineKeyboardButton(f"{solution[1]} {solution[0]}", callback_data=f'solution_{solution[0]}'))

    navigation = []
    if page > 0:
        navigation.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f'mm_answers_{page - 1}'))
    if page < total_pages - 1:
        navigation.append(types.InlineKeyboardButton("➡️ Вперед", callback_data=f'mm_answers_{page + 1}'))

    markup.row(*navigation)
    markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="mm_main_menu"))
    bot.delete_message(call.message.chat.id, call.message.message_id)
    
    bot.send_message(call.message.chat.id, f"Выберите решение для просмотра\nСтраница {page + 1} из {total_pages}:", reply_markup=markup)

def solution(call, sol_id):
    sol = sql_return.get_student_answer_from_id(sol_id)
    print(sol)
    verdicts = {"accept": "✅ Принято", "reject": "❌ Отклонено", "self_reject": "💔 Отменено создателем", None: "⌛️ Ожидает проверки"}
    markup = types.InlineKeyboardMarkup()
    if sol[2] == call.from_user.id and sol[6] == None:
        markup.add(types.InlineKeyboardButton("💔 Отменить", callback_data=f"self_reject_{sol[0]}"))
    if sol[2] == call.from_user.id and sol[6] == "self_reject":
        markup.add(types.InlineKeyboardButton("❤️‍🩹 Восстановить", callback_data=f"undo_self_reject_{sol[0]}"))
    markup.add(types.InlineKeyboardButton("🗂 Все решения", callback_data="mm_answers_0"))
    student_name = sql_return.get_user_name(sol[2])
    text = f"""Решение:
Вердикт: {verdicts[sol[6]]}
Отправил {student_name[0]} {student_name[1]}
Время отправки: {sol[5]}

(тут есть не вся информация, так как функция тестируется)

Текст решения:
{sol[3]}
"""
    bot.delete_message(call.message.chat.id, call.message.message_id)
    
    bot.send_message(call.message.chat.id, text, reply_markup=markup)

def self_reject(call, sol_id, undo=False):
    if undo:
        sql_return.undo_self_reject(sol_id)
    else:
        sql_return.self_reject(sol_id)
    solution(call, sol_id)

def check_all(call):
    task_data = sql_return.last_student_answer_all(call.from_user.id)
    check_task(type=f"check-course-all_", call=call, task_data=task_data)

def check_course(call, course_id):
    task_data = sql_return.last_student_answer_course(course_id)
    check_task(type=f"check-course_{course_id}", call=call, task_data=task_data)

comment_for_answer_dict = dict([])

def check_task(type: str, call, task_data, comment: str = "None"):
    markup = types.InlineKeyboardMarkup()
    if task_data is None:
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="mm_check_0"))
        bot.edit_message_text(
            "У вас нет непроверенных решений в этом разделе",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=markup
        )
        return

    # Create common buttons
    v = [
        types.InlineKeyboardButton("✅ Принять", callback_data=f"check-final_accept_{task_data['answer_id'] if isinstance(task_data, dict) else task_data[0]}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"check-final_reject_{task_data['answer_id'] if isinstance(task_data, dict) else task_data[0]}")
    ]
    markup.row(*v)

    if isinstance(task_data, dict):
        # Handle dictionary case
        markup.add(types.InlineKeyboardButton("✍️ Добавить комментарий", 
                  callback_data=f"check-add-comment_{type}_{task_data['answer_id']}"))
        
        task_data_2 = sql_return.get_task_from_id(task_data["task_id"])
        lesson_data = sql_return.get_lesson_from_id(task_data_2[1])
        files_id = task_data["files_id"]
        answer_text = task_data['answer_text']
        student_name = sql_return.get_user_name(task_data['student_id'])
    else:
        markup.add(types.InlineKeyboardButton("✍️ Добавить комментарий", 
                  callback_data=f"check-add-comment_{type}_{task_data[0]}"))
        task_data_2 = sql_return.get_task_from_id(task_data[1])
        lesson_data = sql_return.get_lesson_from_id(task_data_2[1])
        files_id = task_data[4] if len(task_data) > 4 else None  # Assuming files_id is at index 4
        answer_text = task_data[3]
        student_name = sql_return.get_user_name(task_data[2])
    try:
        # Construct message text
        text = f"""<b>Решение</b>:
    <b>Отправил</b> {student_name[0]} {student_name[1]}
    <b>Урок</b>: {lesson_data[2]}
    <b>Задача</b>: {task_data_2[2]}
    <b>Решение</b>:
    {answer_text}
    <b>Комментарий к вердикту</b>: {comment}"""
        if files_id is None:
            bot.edit_message_text(
                text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=markup,
                parse_mode="HTML"
            )
        else:
            # Delete old message
            bot.delete_message(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )
            
            # Send message with file
            file_id = files_id.split()[0]
            file_info = sql_return.get_file(file_id.split(".")[0])
            file_type = file_info[2]
            file_name = file_info[3]
            file_path = file_info[4]
            
            if file_type == 'photo':
                with open(file_path, 'rb') as photo:
                    bot.send_photo(
                        call.message.chat.id,
                        photo,
                        caption=text,
                        reply_markup=markup,
                        parse_mode="HTML"
                    )
            else:
                with open(file_path, 'rb') as doc:
                    bot.send_document(
                        call.message.chat.id,
                        doc,
                        visible_file_name=file_name,
                        caption=text,
                        reply_markup=markup,
                        parse_mode="HTML"
                    )
    except:
        # Construct message text
        text = f"""Решение:
    Отправил {student_name[0]} {student_name[1]}
    Урок>: {lesson_data[2]}
    Задача>: {task_data_2[2]}
    Решение:
    {answer_text}
    Комментарий к вердикту: {comment}"""
        if files_id is None:
            bot.edit_message_text(
                text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=markup
            )
        else:
            # Delete old message
            bot.delete_message(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )
            
            # Send message with file
            file_id = files_id.split()[0]
            file_info = sql_return.get_file(file_id.split(".")[0])
            file_type = file_info[2]
            file_name = file_info[3]
            file_path = file_info[4]
            
            if file_type == 'photo':
                with open(file_path, 'rb') as photo:
                    bot.send_photo(
                        call.message.chat.id,
                        photo,
                        caption=text,
                        reply_markup=markup
                    )
            else:
                with open(file_path, 'rb') as doc:
                    bot.send_document(
                        call.message.chat.id,
                        doc,
                        visible_file_name=file_name,
                        caption=text,
                        reply_markup=markup
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
    check_task(type, call, task_data, comment)

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
        verdict_message = "✅ Вердикт: верно"
    else:
        verdict_message = "❌ Вердикт: неверно"

    comment2 = ""
    if comment:
        comment2 = f"\n📜 Комментарий: {comment}"
    bot.send_message(sa_data[2], f"""🥳 Ваше решение проверено!

Курс: {sql_return.get_course_name(sql_return.get_course_from_answer_id(answer_id))}
Урок: {sql_return.get_lesson_name(sql_return.get_lesson_from_answer_id(answer_id))}
Задача: {sql_return.get_task_name(sql_return.get_task_from_answer_id(answer_id))}
📝 Текст решения:\n{sa_data[3]}
{verdict_message}{comment2}""")

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
        markup.add(types.InlineKeyboardButton("🤖 Добавить урок (GPT)", callback_data=f"gpt_add_lesson_{course_id}"))
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
            markup.add(types.InlineKeyboardButton("🤖 Добавить урок (GPT)", callback_data=f'gpt_add_lesson_{course_id}'))
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
        markup.add(types.InlineKeyboardButton(f"{lesson[2]}", callback_data=f'lesson_{course_id}_{lesson[0]}_0'))

    navigation = []
    if page > 0:
        navigation.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f'content_{course_id}_{page - 1}'))
    if page < total_pages - 1:
        navigation.append(types.InlineKeyboardButton("➡️ Вперед", callback_data=f'content_{course_id}_{page + 1}'))

    markup.row(*navigation)

    if (is_admin or is_dev) and page == 0:
        markup.add(types.InlineKeyboardButton("➕ Создать урок", callback_data=f'create_lesson_{course_id}'))
    if can_use_gpt and page == 0:
        markup.add(types.InlineKeyboardButton("🤖 Добавить урок (GPT)", callback_data=f'gpt_add_lesson_{course_id}'))

    markup.add(types.InlineKeyboardButton("🔙 К курсу", callback_data=f"course_{course_id}"))

    bot.edit_message_text(f"{description}\nСтраница {page + 1} из {total_pages}:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

def lesson_content(call, course_id, lesson_id, page=0):
    user = sql_return.find_user_id(call.from_user.id)

    if not user:
        bot.send_message(call.message.chat.id, "Вы не зарегистрированы.")
        return

    is_admin = str(call.from_user.id) == str(config["admin_id"])

    tasks = sql_return.tasks_in_lesson(lesson_id)  

    courses_per_page = 8
    total_pages = (len(tasks) + courses_per_page - 1) // courses_per_page
    page_courses = tasks[page * courses_per_page:(page + 1) * courses_per_page]

    description = "Содержание урока:\n"

    markup = types.InlineKeyboardMarkup()
    for lesson in page_courses:
        verdict = sql_return.task_status_by_user(call.from_user.id, lesson[0])
        markup.add(types.InlineKeyboardButton(f"{verdict} {lesson[2]}", callback_data=f'task_{lesson[0]}_{lesson_id}_{course_id}'))

    navigation = []
    if page > 0:
        navigation.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f'lesson_{course_id}_{lesson_id}_{page - 1}'))
    if page < total_pages - 1:
        navigation.append(types.InlineKeyboardButton("➡️ Вперед", callback_data=f'lesson_{course_id}_{lesson_id}_{page + 1}'))

    if (is_admin or sql_return.is_course_dev(call.from_user.id, sql_return.developers_list(course_id))) and page == 0:
        markup.add(types.InlineKeyboardButton("➕ Создать задачу", callback_data=f'create_task_{lesson_id}_{course_id}'))

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
        bot.edit_message_text("❌ Создание курса отменено", chat_id=message.chat.id, message_id=editing_message_id, reply_markup=markup)
        return
    
    if message.text.lower() == "none":
        sql_return.create_course(course_name, message.from_user.id, str(message.from_user.id))
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="mm_main_menu"))
        bot.edit_message_text(f"""✅ Курс "{course_name}" успешно создан!""", chat_id=message.chat.id, message_id=editing_message_id, reply_markup=markup)
        return
        
    try:
        developers = [int(dev_id) for dev_id in developers]
    except ValueError:
        bot.edit_message_text("""🎓 Вы создаёте курс.
                          
📋 Информация о курсе: 
👨‍🏫 Создатель курса: {sql_return.get_user_name(message.from_user.id)[0]} {sql_return.get_user_name(message.from_user.id)[1]} ({message.from_user.id})
📚 Название курса: {course_name}
👥 Разработчики: -

❌ Ошибка: ID разработчиков должны быть числами. Пожалуйста, введите ID через пробел (например: 123456789 987654321)""", chat_id=message.chat.id, message_id=editing_message_id)
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
    bot.edit_message_text(f"""✅ Курс "{course_name}" успешно создан!""", chat_id=message.chat.id, message_id=editing_message_id, reply_markup=markup)

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
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 К списку уроков", callback_data=f"content_{course_id}_0"))
    bot.edit_message_text(f"""✅ Урок "{name}" успешно создан!""", chat_id=message.chat.id, message_id=editing_message_id, reply_markup=markup)

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
    bot.edit_message_text(f"""✅ Задача "{task_name}" успешно создана!""", chat_id=message.chat.id, message_id=editing_message_id, reply_markup=markup)

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
    text = """Вы можете прикрепить к решению не более одного файла (документ или изображение).

Это ограничение связано с тем, что:

1. Если к сообщению прикреплено более одного файла, Telegram автоматически разделяет его на текст и файлы.

2. Бот обрабатывает каждый файл как отдельное сообщение, что приводит к ошибкам.

Для устранения этой проблемы потребуется полностью переписать функцию сдачи решений. Мы можем рассмотреть это в будущем, так как сейчас данная проблема не является критичной.

Если вы отправите больше одного файла, бот обработает только первый и откажется принимать решение. Для предотвращения повторной отправки ненужных файлов реализована функция, которая удаляет все ваши сообщения, отправленные менее чем через 10 секунд после предыдущего. Если вы отправляете небольшое количество файлов, это не должно вызвать сложностей.

Если по важной причине вам необходимо прикрепить больше одного файла, обратитесь в техподдержку (aka @agusev2311).

⚠️ Обратите внимание: каждый запрос в техподдержку требует моего времени. Если проблема связана с базой данных (как в данном случае), потребуется остановка работы бота. Если вы будете обращаться в техподдержку без веской причины, например, просто для прикрепления дополнительных файлов к решению, к вам могут быть применены ограничения. Пожалуйста, будьте внимательны, уважайте других пользователей и меня.
"""
    bot.send_message(message.chat.id, text)

def ban(call):
    if call.from_user.id != config["admin_id"]:
        return
    bot.send_message(call.chat.id, "Введите id пользователей")
    bot.register_next_step_handler(call, ban_enter)

def ban_enter(call):
    log_user_action(
        call.from_user,
        "admin.ban_input",
        f"target_ids={call.message.text or ''}"
    )
    for user in call.message.text.split():
        sql_return.set_user_status(user, "banned")
    sql_return.log_action(call.from_user.id, "ban", f"{call.message.text.split()}")
    bot.send_message(call.message.chat.id, "Пользователи забанены")

def unban(call):
    if call.from_user.id != config["admin_id"]:
        return
    bot.send_message(call.chat.id, "Введите id пользователей")
    bot.register_next_step_handler(call, unban_enter)

def unban_enter(call):
    log_user_action(
        call.from_user,
        "admin.unban_input",
        f"target_ids={call.message.text or ''}"
    )
    for user in call.message.text.split():
        sql_return.set_user_status(user, "approved")
    sql_return.log_action(call.from_user.id, "unban", f"{call.message.text.split()}")
    bot.send_message(call.message.chat.id, "Пользователи разбанены")

def stop_confirm(call):
    markup = types.InlineKeyboardMarkup()
    wtf_markup = types.InlineKeyboardMarkup()

    markup.row(types.InlineKeyboardButton("🔒 Заблокировать", callback_data=f'admin_panel_ban'), types.InlineKeyboardButton("🔓 Разблокировать", callback_data=f'admin_panel_unban'))
    # markup.add(types.InlineKeyboardButton("🛑 Остановить бота", callback_data="admin_panel_stop"))
    markup.row(types.InlineKeyboardButton("🛑 Я уверен", callback_data=f'admin_panel_stop'), types.InlineKeyboardButton("🫢 Отменить", callback_data=f'admin_panel_open'))
    markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="mm_main_menu"))
    wtf_markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="mm_main_menu"))

    if call.from_user.id == config["admin_id"]:
        bot.edit_message_text(f"""Здравствуйте, админ (омг я же сам админ, точно)""", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
    else:
        bot.edit_message_text(f"""Подожди, подожди, подожди. Как ты это сделал?!?!?!""", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=wtf_markup)
        bot.send_message(config["admin_id"], f"❗️❗️СРОЧНО❗️❗️\n\nПользователь {call.from_user.id} ({sql_return.get_user_name(call.from_user.id)}) попытался попасть в панель админа")

def stop(call):
    global is_polling
   
    if call.from_user.id == config["admin_id"]:
        bot.send_message(call.message.chat.id, "Подождите...")
        broadcast("❌ Бот временно закрыт на технические работы.")
        is_polling = False
        bot.send_message(call.message.chat.id, "Бот успешно отправил все сообщения.")
        bot.stop_polling()

def broadcast(message: str):
    for i in sql_return.all_users():
        try:
            bot.send_message(i[0], message)
        except:
            pass

def admin_panel(call):
    markup = types.InlineKeyboardMarkup()
    wtf_markup = types.InlineKeyboardMarkup()

    # markup.row(types.InlineKeyboardButton("🔒 Заблокировать", callback_data=f'admin_panel_ban'), types.InlineKeyboardButton("🔓 Разблокировать", callback_data=f'admin_panel_unban'))
    markup.add(types.InlineKeyboardButton("📦 Отправить бэкап", callback_data="admin_panel_backup"))
    markup.add(types.InlineKeyboardButton("🛑 Остановить бота", callback_data="admin_panel_conf_stop"))
    markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="mm_main_menu"))
    wtf_markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="mm_main_menu"))

    if call.from_user.id == config["admin_id"]:
        bot.edit_message_text(f"""Несданные задачи по матпраку: {sql_return.count_unchecked_solutions(6)}""", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
    else:
        bot.edit_message_text(f"""Подожди, подожди, подожди. Как ты это сделал?!?!?!""", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=wtf_markup)
        bot.send_message(config["admin_id"], f"❗️❗️СРОЧНО❗️❗️\n\nПользователь {call.from_user.id} ({sql_return.get_user_name(call.from_user.id)}) попытался попасть в панель админа")

def admin_backup(call):
    if call.from_user.id != config["admin_id"]:
        return
    bot.send_message(call.message.chat.id, "Запускаю бэкап, сейчас пришлю архивы.")
    Thread(target=backup_databases_and_files_split, daemon=True).start()

broadcast("✅ Бот снова работает!")

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
        with open("polling_errors.log", "a", encoding="utf-8") as f:
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
            "ошибок нет ✅"
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
        bot.send_message(config["admin_id"], summary)
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
        bot.send_document(admin_id, f, caption=caption)

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
    """
    created = []
    try:
        log("backup: START")

        # 1) БД
        db_zip = backup_make_db_zip()
        created.append(db_zip)
        send_file_to_admin(db_zip, caption="Backup DB ✅")
        log("backup: DB SENT")

        # 2) files/ (try single zip, else split)
        files_zip, added_files, size = backup_make_files_zip_single(MAX_PART_BYTES)
        if files_zip:
            created.append(files_zip)
            caption = f"Backup files ✅\nSize: {size} bytes"
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
                    caption = f"Backup files ✅ ({i}/{total_parts})\nSize: {size} bytes"
                    send_file_to_admin(part, caption=caption)
                    log(f"backup: SENT {part} ({i}/{total_parts})")
            else:
                log("backup: no files parts to send")

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
