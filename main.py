import telebot
from telebot import types
import sqlite3
import time

conn = sqlite3.connect("users.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        first_name TEXT,
        last_name TEXT,
        status TEXT
    )
''')
conn.commit()

config = dict([])
for i in open("config", "r").readlines():
    config[i.split(" = ")[0]] = i.split(" = ")[1].split("\n")[0]
print(config)

bot = telebot.TeleBot(config["tg-token"])

@bot.message_handler(commands=["start"])
def start(message):
    cursor.execute("SELECT * FROM users WHERE user_id=?", (message.from_user.id,))
    user = cursor.fetchone()

    if user and user[3] == "pending":
        bot.reply_to(message, "Вы уже подали заявку, ожидайте ответа администратора.")
    elif user and user[3] == "approved":
        bot.reply_to(message, "Вы зарегестрированы!")
    elif user and user[3] == "banned":
        bot.reply_to(message, "Вы были забанины. Обратитесь к администратору")
    else:
        bot.reply_to(message, f"Здравcтвуйте! Сейчас вы будете проходить регистрацию. Пожалуйста введите своё <b>имя</b> и <b>фамилию</b> (<u>обязательно в таком порядке</u>)", parse_mode="HTML")
        bot.register_next_step_handler(message, register_name)

def register_name(message):
    name = message.text.split()
    if len(name) != 2:
        bot.reply_to(message, f"Вы ввели имя и фамилию неправильно. Введите их снова.")
        bot.register_next_step_handler(message, register_name)
    else:
        cursor.execute("INSERT INTO users (user_id, first_name, last_name, status) VALUES (?, ?, ?, ?)",
                       (int(message.from_user.id), name[0], name[1], 'pending'))
        conn.commit()

        bot.reply_to(message, "Мы отправили сообщение администратору. Теперь ожидайте подтверждения.")
        markup = types.InlineKeyboardMarkup()
        button1 = types.InlineKeyboardButton("✅ Принять", callback_data=f'reg_approve_{message.from_user.id}')
        button2 = types.InlineKeyboardButton("🟡 Отклонить", callback_data=f'reg_deny_{message.from_user.id}')
        button3 = types.InlineKeyboardButton("❌ Забанить", callback_data=f'reg_ban_{message.from_user.id}')
        markup.add(button1)
        markup.add(button2, button3)
        bot.send_message(int(config["admin_id"]), f"@{message.from_user.username} ({message.from_user.id}) регистрируется как {name[0]} {name[1]}", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    user_id = call.data.split('_')[-1]

    if call.data.startswith("reg_approve_"):
        cursor.execute("UPDATE users SET status='approved' WHERE user_id=?", (user_id,))
        conn.commit()
        bot.send_message(user_id, "Ваша регистрация была одобрена! Введите /start")
    elif call.data.startswith("reg_deny_"):
        cursor.execute("DELETE FROM users WHERE user_id=?", (user_id,))
        conn.commit()
        bot.send_message(user_id, "Ваша заявка была отклонена. Вы можете подать её снова.")
    elif call.data.startswith("reg_ban_"):
        cursor.execute("UPDATE users SET status='banned' WHERE user_id=?", (user_id,))
        conn.commit()
        bot.send_message(user_id, "Вы были забанены и не можете подать заявку снова. Рекомендую обратиться к администратору")

    bot.delete_message(call.message.chat.id, call.message.message_id)

cre_courses = dict([])

@bot.message_handler(commands=["create_course"])
def create_course(message):
    bot.reply_to(message, f"""Вы начали создание курса. Чтобы его отменить напишите на любом этапе "stop".
Для начала введите имена всех людей, которых вы хотите добавить в разработчиков курса.
Для этого нужно ввести их id. Чтобы найти id человека перешлите боту @userinfobot любое сообщение этого человека.
Указывайте id через пробел (пример: "1234567 7654321 9876")
Если вы не хотите никого указывать отправьте "none"
Если вы успешно создадите курс, то он навсегда останется в базе данных бота, даже если вы его удалите.""")
    bot.register_next_step_handler(message, create_course_users)

def create_course_users(message):
    if message.text == "stop":
        bot.reply_to(message, f"Создание курса отменено")
        return
    elif message.text != "none":
        users_id = message.text.split()
        try:            
            added = ""
            for i in users_id:
                int(i)

            conn = sqlite3.connect("users.db", check_same_thread=False)
            cursor = conn.cursor()
            
            for i in users_id:
                cursor.execute('SELECT COUNT(*) FROM users WHERE user_id = ?', (int(i), ))
                count = cursor.fetchone()[0]
                # print(count)
                if count == 0:
                    added += f"{i} не зарегестрирован\n"
                elif count == 1:
                    cursor.execute('SELECT * FROM users WHERE user_id = ?', (int(i), ))
                    user_info = cursor.fetchone()
                    added += f"{user_info[1]} {user_info[2]} (id: {user_info[0]}, status: {user_info[3]})\n"
                else:
                    bot.send_message(config["1133611562"], f"❗️❗️❗️Человек под ID {i} присутствует в таблице пользователей несколько раз! Обратите на это внимание!")
                    added += f"{i} несколько в таблице. Это не нормально. Мы уже отправили сообщение администратору."
            
            conn.close()
            
            # return count > 0
            bot.reply_to(message, f"Вы добавили следующих людей: \n\n{added}\nЕсли вы добавили неправильных людей, напишите stop.")
            bot.register_next_step_handler(message, create_course_name)
            cre_courses[message.from_user.id] = [users_id]
        except:
            bot.reply_to(message, f"Вы неправавильно ввели id. Введите их сновы (вы всегда можете написать stop или none)")
            bot.register_next_step_handler(message, create_course_users)
    
def create_course_name(message):
    if message.text == "stop":
        bot.reply_to(message, f"Создание курса отменено")
        return

    
@bot.message_handler(commands=["support"])
def create_course(message):
    bot.reply_to(message, f"Поддержка находится в лс у @agusev2311")

bot.polling(none_stop=True)
