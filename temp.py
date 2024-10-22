import sqlite3

# Подключаемся к базе данных
conn = sqlite3.connect('users.db')
cursor = conn.cursor()

# Обновляем lesson_id для указанных id
updates = {
    10: 6,
    11: 7,
    12: 5,
    14: 7
}

for task_id, lesson_id in updates.items():
    cursor.execute("UPDATE tasks SET lesson_id = ? WHERE id = ?", (lesson_id, task_id))

# Сохраняем изменения
conn.commit()

# Закрываем соединение
cursor.close()
conn.close()

print("Данные успешно обновлены.")
