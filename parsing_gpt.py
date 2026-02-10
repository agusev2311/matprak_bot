import base64
import json
import os
import zipfile

import openai


def load_config():
    with open("config.json", "r") as f:
        return json.load(f)


def zip_db(db_path: str) -> str:
    zip_path = os.path.splitext(db_path)[0] + ".zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(db_path, arcname=os.path.basename(db_path))
    return zip_path


def load_image_data_url(image_path: str) -> str:
    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    ext = os.path.splitext(image_path)[1].lower()
    if ext in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif ext == ".png":
        mime = "image/png"
    else:
        raise ValueError(f"Unsupported image extension: {ext}")
    return f"data:{mime};base64,{encoded}"


def main() -> None:
    config = load_config()
    api_key = config["openai-api-key"]

    db_path = config.get("db-name", "users.db")
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    zip_path = zip_db(db_path)

    image_path = config.get("image-path", "photo_2026-02-10_12-18-31.jpg")
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")
    image_data_url = load_image_data_url(image_path)

    client = openai.OpenAI(api_key=api_key)

    with open(zip_path, "rb") as f:
        uploaded = client.files.create(file=f, purpose="user_data")

    instructions = (
        "You are a data analyst. Use the code interpreter only to inspect the "
        "SQLite database contained in the attached zip file. Do NOT use the code "
        "interpreter to analyze the image; use your vision instead."
    )
    prompt = (
        "Извлеките из zip-архива базу данных, проанализируйте базу данных и фото, "
        "и напишите в ответ SQL-запросы, которые добавят новый урок в базу данных "
        "по задачам с листочка. Номер задачи должен быть числом: например '1' и '2*' — "
        "это задачи, а 'А' — не задача. Фотографию анализируйте своим зрением, не питоном. "
        "Ответ должен содержать ТОЛЬКО SQL-запросы. Без форматирования, без лишнего текста."
        "Сначала создавайте урок, ему надо задать все поля, кроме тех, которые задаются автоматически. Потом создавайте уроки, и ставьте в id урока тот id, который должен был сгенерироваться у урока."
    )

    response = client.responses.create(
        model="gpt-4.1",
        tools=[
            {
                "type": "code_interpreter",
                "container": {
                    "type": "auto",
                    "memory_limit": "1g",
                    "file_ids": [uploaded.id],
                },
            }
        ],
        tool_choice="auto",
        instructions=instructions,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": image_data_url},
                ],
            }
        ],
    )

    print(response.output_text)


if __name__ == "__main__":
    main()
