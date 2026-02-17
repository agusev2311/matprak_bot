import base64
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path

import openai

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
PDF_EXTENSION = ".pdf"
MAX_SQL_RETRY_FOR_MISSING = 2
MISSING_TASK_FALLBACK_TEXT = "Текст задачи не распознан полностью. Проверьте и исправьте вручную."
DEFAULT_OPENAI_MODEL = "gpt-4.1"


def load_config():
    with open("config.json", "r", encoding="utf-8") as file:
        return json.load(file)


def _pick_model(config: dict, specific_key: str) -> str:
    model = config.get(specific_key) or config.get("openai-model") or DEFAULT_OPENAI_MODEL
    model = str(model).strip()
    if not model:
        return DEFAULT_OPENAI_MODEL
    return model


def _zip_db(db_path: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as temp_file:
        zip_path = temp_file.name

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.write(db_path, arcname=os.path.basename(db_path))

    return zip_path


def _load_image_data_url(image_path: str) -> str:
    with open(image_path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("ascii")

    ext = Path(image_path).suffix.lower()
    if ext in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif ext == ".png":
        mime = "image/png"
    elif ext == ".webp":
        mime = "image/webp"
    else:
        raise ValueError(f"Неподдерживаемый формат изображения: {ext}")

    return f"data:{mime};base64,{encoded}"


def _strip_markdown_fences(output_text: str) -> str:
    text = (output_text or "").strip()
    if not text.startswith("```"):
        return text

    chunks = text.split("```")
    for chunk in chunks:
        candidate = chunk.strip()
        if not candidate:
            continue

        if "\n" in candidate:
            lines = candidate.splitlines()
            first_line = lines[0].strip().lower()
            if first_line in {"sql", "json", "text", "txt"}:
                candidate = "\n".join(lines[1:]).strip()

        return candidate.strip()

    return text


def _normalize_task_label(label: str) -> str:
    cleaned = re.sub(r"\s+", "", (label or "").strip())
    if cleaned.endswith(".") or cleaned.endswith(")"):
        cleaned = cleaned[:-1]

    match = re.fullmatch(r"(\d+)(\*)?", cleaned)
    if not match:
        return ""

    number = match.group(1)
    suffix = "*" if match.group(2) else ""
    return f"{number}{suffix}"


def _deduplicate_labels(labels: list[str]) -> list[str]:
    result = []
    seen = set()

    for label in labels:
        normalized = _normalize_task_label(label)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)

    return result


def _split_sql_statements(sql_text: str) -> list[str]:
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


def _split_sql_csv(items_text: str) -> list[str]:
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


def _parse_sql_literal(value: str) -> str:
    value = (value or "").strip()

    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("''", "'").strip()

    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1].replace('""', '"').strip()

    return value


def _extract_task_labels_from_sql(sql_text: str) -> list[str]:
    labels = []

    for statement in _split_sql_statements(sql_text):
        match = re.match(
            r"^\s*INSERT\s+INTO\s+tasks\s*\((.*?)\)\s*VALUES\s*\((.*)\)\s*$",
            statement,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            continue

        columns = [col.strip().strip('`"[]').lower() for col in _split_sql_csv(match.group(1))]
        values = _split_sql_csv(match.group(2))

        if len(columns) != len(values):
            continue

        row = dict(zip(columns, values))
        raw_label = None
        for column in ("title", "number", "task_number", "name"):
            if column in row:
                raw_label = _parse_sql_literal(row[column])
                break

        if raw_label:
            normalized = _normalize_task_label(raw_label)
            if normalized:
                labels.append(normalized)

    return _deduplicate_labels(labels)


def _escape_sql_string(text: str) -> str:
    return (text or "").replace("'", "''")


def _append_missing_tasks_to_sql(sql_text: str, missing_tasks: dict[str, str]) -> str:
    chunks = [sql_text.strip()]

    for label, task_text in missing_tasks.items():
        safe_label = _escape_sql_string(label)
        safe_text = _escape_sql_string(task_text.strip())
        chunks.append(
            "INSERT INTO tasks (lesson_id, title, status, description) VALUES "
            f"((SELECT MAX(id) FROM lessons), '{safe_label}', 'open', '{safe_text}');"
        )

    return "\n\n".join(chunk for chunk in chunks if chunk)


def _parse_task_labels_from_text(text: str) -> list[str]:
    cleaned = _strip_markdown_fences(text)
    labels = re.findall(r"(?<!\d)(\d+\s*\*?)(?!\d)", cleaned)
    return _deduplicate_labels(labels)


def _build_initial_prompt(course_id: int, required_labels: list[str] | None = None) -> str:
    required_labels = required_labels or []
    required_block = ""

    if required_labels:
        required_block = (
            "\nОбязательный список номеров задач (нельзя пропускать):\n"
            + "\n".join(required_labels)
            + "\n"
        )

    return f"""
Сгенерируй SQL-запросы для SQLite базы учебного бота.

Контекст:
- Нужно добавить новый урок и задачи в course_id = {course_id}.
- Используй только таблицы lessons и tasks.
{required_block}

Схема таблиц (важно соблюдать точные названия колонок):
lessons:
- id INTEGER PRIMARY KEY AUTOINCREMENT
- course_id INTEGER NOT NULL
- title TEXT NOT NULL
- status TEXT NOT NULL
- open_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP

tasks:
- id INTEGER PRIMARY KEY AUTOINCREMENT
- lesson_id INTEGER NOT NULL
- title TEXT NOT NULL
- status TEXT NOT NULL
- deadline TIMESTAMP
- description TEXT

Правила:
1) Используй только SQL.
2) Сначала создай ОДИН новый урок в таблице lessons.
3) Затем создай задачи в таблице tasks, связанные с этим уроком.
4) Для lessons.status и tasks.status ставь 'open'.
5) Вставляй только те задачи, у которых номер начинается с числа
   (например: 1, 2, 3, 7*). Буквенные пункты и подпункты без числового номера игнорируй.
6) Используй корректный id урока:
   - либо через подзапрос с MAX(id),
   - либо через явный id, который соответствует следующему доступному id.
7) Для каждой задачи:
   - title: короткий номер задачи (например, '1', '2', '3*')
   - description: полный текст задачи
8) ОБЯЗАТЕЛЬНО проверь перед ответом, что ни один номер задачи не пропущен.
9) НЕ используй колонки text, number, name и любые другие, которых нет в схеме выше.
10) Не используй DELETE, DROP, ALTER, UPDATE.
11) Не добавляй комментарии и пояснения.

Ответ верни ТОЛЬКО SQL-запросами, без markdown.
""".strip()


def _build_retry_prompt(
    course_id: int,
    previous_sql: str,
    admin_feedback: str,
    required_labels: list[str] | None = None,
) -> str:
    required_labels = required_labels or []
    required_block = ""

    if required_labels:
        required_block = (
            "\nОбязательный список номеров задач (нельзя пропускать):\n"
            + "\n".join(required_labels)
            + "\n"
        )

    return f"""
Исправь SQL-запросы для SQLite базы учебного бота.

Контекст:
- course_id = {course_id}
- Нужно создать урок и задачи из прикрепленного листка.
{required_block}

Схема таблиц (строго):
lessons(id, course_id, title, status, open_date)
tasks(id, lesson_id, title, status, deadline, description)

Комментарий администратора с ошибками:
{admin_feedback}

Текущая версия SQL:
{previous_sql}

Требования:
1) Верни исправленный SQL.
2) Используй только SQL, без markdown и пояснений.
3) Не используй DELETE, DROP, ALTER, UPDATE.
4) Сначала INSERT в lessons, затем INSERT в tasks.
5) Для lessons.status и tasks.status ставь 'open'.
6) Добавляй только задачи с числовым номером.
7) Для задач используй только колонки: lesson_id, title, status, description (deadline опционально).
8) НИКОГДА не используй колонки text, number, name.
9) title должен быть номером задачи, description должен быть полным текстом.
10) ОБЯЗАТЕЛЬНО проверь, что ни один номер задачи не пропущен.
""".strip()


def _build_labels_audit_prompt(audit_mode: str) -> str:
    if audit_mode == "bottom_up":
        return """
Проведи ПОВТОРНУЮ ПРОВЕРКУ листка снизу вверх и по краям.
Особенно ищи номера со звездочкой (например 1*, 2*) и пункты,
которые легко пропустить.

Верни только номера задач, по одному номеру в строке.
Формат номера: 1 или 1*.
Никакого дополнительного текста.
""".strip()

    return """
Проанализируй листок с задачами сверху вниз.
Верни ВСЕ номера задач, по одному номеру в строке.
Формат номера: 1 или 1*.
Никакого дополнительного текста.
""".strip()


def _build_missing_tasks_prompt(missing_labels: list[str]) -> str:
    labels_block = "\n".join(missing_labels)
    return f"""
Найди на листке полный текст задач строго для этих номеров:
{labels_block}

Ответ верни только строками формата:
<номер>|||<полный текст задачи>

Одна задача — одна строка.
Если текст частично нечитабелен, верни максимально полный видимый вариант.
""".strip()


def _parse_missing_tasks_response(text: str) -> dict[str, str]:
    cleaned = _strip_markdown_fences(text)
    result = {}

    for line in cleaned.splitlines():
        if "|||" not in line:
            continue
        label_raw, task_text = line.split("|||", 1)
        label = _normalize_task_label(label_raw)
        task_text = task_text.strip()
        if label and task_text:
            result[label] = task_text

    return result


def _build_lesson_content(client: openai.OpenAI, lesson_file_path: str):
    extension = Path(lesson_file_path).suffix.lower()

    if extension in IMAGE_EXTENSIONS:
        return [{"type": "input_image", "image_url": _load_image_data_url(lesson_file_path)}], None

    if extension == PDF_EXTENSION:
        with open(lesson_file_path, "rb") as lesson_file:
            uploaded_file = client.files.create(file=lesson_file, purpose="user_data")
        return [{"type": "input_file", "file_id": uploaded_file.id}], uploaded_file.id

    raise ValueError("Поддерживаются только фото (jpg/jpeg/png/webp) и PDF.")


def _request_sheet_text(lesson_file_path: str, prompt: str) -> str:
    config = load_config()
    api_key = config["openai-api-key"]
    audit_model = _pick_model(config, "openai-model-audit")

    if not os.path.exists(lesson_file_path):
        raise FileNotFoundError(f"Не найден файл с задачами: {lesson_file_path}")

    client = openai.OpenAI(api_key=api_key)
    uploaded_ids = []

    try:
        lesson_content, lesson_file_id = _build_lesson_content(client, lesson_file_path)
        if lesson_file_id:
            uploaded_ids.append(lesson_file_id)

        response = client.responses.create(
            model=audit_model,
            input=[
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}, *lesson_content],
                }
            ],
        )

        text = _strip_markdown_fences(response.output_text)
        if not text:
            raise RuntimeError("GPT вернул пустой ответ при аудите листка.")
        return text.strip()
    finally:
        for file_id in uploaded_ids:
            try:
                client.files.delete(file_id)
            except Exception:
                pass


def _collect_required_task_labels(lesson_file_path: str) -> list[str]:
    pass1 = _request_sheet_text(lesson_file_path, _build_labels_audit_prompt("top_down"))
    pass2 = _request_sheet_text(lesson_file_path, _build_labels_audit_prompt("bottom_up"))
    labels = _parse_task_labels_from_text(pass1) + _parse_task_labels_from_text(pass2)
    return _deduplicate_labels(labels)


def _extract_missing_tasks_text(lesson_file_path: str, missing_labels: list[str]) -> dict[str, str]:
    if not missing_labels:
        return {}

    response_text = _request_sheet_text(lesson_file_path, _build_missing_tasks_prompt(missing_labels))
    parsed = _parse_missing_tasks_response(response_text)

    result = {}
    for label in missing_labels:
        result[label] = parsed.get(label, MISSING_TASK_FALLBACK_TEXT)

    return result


def _find_missing_labels(required_labels: list[str], sql_text: str) -> list[str]:
    required = _deduplicate_labels(required_labels)
    if not required:
        return []

    in_sql = set(_extract_task_labels_from_sql(sql_text))
    return [label for label in required if label not in in_sql]


def _request_sql(lesson_file_path: str, prompt: str) -> str:
    config = load_config()
    db_path = config.get("db-name", "users.db")
    api_key = config["openai-api-key"]
    sql_model = _pick_model(config, "openai-model-sql")

    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Не найдена база данных: {db_path}")
    if not os.path.exists(lesson_file_path):
        raise FileNotFoundError(f"Не найден файл с задачами: {lesson_file_path}")

    client = openai.OpenAI(api_key=api_key)
    zip_path = _zip_db(db_path)
    uploaded_ids = []

    try:
        with open(zip_path, "rb") as db_archive:
            db_file = client.files.create(file=db_archive, purpose="user_data")
        uploaded_ids.append(db_file.id)

        lesson_content, lesson_file_id = _build_lesson_content(client, lesson_file_path)
        if lesson_file_id:
            uploaded_ids.append(lesson_file_id)

        response = client.responses.create(
            model=sql_model,
            tools=[
                {
                    "type": "code_interpreter",
                    "container": {
                        "type": "auto",
                        "memory_limit": "1g",
                        "file_ids": [db_file.id],
                    },
                }
            ],
            tool_choice="auto",
            instructions=(
                "Анализируй SQLite через code interpreter только по приложенному архиву БД. "
                "Прикрепленный листок (фото или PDF) анализируй самим модельным зрением/чтением, "
                "без попытки читать его через Python."
            ),
            input=[
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}, *lesson_content],
                }
            ],
        )

        sql_text = _strip_markdown_fences(response.output_text)
        if not sql_text:
            raise RuntimeError("GPT вернул пустой ответ.")

        return sql_text.strip()
    finally:
        for file_id in uploaded_ids:
            try:
                client.files.delete(file_id)
            except Exception:
                pass

        try:
            os.remove(zip_path)
        except OSError:
            pass


def _ensure_sql_covers_required_labels(
    lesson_file_path: str,
    course_id: int,
    sql_text: str,
    required_labels: list[str],
    base_feedback: str = "",
) -> str:
    missing_labels = _find_missing_labels(required_labels, sql_text)
    retry_number = 0

    while missing_labels and retry_number < MAX_SQL_RETRY_FOR_MISSING:
        retry_number += 1
        feedback_parts = []
        if base_feedback.strip():
            feedback_parts.append(base_feedback.strip())
        feedback_parts.append(
            "В SQL отсутствуют задачи с номерами: "
            + ", ".join(missing_labels)
            + ". Добавь их обязательно и не удаляй уже существующие задачи."
        )

        sql_text = _request_sql(
            lesson_file_path=lesson_file_path,
            prompt=_build_retry_prompt(
                course_id=course_id,
                previous_sql=sql_text,
                admin_feedback="\n\n".join(feedback_parts),
                required_labels=required_labels,
            ),
        )
        missing_labels = _find_missing_labels(required_labels, sql_text)

    if missing_labels:
        missing_tasks = _extract_missing_tasks_text(lesson_file_path, missing_labels)
        sql_text = _append_missing_tasks_to_sql(sql_text, missing_tasks)

    return sql_text


def generate_lesson_sql(lesson_file_path: str, course_id: int) -> str:
    required_labels = _collect_required_task_labels(lesson_file_path)

    sql_text = _request_sql(
        lesson_file_path=lesson_file_path,
        prompt=_build_initial_prompt(course_id=course_id, required_labels=required_labels),
    )

    return _ensure_sql_covers_required_labels(
        lesson_file_path=lesson_file_path,
        course_id=course_id,
        sql_text=sql_text,
        required_labels=required_labels,
    )


def fix_lesson_sql(lesson_file_path: str, course_id: int, previous_sql: str, admin_feedback: str) -> str:
    required_labels = _collect_required_task_labels(lesson_file_path)

    sql_text = _request_sql(
        lesson_file_path=lesson_file_path,
        prompt=_build_retry_prompt(
            course_id=course_id,
            previous_sql=previous_sql,
            admin_feedback=admin_feedback,
            required_labels=required_labels,
        ),
    )

    return _ensure_sql_covers_required_labels(
        lesson_file_path=lesson_file_path,
        course_id=course_id,
        sql_text=sql_text,
        required_labels=required_labels,
        base_feedback=admin_feedback,
    )


def main() -> None:
    config = load_config()
    lesson_file_path = config.get("image-path", "photo_2026-02-10_12-18-31.jpg")
    course_id = int(config.get("course-id", 1))
    sql_text = generate_lesson_sql(lesson_file_path=lesson_file_path, course_id=course_id)
    print(sql_text)


if __name__ == "__main__":
    main()
