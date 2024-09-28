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

cursor.execute('''
    CREATE TABLE IF NOT EXISTS courses (
        course_id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_name TEXT,
        creator_id INTEGER,
        student_id TEXT,
        developers TEXT
    )
''')
conn.commit()

config = dict([])
for i in open("config", "r").readlines():
    config[i.split(" = ")[0]] = i.split(" = ")[1].split("\n")[0]
print(config)

bot = telebot.TeleBot(config["tg-token"])

# Хэндлер команды /start
@bot.message_handler(commands=["start"])
def start(message):
    cursor.execute("SELECT * FROM users WHERE user_id=?", (message.from_user.id,))
    user = cursor.fetchone()

    if user and user[3] == "pending":
        bot.reply_to(message, "Вы уже подали заявку, ожидайте ответа администратора.")
    elif user and user[3] == "approved":
        markup = types.InlineKeyboardMarkup()
        button1 = types.InlineKeyboardButton("✏️ Отправить решение", callback_data=f'mm_send')
        button2 = types.InlineKeyboardButton("🔍 Принять решение", callback_data=f'mm_check')
        button3 = types.InlineKeyboardButton("📃 Все курсы", callback_data=f'mm_courses_0')
        markup.add(button1)
        markup.add(button2)
        markup.add(button3)
        bot.reply_to(message, f"""Здравствуйте, {message.from_user.first_name}!""", reply_markup=markup)
    elif user and user[3] == "banned":
        bot.reply_to(message, "Вы были забанены. Обратитесь к администратору")
    else:
        bot.reply_to(message, f"""Здравcтвуйте! Сейчас вы будете проходить регистрацию. Пожалуйста введите своё <b>имя</b> и <b>фамилию</b> (<u>обязательно в таком порядке</u>)\n\nПример: "Артём Гусев".""", parse_mode="HTML")
        bot.register_next_step_handler(message, register_name)

# Регистрация пользователя
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

# Хэндлер для обработки колбеков
@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    user_id = call.data.split('_')[-1]
    if call.data.startswith("reg_approve_"):
        cursor.execute("UPDATE users SET status='approved' WHERE user_id=?", (user_id,))
        conn.commit()
        bot.send_message(user_id, "Ваша регистрация была одобрена! Введите /start")
        bot.delete_message(call.message.chat.id, call.message.message_id)
    elif call.data.startswith("reg_deny_"):
        cursor.execute("DELETE FROM users WHERE user_id=?", (user_id,))
        conn.commit()
        bot.send_message(user_id, "Ваша заявка была отклонена. Вы можете подать её снова.")
        bot.delete_message(call.message.chat.id, call.message.message_id)
    elif call.data.startswith("reg_ban_"):
        cursor.execute("UPDATE users SET status='banned' WHERE user_id=?", (user_id,))
        conn.commit()
        bot.send_message(user_id, "Вы были забанены и не можете подать заявку снова. Рекомендую обратиться к администратору")
        bot.delete_message(call.message.chat.id, call.message.message_id)
    elif call.data.startswith("mm_send"):
        mm_send(call)
    elif call.data.startswith("mm_check"):
        mm_check(call)
    elif call.data.startswith("mm_courses_"):
        mm_courses(call, int(call.data.split('_')[-1]))
    elif call.data.startswith("mm_main_menu"):
        cursor.execute("SELECT * FROM users WHERE user_id=?", (call.from_user.id,))
        user = cursor.fetchone()

        if user and user[3] == "pending":
            bot.reply_to(call.message, "Вы уже подали заявку, ожидайте ответа администратора.")
        elif user and user[3] == "approved":
            markup = types.InlineKeyboardMarkup()
            button1 = types.InlineKeyboardButton("✏️ Отправить решение", callback_data=f'mm_send')
            button2 = types.InlineKeyboardButton("🔍 Принять решение", callback_data=f'mm_check')
            button3 = types.InlineKeyboardButton("📃 Все курсы", callback_data=f'mm_courses_0')
            markup.add(button1)
            markup.add(button2)
            markup.add(button3)
            bot.reply_to(call.message, f"""Здравствуйте, {call.message.from_user.first_name}!""", reply_markup=markup)
        elif user and user[3] == "banned":
            bot.reply_to(call.message, "Вы были забанены. Обратитесь к администратору")
        else:
            bot.reply_to(call.message, f"""Здравcтвуйте! Сейчас вы будете проходить регистрацию. Пожалуйста введите своё <b>имя</b> и <b>фамилию</b> (<u>обязательно в таком порядке</u>)\n\nПример: "Артём Гусев".""", parse_mode="HTML")
            bot.register_next_step_handler(call.message, register_name)
    elif call.data.startswith("course_"):
        course_info(call)
    elif call.data.startswith("add_student_"):
        add_student(call)
    elif call.data.startswith("add_developer_"):
        add_developer(call)

def mm_send(call):
    pass

def mm_check(call):
    pass

def mm_courses(call, page=0):
    cursor.execute("SELECT * FROM users WHERE user_id=?", (call.from_user.id,))
    user = cursor.fetchone()

    if not user:
        bot.send_message(call.message.chat.id, "Вы не зарегистрированы.")
        return

    is_admin = (user[3] == "approved" and str(call.from_user.id) == config["admin_id"])

    # Извлекаем курсы
    cursor.execute("SELECT * FROM courses")
    all_courses = cursor.fetchall()

    # Фильтрация курсов для не-админов
    student_or_developer_courses = []
    other_courses = []
    
    for course in all_courses:
        student_ids = course[3] if course[3] else ""  # Проверка на None
        developer_ids = course[4] if course[4] else ""  # Проверка на None
        
        # Если пользователь студент или разработчик, добавляем курс в отдельный список
        if str(call.from_user.id) in student_ids.split() or str(call.from_user.id) in developer_ids.split():
            student_or_developer_courses.append(course)
        else:
            other_courses.append(course)

    # Если админ, показываем сначала курсы, в которых он участвует, затем остальные
    if is_admin:
        filtered_courses = student_or_developer_courses + other_courses
    else:
        filtered_courses = student_or_developer_courses

    # Пагинация
    courses_per_page = 5
    total_pages = (len(filtered_courses) + courses_per_page - 1) // courses_per_page
    page_courses = filtered_courses[page * courses_per_page:(page + 1) * courses_per_page]

    # Формирование текста с объяснением для каждого эмодзи
    description = "Выберите курс:\n"
    description += "👨‍🎓 — Вы студент курса\n"
    description += "👨‍🏫 — Вы преподаватель курса\n"
    
    # Эмодзи для админов будет добавлено только если текущий пользователь админ
    if is_admin:
        description += "🔑 — Вы администратор\n"

    # Формирование кнопок
    markup = types.InlineKeyboardMarkup()
    for course in page_courses:
        student_ids = course[3] if course[3] else ""
        developer_ids = course[4] if course[4] else ""

        if str(call.from_user.id) in student_ids.split():
            emoji = "👨‍🎓"  # Вы студент
        elif str(call.from_user.id) in developer_ids.split():
            emoji = "👨‍🏫"  # Вы преподаватель
        elif is_admin:
            emoji = "🔑"  # Админ видит все курсы
        else:
            emoji = "🚫"  # Не состоит в курсе

        markup.add(types.InlineKeyboardButton(f"{emoji} {course[1]}", callback_data=f'course_{course[0]}'))

    # Кнопки для навигации по страницам
    navigation = []
    if page > 0:
        navigation.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f'mm_courses_{page - 1}'))
    if page < total_pages - 1:
        navigation.append(types.InlineKeyboardButton("➡️ Вперед", callback_data=f'mm_courses_{page + 1}'))

    markup.row(*navigation)
    markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="mm_main_menu"))

    # Изменяем сообщение без проверки
    bot.edit_message_text(f"{description}\nСтраница {page + 1} из {total_pages}:",
                          chat_id=call.message.chat.id,
                          message_id=call.message.message_id, 
                          reply_markup=markup)

def course_info(call):
    course_id = int(call.data.split('_')[-1])
    cursor.execute("SELECT * FROM courses WHERE course_id=?", (course_id,))
    course = cursor.fetchone()

    if not course:
        bot.send_message(call.message.chat.id, "Курс не найден.")
        return

    course_name = course[1]
    creator_id = course[2]
    student_ids = course[3] if course[3] else ""
    developer_ids = course[4] if course[4] else ""

    # Получаем список разработчиков
    developers = [str(dev_id) for dev_id in developer_ids.split()]
    developer_names = []
    for dev_id in developers:
        cursor.execute("SELECT first_name, last_name FROM users WHERE user_id=?", (int(dev_id),))
        user = cursor.fetchone()
        if user:
            developer_names.append(f"{user[0]} {user[1]}")
        else:
            developer_names.append(f"Пользователь с ID {dev_id} не найден")

    # Получаем список студентов
    students = [str(student_id) for student_id in student_ids.split()]
    student_names = []
    for student_id in students:
        cursor.execute("SELECT first_name, last_name FROM users WHERE user_id=?", (int(student_id),))
        user = cursor.fetchone()
        if user:
            student_names.append(f"{user[0]} {user[1]}")
        else:
            student_names.append(f"Пользователь с ID {student_id} не найден")

    # Формируем сообщение с информацией о курсе
    course_info = f"📚 Курс: {course_name}\n\n"
    course_info += f"Создатель: {creator_id}\n\n"
    course_info += "👨‍🏫 Разработчики:\n" + "\n".join(developer_names) + "\n\n"
    course_info += "👨‍🎓 Студенты:\n" + "\n".join(student_names) + "\n"

    cursor.execute("SELECT * FROM users WHERE user_id=?", (call.from_user.id,))
    user = cursor.fetchone()
    is_dev = str(call.from_user.id) in developer_ids.split()

    markup = types.InlineKeyboardMarkup()
    if int(call.from_user.id) == int(config["admin_id"]) or is_dev:
        markup.add(types.InlineKeyboardButton("➕ Добавить ученика", callback_data=f'add_student_{course_id}'))
        markup.add(types.InlineKeyboardButton("➕ Добавить разработчика", callback_data=f'add_developer_{course_id}'))
    markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="mm_main_menu"))

    bot.edit_message_text(course_info, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

def add_student(call):
    course_id = int(call.data.split('_')[-1])
    bot.reply_to(call.message, "Введите ID ученика, которого хотите добавить:")
    bot.register_next_step_handler(call.message, lambda message: add_student_to_course(message, course_id))

def add_student_to_course(message, course_id):
    try:
        student_id = int(message.text)
        cursor.execute("SELECT * FROM users WHERE user_id=?", (student_id,))
        student = cursor.fetchone()

        if not student:
            bot.reply_to(message, "Пользователь с таким ID не найден.")
            return

        # Добавляем студента в курс
        cursor.execute("SELECT student_id FROM courses WHERE course_id=?", (course_id,))
        student_ids = cursor.fetchone()[0] or ""
        if str(student_id) not in student_ids.split():
            new_student_ids = student_ids + f" {student_id}"
            cursor.execute("UPDATE courses SET student_id=? WHERE course_id=?", (new_student_ids.strip(), course_id))
            conn.commit()
            bot.reply_to(message, f"Ученик {student[1]} {student[2]} добавлен в курс!")
        else:
            bot.reply_to(message, "Этот ученик уже находится в курсе.")
    except ValueError:
        bot.reply_to(message, "Неправильный ID. Попробуйте снова.")

def add_developer(call):
    course_id = int(call.data.split('_')[-1])
    bot.reply_to(call.message, "Введите ID разработчика, которого хотите добавить:")
    bot.register_next_step_handler(call.message, lambda message: add_developer_to_course(message, course_id))

def add_developer_to_course(message, course_id):
    try:
        developer_id = int(message.text)
        cursor.execute("SELECT * FROM users WHERE user_id=?", (developer_id,))
        developer = cursor.fetchone()

        if not developer:
            bot.reply_to(message, "Пользователь с таким ID не найден.")
            return

        # Добавляем разработчика в курс
        cursor.execute("SELECT developers FROM courses WHERE course_id=?", (course_id,))
        developer_ids = cursor.fetchone()[0] or ""
        if str(developer_id) not in developer_ids.split():
            new_developer_ids = developer_ids + f" {developer_id}"
            cursor.execute("UPDATE courses SET developers=? WHERE course_id=?", (new_developer_ids.strip(), course_id))
            conn.commit()
            bot.reply_to(message, f"Разработчик {developer[1]} {developer[2]} добавлен в курс!")
        else:
            bot.reply_to(message, "Этот разработчик уже находится в курсе.")
    except ValueError:
        bot.reply_to(message, "Неправильный ID. Попробуйте снова.")

cre_courses = dict([])

# Создание курса
@bot.message_handler(commands=["create_course"])
def create_course(message):
    bot.reply_to(message, f"""Вы начали создание курса. Чтобы его отменить напишите на любом этапе "stop".
Для начала введите имена всех людей, которых вы хотите добавить в разработчиков курса.
Для этого нужно ввести их id. Чтобы найти id человека перешлите боту @userinfobot любое сообщение этого человека.
Указывайте id через пробел (пример: "1234567 7654321 9876")
Если вы не хотите никого указывать отправьте "none"
Если вы успешно создадите курс, то он навсегда останется в базе данных бота, даже если вы его удалите.""")
    bot.register_next_step_handler(message, create_course_users)

# Добавление разработчиков курса
def create_course_users(message):
    if message.text == "stop":
        bot.reply_to(message, f"Создание курса отменено")
        return
    elif message.text != "none":
        users_id = [str(message.from_user.id)].append(message.text.split())

        try:            
            added = ""
            for i in users_id:
                int(i)

            conn = sqlite3.connect("users.db", check_same_thread=False)
            cursor = conn.cursor()
            
            for i in users_id:
                cursor.execute('SELECT COUNT(*) FROM users WHERE user_id = ?', (int(i), ))
                count = cursor.fetchone()[0]
                if count == 0:
                    added += f"{i} не зарегестрирован\n"
                elif count == 1:
                    cursor.execute('SELECT * FROM users WHERE user_id = ?', (int(i), ))
                    user_info = cursor.fetchone()
                    added += f"{user_info[1]} {user_info[2]} (id: {user_info[0]}, status: {user_info[3]})\n"
                else:
                    bot.send_message(config["admin_id"], f"❗️❗️❗️Человек под ID {i} присутствует в таблице пользователей несколько раз! Обратите на это внимание!")
                    added += f"{i} несколько в таблице. Это не нормально. Мы уже отправили сообщение администратору."
            
            conn.close()
            bot.register_next_step_handler(message, create_course_name)
            bot.reply_to(message, f"""Вы добавили следующих людей: \n\n{added}\nЕсли вы добавили неправильных людей, напишите stop.\n\nТеперь введите название курса. Например "Матпрак 7С".""")
            cre_courses[message.from_user.id] = [users_id]
        except:
            bot.reply_to(message, f"Вы неправавильно ввели id. Введите их сновы (вы всегда можете написать stop или none)")
            bot.register_next_step_handler(message, create_course_users)
    else:
        cre_courses[message.from_user.id] = [[message.from_user.id]]
        bot.reply_to(message, f"""Вы никого не добавили\n\nТеперь введите название курса. Например "Матпрак 7С".""")
        bot.register_next_step_handler(message, create_course_name)

# Добавление названия курса
def create_course_name(message):
    if message.text == "stop":
        bot.reply_to(message, f"Создание курса отменено")
        return
    
    cre_cur_name = message.text

    # Проверяем, добавлял ли пользователь разработчиков
    if message.from_user.id not in cre_courses:
        bot.reply_to(message, f"Ошибка: вы не добавили разработчиков. Пожалуйста, начните создание курса заново.")
        return
    
    # Сохраняем курс в БД
    cursor.execute("INSERT INTO courses (course_name, creator_id, developers) VALUES (?, ?, ?)",
            (cre_cur_name, message.from_user.id, " ".join([str(i) for i in cre_courses[message.from_user.id][0]])))
    conn.commit()
    
    bot.reply_to(message, f"""Курс "{cre_cur_name}" создан и добавлен в базу данных!""")
    # Удаляем временные данные о курсе
    del cre_courses[message.from_user.id]

@bot.message_handler(commands=["support"])
def support(message):
    bot.reply_to(message, f"Поддержка находится в лс у @agusev2311")

bot.polling(none_stop=True)