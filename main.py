import telebot
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

bot.polling(none_stop=True)
