import openai
import json
import requests
import base64

# Function to read the image file and convert it to base64
def encode_image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

image_path = "files/e.jpg"
MyEncodedImage = encode_image_to_base64(image_path)

with open('config.json', 'r') as f:
    config = json.load(f)

client = openai.OpenAI(api_key=config['openai-api-key'])
api_key = config['openai-api-key']

question = "Что ты видишь?"
RuleInstructions = """Ты проверяешь решения. Ты должен дать результат (accept / reject) и коммментарий.

Пример вашего ответа:
accept
Решение верное

reject
Неверно указана переменная a"""

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}"
}

payload = {
    "model": "gpt-4o-mini",
    "messages": [
        {"role": "system", "content": RuleInstructions},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{MyEncodedImage}",
                        "detail": "auto"
                    }
                }
            ]
        }
    ],
    "max_tokens": 300
}

response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
response_json = response.json()

# Extracting the message content
if "choices" in response_json and response_json["choices"]:
    message_content = response_json["choices"][0]["message"]["content"]
    print("AI Response Message:")
    print(message_content)
else:
    print("No valid response received.")

# Extracting usage information
if "usage" in response_json:
    usage_info = response_json["usage"]
    print("Usage Information:")
    print(f"Prompt Tokens: {usage_info['prompt_tokens']}")
    print(f"Completion Tokens: {usage_info['completion_tokens']}")
    print(f"Total Tokens: {usage_info['total_tokens']}")
