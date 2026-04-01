import base64
import json
import os
import re
from pathlib import Path

import requests

OPENAI_API_BASE = "https://api.openai.com/v1"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
PDF_EXTENSION = ".pdf"
DEFAULT_OPENAI_MODEL = "gpt-4.1"
REQUEST_TIMEOUT_SECONDS = 300

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


def load_config():
    with open("config.json", "r", encoding="utf-8") as file:
        return json.load(file)


def _pick_model(config: dict, specific_key: str) -> str:
    candidates = [
        config.get(specific_key),
        config.get("openai-model-sql"),
        config.get("openai-model-lesson"),
        config.get("openai-model"),
        DEFAULT_OPENAI_MODEL,
    ]
    for candidate in candidates:
        model = str(candidate or "").strip()
        if model:
            return model
    return DEFAULT_OPENAI_MODEL


def _load_image_data_url(image_path: str) -> str:
    with open(image_path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("ascii")

    extension = Path(image_path).suffix.lower()
    if extension in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif extension == ".png":
        mime = "image/png"
    elif extension == ".webp":
        mime = "image/webp"
    else:
        raise ValueError(f"Неподдерживаемый формат изображения: {extension}")

    return f"data:{mime};base64,{encoded}"


def _openai_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
    }


def _extract_response_text(response_json: dict) -> str:
    output_text = str(response_json.get("output_text") or "").strip()
    if output_text:
        return output_text

    parts = []
    for output_item in response_json.get("output", []):
        for content_item in output_item.get("content", []):
            if content_item.get("type") == "output_text":
                text = str(content_item.get("text") or "").strip()
                if text:
                    parts.append(text)

    return "\n".join(parts).strip()


def _upload_user_file(api_key: str, file_path: str) -> str:
    file_name = os.path.basename(file_path)
    with open(file_path, "rb") as source_file:
        response = requests.post(
            f"{OPENAI_API_BASE}/files",
            headers=_openai_headers(api_key),
            data={"purpose": "user_data"},
            files={"file": (file_name, source_file)},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        raise RuntimeError(f"Не удалось загрузить файл в OpenAI: {response.text}") from error

    return response.json()["id"]


def _delete_uploaded_file(api_key: str, file_id: str) -> None:
    try:
        requests.delete(
            f"{OPENAI_API_BASE}/files/{file_id}",
            headers=_openai_headers(api_key),
            timeout=60,
        )
    except Exception:
        pass


def _build_lesson_content(api_key: str, lesson_file_path: str):
    extension = Path(lesson_file_path).suffix.lower()

    if extension in IMAGE_EXTENSIONS:
        return [{"type": "input_image", "image_url": _load_image_data_url(lesson_file_path)}], None

    if extension == PDF_EXTENSION:
        uploaded_file_id = _upload_user_file(api_key, lesson_file_path)
        return [{"type": "input_file", "file_id": uploaded_file_id}], uploaded_file_id

    raise ValueError("Поддерживаются только фото (jpg/jpeg/png/webp) и PDF.")


def _extract_sql_code(text: str) -> str:
    content = str(text or "").strip()
    if not content:
        return ""

    fenced_match = re.search(r"```(?:sql)?\s*(.*?)```", content, flags=re.IGNORECASE | re.DOTALL)
    if fenced_match:
        content = fenced_match.group(1).strip()

    return content.strip()


def _quote_sql_string(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


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


def _split_sql_value_rows(values_text: str) -> list[str]:
    rows = []
    current = []
    depth = 0
    in_single_quote = False
    in_double_quote = False

    text = values_text.strip()
    index = 0
    while index < len(text):
        char = text[index]

        if char == "'" and not in_double_quote:
            if in_single_quote and index + 1 < len(text) and text[index + 1] == "'":
                if depth > 0:
                    current.append(char)
                    current.append(text[index + 1])
                index += 2
                continue
            in_single_quote = not in_single_quote
        elif char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote

        if char == "(" and not in_single_quote and not in_double_quote:
            if depth == 0:
                current = []
            else:
                current.append(char)
            depth += 1
            index += 1
            continue

        if char == ")" and not in_single_quote and not in_double_quote:
            depth -= 1
            if depth < 0:
                raise ValueError("Некорректный VALUES-блок в SQL.")
            if depth == 0:
                rows.append("".join(current).strip())
                current = []
                index += 1
                continue

        if depth > 0:
            current.append(char)

        index += 1

    if depth != 0:
        raise ValueError("Некорректный VALUES-блок в SQL.")

    return [row for row in rows if row]


def _normalize_identifier(identifier: str) -> str:
    return identifier.strip().strip('`"[]').lower()


def _parse_sql_string_literal(value: str, field_name: str, allow_null: bool = False) -> str | None:
    normalized = value.strip()
    if allow_null and normalized.upper() == "NULL":
        return None

    if len(normalized) >= 2 and normalized[0] == "'" and normalized[-1] == "'":
        return normalized[1:-1].replace("''", "'")

    if len(normalized) >= 2 and normalized[0] == '"' and normalized[-1] == '"':
        return normalized[1:-1].replace('""', '"')

    raise ValueError(f"Поле {field_name} должно быть строковым литералом SQL.")


def _parse_sql_text_value(value: str, field_name: str) -> str:
    normalized = value.strip()
    if re.fullmatch(r"-?\d+", normalized):
        return normalized
    parsed = _parse_sql_string_literal(normalized, field_name, allow_null=False)
    if parsed is None:
        raise ValueError(f"Поле {field_name} не может быть NULL.")
    return parsed


def _parse_lesson_insert(statement: str, expected_course_id: int | None) -> dict:
    match = re.match(
        r"^\s*INSERT\s+INTO\s+lessons\s*\((.*?)\)\s*VALUES\s*\((.*)\)\s*$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise ValueError("Некорректный INSERT INTO lessons.")

    columns = _split_sql_csv(match.group(1))
    values = _split_sql_csv(match.group(2))

    if len(columns) != len(values):
        raise ValueError("В INSERT INTO lessons количество колонок и значений не совпадает.")

    mapped_values = {}
    for raw_column, raw_value in zip(columns, values):
        column = _normalize_identifier(raw_column)
        normalized_column = LESSONS_COLUMN_ALIASES.get(column, column)

        if normalized_column not in {"id", "course_id", "title", "status", "open_date", "file_id"}:
            raise ValueError(f"Недопустимая колонка lessons: {raw_column}")

        if normalized_column not in mapped_values:
            mapped_values[normalized_column] = raw_value.strip()

    if expected_course_id is None:
        if "course_id" not in mapped_values:
            raise ValueError("В INSERT INTO lessons отсутствует course_id.")
        try:
            course_id = int(mapped_values["course_id"])
        except ValueError as error:
            raise ValueError("course_id в INSERT INTO lessons должен быть целым числом.") from error
    else:
        course_id = int(expected_course_id)

    lesson_title = _parse_sql_text_value(mapped_values.get("title", "'Новый урок'"), "lessons.title")
    lesson_status = _parse_sql_string_literal(mapped_values.get("status", "'open'"), "lessons.status") or "open"

    return {
        "course_id": course_id,
        "lesson_title": lesson_title,
        "lesson_status": lesson_status,
        "tasks": [],
    }


def _parse_tasks_insert(statement: str, default_title_index: int) -> tuple[list[dict], int]:
    match = re.match(
        r"^\s*INSERT\s+INTO\s+tasks\s*\((.*?)\)\s*VALUES\s*(.*)\s*$",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise ValueError("Некорректный INSERT INTO tasks. Ожидается формат с VALUES.")

    columns = _split_sql_csv(match.group(1))
    row_texts = _split_sql_value_rows(match.group(2))

    if not row_texts:
        raise ValueError("В INSERT INTO tasks нет строк VALUES.")

    tasks = []
    for row_text in row_texts:
        values = _split_sql_csv(row_text)
        if len(columns) != len(values):
            raise ValueError("В INSERT INTO tasks количество колонок и значений не совпадает.")

        mapped_values = {}
        for raw_column, raw_value in zip(columns, values):
            column = _normalize_identifier(raw_column)
            normalized_column = TASKS_COLUMN_ALIASES.get(column, column)

            if normalized_column not in {"id", "lesson_id", "title", "status", "deadline", "description"}:
                raise ValueError(f"Недопустимая колонка tasks: {raw_column}")

            if normalized_column not in mapped_values:
                mapped_values[normalized_column] = raw_value.strip()

        title_value = mapped_values.get("title")
        if title_value is None:
            title = f"Задача {default_title_index}"
            default_title_index += 1
        else:
            title = _parse_sql_text_value(title_value, "tasks.title")

        status = _parse_sql_string_literal(mapped_values.get("status", "'open'"), "tasks.status") or "open"
        description = _parse_sql_string_literal(
            mapped_values.get("description", "NULL"),
            "tasks.description",
            allow_null=True,
        )
        if description is None or not str(description).strip():
            raise ValueError(f"У задачи {title} отсутствует description.")

        tasks.append({
            "title": title,
            "status": status,
            "description": description,
        })

    return tasks, default_title_index


def _build_normalized_sql(payload: dict) -> str:
    lesson_statement = (
        "INSERT INTO lessons (course_id, title, status) VALUES "
        f"({int(payload['course_id'])}, {_quote_sql_string(payload['lesson_title'])}, {_quote_sql_string(payload['lesson_status'])});"
    )

    task_lines = []
    for index, task in enumerate(payload["tasks"]):
        select_prefix = "SELECT" if index == 0 else "UNION ALL\nSELECT"
        task_lines.append(
            f"{select_prefix} last_insert_rowid(), "
            f"{_quote_sql_string(task['title'])}, "
            f"{_quote_sql_string(task.get('status') or 'open')}, "
            f"{_quote_sql_string(task.get('description') or '')}"
        )

    tasks_statement = "INSERT INTO tasks (lesson_id, title, status, description)\n" + "\n".join(task_lines) + ";"
    return lesson_statement + "\n\n" + tasks_statement


def normalize_lesson_sql(sql_text: str, expected_course_id: int | None = None) -> tuple[str, dict]:
    extracted_sql = _extract_sql_code(sql_text)
    if not extracted_sql:
        raise ValueError("Пустой SQL.")

    statements = _split_sql_statements(extracted_sql)
    if not statements:
        raise ValueError("SQL не содержит команд.")

    lesson_payload = None
    task_payloads = []
    default_title_index = 1

    for statement in statements:
        compact = statement.strip()
        if not compact:
            continue

        if re.match(r"^\s*INSERT\s+INTO\s+lessons\b", compact, flags=re.IGNORECASE):
            if lesson_payload is not None:
                raise ValueError("В SQL должно быть только одно INSERT INTO lessons.")
            lesson_payload = _parse_lesson_insert(compact, expected_course_id)
            continue

        if re.match(r"^\s*INSERT\s+INTO\s+tasks\b", compact, flags=re.IGNORECASE):
            tasks, default_title_index = _parse_tasks_insert(compact, default_title_index)
            task_payloads.extend(tasks)
            continue

        if re.match(r"^\s*(BEGIN|COMMIT|END|ROLLBACK)\b", compact, flags=re.IGNORECASE):
            continue

        raise ValueError(f"Недопустимая SQL-команда: {compact[:80]}")

    if lesson_payload is None:
        raise ValueError("В SQL нет INSERT INTO lessons.")
    if not task_payloads:
        raise ValueError("В SQL нет INSERT INTO tasks.")

    lesson_payload["tasks"] = task_payloads
    normalized_sql = _build_normalized_sql(lesson_payload)
    return normalized_sql, lesson_payload


def _base_prompt(course_id: int) -> str:
    return f"""
Ты помогаешь заполнить базу учебного бота.

Нужно вернуть SQL для SQLite, который добавляет один новый урок в course_id = {course_id}
и все задачи из присланного листка.

Верни только SQL, без markdown, без пояснений и без комментариев.

Используй только такие команды:
1) ровно один INSERT INTO lessons
2) один или несколько INSERT INTO tasks

Ожидаемый формат:
INSERT INTO lessons (course_id, title, status) VALUES ({course_id}, 'Название урока', 'open');
INSERT INTO tasks (lesson_id, title, status, description) VALUES (0, '1', 'open', 'Текст задачи');
INSERT INTO tasks (lesson_id, title, status, description) VALUES (0, '2а', 'open', 'Текст задачи');

Правила:
1) Не используй UPDATE, DELETE, DROP, CREATE, ALTER и другие команды кроме INSERT INTO lessons/tasks.
2) lesson_id в INSERT INTO tasks можно ставить любым целым числом-плейсхолдером, бот его перепишет сам.
3) Не заполняй id вручную.
4) Используй одинарные кавычки в SQL-строках.
5) Если в тексте есть апостроф, экранируй его удвоением.
6) title у задачи это номер или подпункт: 1, 2a, 2б, 7* и т.п.
7) description у задачи это полный текст задачи.
8) Не пропускай видимые задачи и подпункты.
9) Не объединяй разные задачи в одну.
10) status для урока и задач ставь 'open'.
""".strip()


def _retry_prompt(course_id: int, previous_sql: str, admin_feedback: str) -> str:
    return f"""
Исправь SQL для SQLite по замечаниям администратора.

Нужно вернуть только SQL, без markdown, без пояснений и без комментариев.
Новый SQL должен добавлять один урок в course_id = {course_id} и все его задачи.

Замечания администратора:
{admin_feedback}

Текущая версия SQL:
{previous_sql}

Требования:
1) Используй только INSERT INTO lessons и INSERT INTO tasks.
2) lesson_id в INSERT INTO tasks можно ставить любым целым числом-плейсхолдером, бот его перепишет сам.
3) Не заполняй id вручную.
4) Используй одинарные кавычки в SQL-строках.
5) Не пропускай видимые задачи и подпункты.
6) Не объединяй разные задачи в одну.
7) status для урока и задач ставь 'open'.
""".strip()


def _request_lesson_sql(lesson_file_path: str, prompt: str, model_key: str, course_id: int) -> tuple[str, dict]:
    config = load_config()
    api_key = str(config["openai-api-key"]).strip()
    model = _pick_model(config, model_key)

    if not os.path.exists(lesson_file_path):
        raise FileNotFoundError(f"Не найден файл с задачами: {lesson_file_path}")

    uploaded_file_id = None
    try:
        lesson_content, uploaded_file_id = _build_lesson_content(api_key, lesson_file_path)
        payload = {
            "model": model,
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}, *lesson_content],
                }
            ],
        }

        response = requests.post(
            f"{OPENAI_API_BASE}/responses",
            headers={
                **_openai_headers(api_key),
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            raise RuntimeError(f"OpenAI вернул ошибку: {response.text}") from error

        response_text = _extract_response_text(response.json())
        if not response_text:
            raise RuntimeError("OpenAI вернул пустой ответ.")

        return normalize_lesson_sql(response_text, expected_course_id=course_id)
    finally:
        if uploaded_file_id:
            _delete_uploaded_file(api_key, uploaded_file_id)


def generate_lesson_sql(lesson_file_path: str, course_id: int) -> tuple[str, dict]:
    return _request_lesson_sql(
        lesson_file_path=lesson_file_path,
        prompt=_base_prompt(course_id),
        model_key="openai-model-sql",
        course_id=course_id,
    )


def fix_lesson_sql(lesson_file_path: str, course_id: int, previous_sql: str, admin_feedback: str) -> tuple[str, dict]:
    return _request_lesson_sql(
        lesson_file_path=lesson_file_path,
        prompt=_retry_prompt(course_id, previous_sql, admin_feedback),
        model_key="openai-model-sql",
        course_id=course_id,
    )


def main() -> None:
    config = load_config()
    lesson_file_path = config.get("image-path", "photo_2026-02-10_12-18-31.jpg")
    course_id = int(config.get("course-id", 1))
    sql_text, _ = generate_lesson_sql(lesson_file_path=lesson_file_path, course_id=course_id)
    print(sql_text)


if __name__ == "__main__":
    main()
