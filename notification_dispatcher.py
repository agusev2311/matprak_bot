import telebot
import json
import sqlite3

with open('config.json', 'r') as file:
    config = json.load(file)

bot = telebot.TeleBot(config["tg-token"])

text = f"""
🔔 Глобальное уведомление от администрации:

{input("Введите текст уведомления: ")}"""

with sqlite3.connect(config["db-name"]) as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [user[0] for user in cursor.fetchall()]

for user in users:
    bot.send_message(user, text)

