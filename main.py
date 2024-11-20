import telebot
from telebot import types
import sqlite3
import time
import datetime
import sql_return
import json
from dateutil.relativedelta import relativedelta

with open('config.json', 'r') as file:
    config = json.load(file)
print(config)

sql_return.init_db()

bot = telebot.TeleBot(config["tg-token"])

@bot.message_handler(commands=["start"])
def start(message):
    user = sql_return.find_user_id(message.from_user.id)
    if user and user[3] == "pending":
        bot.reply_to(message, "Вы уже подали заявку, ожидайте ответа администратора.")
    elif user and user[3] == "approved":
        markup = types.InlineKeyboardMarkup()
        button1 = types.InlineKeyboardButton("✏️ Отправить решение", callback_data=f'mm_send')
        button2 = types.InlineKeyboardButton("🔍 Принять решение", callback_data=f'mm_check_0')
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

def register_name(message):
    name = message.text.split()
    if len(name) != 2:
        bot.reply_to(message, f"Вы ввели имя и фамилию неправильно. Введите их снова.")
        bot.register_next_step_handler(message, register_name)
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

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    user_id = call.data.split('_')[-1]
    if call.data.startswith("reg_approve_"):
        sql_return.set_user_status(user_id, "approved")
        bot.send_message(user_id, "Ваша регистрация была одобрена! Введите /start для попадания в главное меню или /help для помощи.")
        bot.delete_message(call.message.chat.id, call.message.message_id)
    elif call.data.startswith("reg_deny_"):
        sql_return.delete_user(user_id)
        bot.send_message(user_id, "Ваша заявка была отклонена. Вы можете подать её снова.")
        bot.delete_message(call.message.chat.id, call.message.message_id)
    elif call.data.startswith("reg_ban_"):
        sql_return.set_user_status(user_id, "banned")
        bot.send_message(user_id, "Вы были забанены и не можете подать заявку снова. Рекомендую обратиться к администратору")
        bot.delete_message(call.message.chat.id, call.message.message_id)
    elif call.data.startswith("mm_send"):
        mm_send(call)
    elif call.data.startswith("mm_check"):
        mm_check(call, int(call.data.split("_")[-1]))
    elif call.data.startswith("mm_courses_"):
        mm_courses(call, int(call.data.split('_')[-1]))
    elif call.data.startswith("mm_main_menu"):
        user = sql_return.find_user_id(call.from_user.id)

        if user and user[3] == "pending":
            bot.edit_message_text("Вы уже подали заявку, ожидайте ответа администратора.", chat_id=call.message.chat.id, message_id=call.message.message_id)
        elif user and user[3] == "approved":
            markup = types.InlineKeyboardMarkup()
            button1 = types.InlineKeyboardButton("✏️ Отправить решение", callback_data=f'mm_send')
            button2 = types.InlineKeyboardButton("🔍 Принять решение", callback_data=f'mm_check_0')
            button3 = types.InlineKeyboardButton("📃 Все курсы", callback_data=f'mm_courses_0')
            markup.add(button1)
            markup.add(button2)
            markup.add(button3)
            bot.edit_message_text(f"""Здравствуйте, {call.message.from_user.first_name}!""", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
        elif user and user[3] == "banned":
            bot.edit_message_text("Вы были забанены. Обратитесь к администратору", chat_id=call.message.chat.id, message_id=call.message.message_id)
        else:
            bot.edit_message_text(f"""Здравcтвуйте! Сейчас вы будете проходить регистрацию. Пожалуйста введите своё <b>имя</b> и <b>фамилию</b> (<u>обязательно в таком порядке</u>)\n\nПример: "Артём Гусев".""", parse_mode="HTML", chat_id=call.message.chat.id, message_id=call.message.message_id)
            bot.register_next_step_handler(call.message, register_name)
    elif call.data.startswith("course_"):
        course_info(call)
    elif call.data.startswith("add_student_"):
        add_student(call)
    elif call.data.startswith("add_developer_"):
        add_developer(call)
    elif call.data.startswith("content_"):
        course_content(call, int(call.data.split('_')[-2]), int(call.data.split("_")[-1]))
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
    else:
        bot.answer_callback_query(call.id, "Обработчика для этой кнопки не существует.")
    
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

    courses_per_page = 5
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

    is_admin = str(call.from_user.id) == config["admin_id"]

    lessons = sql_return.lessons_in_course(course_id)

    # all_courses = sql_return.all_courses()

    courses_per_page = 5
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

    is_admin = str(call.from_user.id) == config["admin_id"]

    tasks = sql_return.tasks_in_lesson(lesson_id)  

    courses_per_page = 5
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

        if task_deadline:
            deadline_date = datetime.datetime.strptime(task_deadline, '%Y-%m-%d %H:%M:%S')
            current_date = datetime.datetime.now()
            days_left = (deadline_date - current_date).total_seconds() / (60 * 60 * 24)
            if task_status == 'Архивирован' or deadline_date < current_date:
                deadline_str = deadline_date.strftime('%d-%m-%Y %H:%M')
                deadline_info = f"🗓 <b>Дедлайн</b>: {deadline_str}"
            elif days_left < 2:
                deadline_str = deadline_date.strftime('%d-%m-%Y %H:%M')
                deadline_info = f"🔥 <b>Дедлайн через</b>: {time_left_str} ({deadline_str})"
            else:
                time_left = relativedelta(deadline_date, current_date)
                time_left_str = f"{time_left.days} дней, {time_left.hours} часов, {time_left.minutes} минут"
                deadline_str = deadline_date.strftime('%d-%m-%Y %H:%M')
                deadline_info = f"⏰ <b>Дедлайн через</b>: {time_left_str} ({deadline_str})"
        else:
            deadline_info = "⏰ <b>Дедлайн</b>: Не указан"

        task_info_message = (f"Вы начали сдачу решения для задачи, приведённой ниже. Если вы хотите отменить это действие, напишите вместо текста решения \"Stop\".\n\nЕсли вам нужно прикрепить файл (включая изображение), загрузите его на gachi.gay и вставьте ссылку в текст ответа. Если вам нужно прикрепить код, вы можете вставить его в качестве файла, через Telegram, экранировав его тремя символами \"`\", или загрузив на pastebin.com.\n\n"
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

def mm_send_final_2(message, lesson_id, course_id, task_id, user_id):
    answer_text = message.text
    # lesson_id, course_id, task_id = new_student_answer_dict[message.from_user.id]
    if message.text == "Stop":
        bot.send_message(message.chat.id, "Отменено")
        return
    sql_return.new_student_answer(task_id, user_id, answer_text)
    bot.send_message(message.chat.id, "Решение отправлено на проверку")
    for i in sql_return.developers_list(course_id):
        bot.send_message(i, f"Поступило новое решение для проверки от {sql_return.get_user_name(user_id)[0]} {sql_return.get_user_name(user_id)[1]}")

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

    courses_per_page = 5
    total_pages = (len(filtered_courses) + courses_per_page - 1) // courses_per_page
    page_courses = filtered_courses[page * courses_per_page:(page + 1) * courses_per_page]

    markup = types.InlineKeyboardMarkup()
    if page == 0:
        markup.add(types.InlineKeyboardButton(f"🗂 Все решения", callback_data=f'check-course-all_'))
    for course in page_courses:
        markup.add(types.InlineKeyboardButton(f"👨‍🏫 {course[1]}", callback_data=f'check-course_{course[0]}'))

    navigation = []
    if page > 0:
        navigation.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f'mm_check_{page - 1}'))
    if page < total_pages - 1:
        navigation.append(types.InlineKeyboardButton("➡️ Вперед", callback_data=f'mm_check_{page + 1}'))

    markup.row(*navigation)
    markup.add(types.InlineKeyboardButton("🏠 Главное меню", callback_data="mm_main_menu"))
    bot.edit_message_text(f"Выберите курс для принятия задания\nСтраница {page + 1} из {total_pages}:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

def check_all(call):
    task_data = sql_return.last_student_answer_all(call.from_user.id)
    check_task(type=f"check-course-all_", call=call, task_data=task_data)

def check_course(call, course_id):
    task_data = sql_return.last_student_answer_course(course_id)
    check_task(type=f"check-course_{course_id}", call=call, task_data=task_data)

comment_for_answer_dict = dict([])

def check_task(type: str, call, task_data, comment: str = "None"):
    markup = types.InlineKeyboardMarkup()
    if task_data == None:
        markup.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="mm_check_0"))
        bot.edit_message_text(f"У вас нет непроверенных решений в этом разделе", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
        return
    v = []
    if not isinstance(task_data, dict):
        v.append(types.InlineKeyboardButton("✅ Принять", callback_data=f"check-final_accept_{task_data[0]}"))
        v.append(types.InlineKeyboardButton("❌ Отклонить", callback_data=f"check-final_reject_{task_data[0]}"))
        markup.row(*v)
        task_data_2 = sql_return.get_task_from_id(task_data[1])
        lesson_data = sql_return.get_lesson_from_id(task_data_2[1])
        text = f"<b>Решение</b>:\n<b>Отправил</b> {sql_return.get_user_name(task_data[2])[0]} {sql_return.get_user_name(task_data[2])[1]}\n<b>Урок</b>: {lesson_data[2]}\n<b>Задача</b>: {task_data_2[2]}\n<b>Решение</b>:\n{task_data[3]}\n<b>Комментарий к вердикту</b>: {comment}"
    else:
        v.append(types.InlineKeyboardButton("✅ Принять", callback_data=f"check-final_accept_{task_data['answer_id']}"))
        v.append(types.InlineKeyboardButton("❌ Отклонить", callback_data=f"check-final_reject_{task_data['answer_id']}"))
        markup.row(*v)
        markup.add(types.InlineKeyboardButton("✍️ Добавить комментарий", callback_data=f"check-add-comment_{type}_{task_data['answer_id']}"))
        task_data_2 = sql_return.get_task_from_id(task_data["task_id"])
        lesson_data = sql_return.get_lesson_from_id(task_data_2[1])
        text = f"<b>Решение</b>:\n<b>Отправил</b> {sql_return.get_user_name(task_data['student_id'])[0]} {sql_return.get_user_name(task_data['student_id'])[1]}\n<b>Урок</b>: {lesson_data[2]}\n<b>Задача</b>: {task_data_2[2]}\n<b>Решение</b>:\n{task_data['answer_text']}\n<b>Комментарий к вердикту</b>: {comment}"
    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="HTML")
    
def check_add_comment(message, call, type: str, task_id):
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
    bot.send_message(sa_data[2], f"Ваше решение проверено!\n\nТекст решения:\n{sa_data[3]}\nВердикт: {verdict}\nКомментарий: {comment}")
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

    courses_per_page = 5
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

    developers = [str(dev_id) for dev_id in developer_ids.split()]
    developer_names = []
    for dev_id in developers:
        user = sql_return.get_user_name(int(dev_id))
        if user:
            developer_names.append(f"{user[0]} {user[1]}")
        else:
            developer_names.append(f"Пользователь с ID {dev_id} не найден")

    students = [str(student_id) for student_id in student_ids.split()]
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
    markup.add(types.InlineKeyboardButton("📃 К курсам", callback_data="mm_courses_0"))

    bot.edit_message_text(course_info, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

def add_student(call):
    course_id = int(call.data.split('_')[-1])
    bot.reply_to(call.message, "Введите ID ученика, которого хотите добавить:")
    bot.register_next_step_handler(call.message, lambda message: add_student_to_course(message, course_id))

def add_student_to_course(message, course_id):
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
        developer = sql_return.find_user_id(developer_id)

        if not developer:
            bot.reply_to(message, "Пользователь с таким ID не найден.")
            return

        developer_ids = sql_return.developers_list(course_id)
        if str(developer_id) not in developer_ids.split():
            new_developer_ids = developer_ids + f" {developer_id}"
            sql_return.try_add_developer_to_course(course_id, new_developer_ids.strip())
            bot.reply_to(message, f"Разработчик {developer[1]} {developer[2]} добавлен в курс!")
        else:
            bot.reply_to(message, "Этот разработчик уже находится в курсе.")
    except ValueError:
        bot.reply_to(message, "Неправильный ID. Попробуйте снова.")

def course_content(call, course_id, page=0):
    user = sql_return.find_user_id(call.from_user.id)

    if not user:
        bot.send_message(call.message.chat.id, "Вы не зарегистрированы.")
        return

    is_admin = str(call.from_user.id) == config["admin_id"]

    lessons = sql_return.lessons_in_course(course_id)

    # all_courses = sql_return.all_courses()

    courses_per_page = 5
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

    if (is_admin or sql_return.is_course_dev(call.from_user.id, sql_return.developers_list(course_id))) and page == 0:
        markup.add(types.InlineKeyboardButton("➕ Создать урок", callback_data=f'create_lesson_{course_id}'))

    markup.add(types.InlineKeyboardButton("🔙 К курсу", callback_data=f"course_{course_id}"))

    bot.edit_message_text(f"{description}\nСтраница {page + 1} из {total_pages}:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

def lesson_content(call, course_id, lesson_id, page=0):
    user = sql_return.find_user_id(call.from_user.id)

    if not user:
        bot.send_message(call.message.chat.id, "Вы не зарегистрированы.")
        return

    is_admin = str(call.from_user.id) == config["admin_id"]

    tasks = sql_return.tasks_in_lesson(lesson_id)  

    courses_per_page = 5
    total_pages = (len(tasks) + courses_per_page - 1) // courses_per_page
    page_courses = tasks[page * courses_per_page:(page + 1) * courses_per_page]

    description = "Содержание урока:\n"

    markup = types.InlineKeyboardMarkup()
    for lesson in page_courses:
        markup.add(types.InlineKeyboardButton(f"{lesson[2]}", callback_data=f'task_{lesson[0]}_{lesson_id}_{course_id}'))

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
    task = sql_return.task_info(task_id)
    
    if task:
        task_id, lesson_id, task_title, task_status, task_deadline, task_description = task

        status_translation = {
            'open': 'Открыт',
            'arc': 'Архивирован',
            'dev': 'В разработке'
        }
        task_status = status_translation.get(task_status, 'Неизвестен')

        if task_deadline:
            deadline_date = datetime.datetime.strptime(task_deadline, '%Y-%m-%d %H:%M:%S')
            current_date = datetime.datetime.now()
            days_left = (deadline_date - current_date).total_seconds() / (60 * 60 * 24)
            if task_status == 'Архивирован' or deadline_date < current_date:
                deadline_str = deadline_date.strftime('%d-%m-%Y %H:%M')
                deadline_info = f"🗓 <b>Дедлайн</b>: {deadline_str}"
            elif days_left < 2:
                deadline_str = deadline_date.strftime('%d-%m-%Y %H:%M')
                deadline_info = f"🔥 <b>Дедлайн через</b>: {time_left_str} ({deadline_str})"
            else:
                time_left = relativedelta(deadline_date, current_date)
                time_left_str = f"{time_left.days} дней, {time_left.hours} часов, {time_left.minutes} минут"
                deadline_str = deadline_date.strftime('%d-%m-%Y %H:%M')
                deadline_info = f"⏰ <b>Дедлайн через</b>: {time_left_str} ({deadline_str})"
        else:
            deadline_info = "⏰ <b>Дедлайн</b>: Не указан"

        task_info_message = (f"📌 <b>Название задачи</b>: {task_title}\n"
                             f"🔖 <b>Статус</b>: {task_status}\n"
                             f"{deadline_info}\n"
                             f"📝 <b>Текст задачи</b>: {task_description if task_description else 'Нет текста задачи'}")
        
        markup = types.InlineKeyboardMarkup()
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

def create_course(call):
    bot.edit_message_text(f"""🎓 Вы создаёте курс.
                          
📋 Информация о курсе:
👨‍🏫 Создатель курса: {sql_return.get_user_name(call.from_user.id)[0]} {sql_return.get_user_name(call.from_user.id)[1]} ({call.from_user.id})
📚 Название курса: -
👥 Разработчики: -

✏️ Пожалуйста, введите название курса:""", chat_id=call.message.chat.id, message_id=call.message.message_id)
    bot.register_next_step_handler(call.message, create_course_name, call.message.message_id)

def create_course_name(message, editing_message_id):
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
    name = message.text
    bot.delete_message(message.chat.id, message.message_id)
    sql_return.create_lesson(course_id, name)
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
    task_name = message.text
    bot.delete_message(message.chat.id, message.message_id)
    bot.edit_message_text(f"""🎓 Вы создаёте задачу.
                          
📋 Информация о задаче:
📚 Название задачи: {task_name}
📝 Текст задачи: - 

✏️ Пожалуйста, введите текст задачи:""", chat_id=message.chat.id, message_id=editing_message_id)
    bot.register_next_step_handler(message, create_task_description, editing_message_id, lesson_id, course_id, task_name)

def create_task_description(message, editing_message_id, lesson_id, course_id, task_name):
    task_description = message.text
    bot.delete_message(message.chat.id, message.message_id)
    sql_return.create_task(lesson_id, course_id, task_name, task_description)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 К списку задач", callback_data=f"lesson_{course_id}_{lesson_id}_0"))
    bot.edit_message_text(f"""✅ Задача "{task_name}" успешно создана!""", chat_id=message.chat.id, message_id=editing_message_id, reply_markup=markup)

@bot.message_handler(commands=["support"])
def support(message):
    bot.reply_to(message, f"Поддержка находится в лс у @agusev2311")

@bot.message_handler(commands=["help"])
def help(message):
    text = """Список всех команд в боте и faq:
Команды:
/start - регистрация или главное меню

/support - поддержка

/help - этот список
"""
    bot.send_message(message.chat.id, text)

bot.polling(none_stop=True)