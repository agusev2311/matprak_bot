import telebot
from telebot import types
import time

config = dict([])
for i in open("config", "r").readlines():
    config[i.split(" = ")[0]] = i.split(" = ")[1].split("\n")[0]
print(config)

bot = telebot.TeleBot(config["tg-token"])

register = dict([])

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, f"Здравcтвуйте! Сейчас вы будете проходить регистрацию. Пожалуйста введите своё <b>имя</b> и <b>фамилию</b> (<u>обязательно в таком порядке</u>)\n\nПозже администратор проверит, зарегестрированы ли вы, и в зависимости от этого вынесет вердикт: (зарегестрировать, проигнорировать (ваша заявка будет отклонена, но вы сможете подать ещё одну) или заблокировать (ваша заявка будет отклонена, и вы больше не сможете подать заявку))", parse_mode="HTML")
    bot.register_next_step_handler(message, register_name)

def register_name(message):
    name = message.text.split()
    print(name)
    if len(name) != 2:
        bot.reply_to(message, f"Вы ввели имя и фамилию неправильно. Введите их снова.")
        bot.register_next_step_handler(message, register_name)
    else:
        register[message.from_user.id] = name
        bot.reply_to(message, f"Мы отправили сообщение администратору. Теперь ожидайте подтверждения от него.")
        markup = types.InlineKeyboardMarkup()
        button1 = types.InlineKeyboardButton("✅ Принять", callback_data=f'reg_approve_{message.from_user.id}_{name[0]}_{name[1]}')
        button2 = types.InlineKeyboardButton("🟡 Отклонить", callback_data=f'reg_deny_{message.from_user.id}')
        button3 = types.InlineKeyboardButton("❌ Забанить", callback_data=f'reg_ban_{message.from_user.id}')
        markup.add(button1)
        markup.add(button2, button3)
        bot.send_message(int(config["admin_id"]), f"{message.from_user.username} регестрируется как {name[0]} {name[1]}", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    if (call.data[:4] == "reg_"):
        bot.delete_message(call.message.chat.id, call.message.message_id)
        if (call.data[:12] == "reg_approve_"):
            print("reg_approve_")
        elif (call.data[:9] == "reg_deny_"):
            print("reg_deny_")
        elif (call.data[:12] == "reg_"):
            print("reg_")
    # bot.send_message(call.message.from_user.id, call.data[:3])

bot.polling(none_stop=True)
