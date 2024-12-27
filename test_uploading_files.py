import telebot
import json
import os
import sql_return
with open('config.json', 'r') as file:
    config = json.load(file)
print(config)

sql_return.init_files_db()

bot = telebot.TeleBot(config["tg-token"])

@bot.message_handler(content_types=['text'])
def handle_text(message):
    bot.reply_to(message, f"Текст сообщения: {message.text}")

@bot.message_handler(content_types=['document', 'photo'])
def handle_files(message):
    if not os.path.exists('files'):
        os.makedirs('files')
    
    try:
        file_id = message.document.file_id if message.content_type == 'document' else message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        
        if file_info.file_size > 15 * 1024 * 1024:  # 15 МБ в байтах
            bot.reply_to(message, "Файл слишком большой. Максимальный размер - 15 МБ.")
            return
        
        downloaded_file = bot.download_file(file_info.file_path)
        
        file_extension = os.path.splitext(file_info.file_path)[1]
        
        new_file_name = f'{sql_return.next_name("files")}{file_extension}'
        save_path = f'files/{new_file_name}'
        
        with open(save_path, 'wb') as new_file:
            new_file.write(downloaded_file)
        sql_return.save_file(message.content_type, new_file_name, save_path, message.from_user.id)

        # print(message)
        print("New message")
        bot.reply_to(message, f"Файл сохранен как {new_file_name} (текст сообщения: {message.caption})")

    except telebot.apihelper.ApiTelegramException as e:
        if "file is too big" in str(e):
            bot.reply_to(message, "Файл слишком большой для загрузки через Telegram API.")
        else:
            bot.reply_to(message, "Произошла ошибка при обработке файла.")

@bot.message_handler(commands=['get_file'])
def get_file_by_id(message):
    try:
        file_info = sql_return.get_file(message.text.split()[1])
        
        if not file_info:
            bot.reply_to(message, "Файл не найден")
            return
            
        file_type = file_info[2]
        file_name = file_info[3] 
        file_path = file_info[4]
        
        if not os.path.exists(file_path):
            bot.reply_to(message, f"Файл не найден на диске ({file_path})")
            return
            
        if file_type == 'photo':
            with open(file_path, 'rb') as photo:
                bot.send_photo(message.chat.id, photo, caption=file_name)
        else:
            with open(file_path, 'rb') as doc:
                bot.send_document(message.chat.id, doc, visible_file_name=file_name)
                
    except (IndexError, ValueError):
        bot.reply_to(message, "Пожалуйста, укажите ID файла. Пример: /get_file 1")

bot.polling(none_stop=True)
