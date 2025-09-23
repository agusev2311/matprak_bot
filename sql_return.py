import sqlite3
import json
import datetime
import os
from typing import Optional

with open('config.json', 'r') as file:
    config = json.load(file)

def init_db():
    conn = sqlite3.connect(config["db-name"], check_same_thread=False)
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
        CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            open_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(course_id) REFERENCES courses(id)
        )
    ''')

    # Status:
    # open
    # arc
    # dev

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lesson_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            deadline TIMESTAMP,
            description TEXT,
            FOREIGN KEY(lesson_id) REFERENCES lessons(id)
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
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS student_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            answer_text TEXT,
            files_id TEXT,
            submission_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            verdict TEXT,           -- Вердикт преподавателя
            comment TEXT,           -- Комментарий к вердикту
            FOREIGN KEY(task_id) REFERENCES tasks(id),
            FOREIGN KEY(student_id) REFERENCES users(user_id)
        );
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bug_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT,
            time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            executor_id INTEGER,
            action TEXT,
            time TIMESTAMP DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', '+3 hours')),
            info TEXT
        )
    ''')

    # Verdict:
    # accepted
    # rejected

    conn.commit()
    cursor.close()

def init_files_db():
    conn = sqlite3.connect(config["files-db-name"], check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT,
            type TEXT,
            file_name TEXT,
            file_path TEXT,
            creator_id INTEGER,
            creation_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # type:
    # photo
    # file
    conn.commit()
    cursor.close()

def save_file(file_type: str, file_name: str, file_path: str, creator_id: int):
    file_id = file_path.split("/")[-1].split(".")[0]
    with sqlite3.connect(config["files-db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO files (file_id, type, file_name, file_path, creator_id) VALUES (?, ?, ?, ?, ?)", (file_id, file_type, file_name, file_path, creator_id))
        conn.commit()

def get_file(file_id: str):
    with sqlite3.connect(config["files-db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM files WHERE file_id=?", (file_id,))
        return cursor.fetchone()

def lessons_in_class():
    pass

def find_user_id(user_id):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        user = cursor.fetchone()
    return user

def reg_user(user_id, first_name, second_name, status="pending"):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (user_id, first_name, last_name, status) VALUES (?, ?, ?, ?)",
                    (user_id, first_name, second_name, status))
        conn.commit()

def set_user_status(user_id, status):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET status=? WHERE user_id=?", (status, user_id,))
        conn.commit()

def delete_user(user_id):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE user_id=?", (user_id,))
        conn.commit()

def all_courses():
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM courses")
        return cursor.fetchall()

def find_course_id(course_id):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM courses WHERE course_id=?", (course_id,))
        return cursor.fetchone()

def is_course_dev(user_id: int, devs_id: str) -> bool:
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        user = cursor.fetchone()
        return str(user_id) in devs_id.split()

def get_user_name(user_id):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT first_name, last_name FROM users WHERE user_id=?", (int(user_id),))
        return cursor.fetchone()

def students_list(course_id):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT student_id FROM courses WHERE course_id=?", (course_id,))
        return cursor.fetchone()[0] or ""

def developers_list(course_id):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT developers FROM courses WHERE course_id=?", (course_id,))
        # print(cursor.fetchone()[0])
        return cursor.fetchone()[0] or ""

def try_add_student_to_course(course_id, new_students_list):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE courses SET student_id=? WHERE course_id=?", (new_students_list, course_id))
        conn.commit()

def try_add_developer_to_course(course_id, new_developer_list):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE courses SET developers=? WHERE course_id=?", (new_developer_list, course_id))
        conn.commit()

def create_course(cre_cur_name: str, user_id: int, developers: str):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO courses (course_name, creator_id, developers) VALUES (?, ?, ?)",
            (cre_cur_name, user_id, developers))
        conn.commit()

def lessons_in_course(course_id: int):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM lessons WHERE course_id=?", (course_id,))
        return cursor.fetchall()

def tasks_in_lesson(lesson_id):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tasks WHERE lesson_id=?", (lesson_id,))
        return cursor.fetchall()

def task_info(task_id: int):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute('''SELECT * FROM tasks WHERE id = ?''', (task_id, ))
        return cursor.fetchone()

def new_student_answer(task_id: int, student_id: int, answer_text: str, files_id: str = None):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO student_answers (task_id, student_id, answer_text, submission_date, verdict, comment, files_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (task_id, student_id, answer_text, str(datetime.datetime.now()), None, None, files_id))  # Здесь кортеж
        conn.commit()

def next_name(dir: str) -> str:
    files = os.listdir(dir)
    new_files = []
    for i in files:
        new_files.append(i.split(".")[0])
    i = 0
    while True:
        numb = hex(i)[2:]
        if numb not in new_files:
            break
        i += 1
    return hex(i)[2:]

def save_photo(downloaded_file):
    downloaded_file

    save_path = f'files/{next_name("files")}.jpg'

    with open(save_path, 'wb') as new_file:
        new_file.write(downloaded_file)

def last_student_answer_course(course_id: int):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT *
            FROM student_answers sa
            JOIN tasks t ON sa.task_id = t.id
            JOIN lessons l ON t.lesson_id = l.id
            JOIN courses c ON l.course_id = c.course_id
            WHERE c.course_id = ? AND sa.verdict IS NULL
            ORDER BY sa.submission_date ASC
            LIMIT 1;
        ''', (course_id,))
        return cursor.fetchone()

def last_student_answer_all(developer_id: int):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        query = '''
            SELECT course_id
            FROM courses
            WHERE developers LIKE ?
        '''
        # Поиск всех курсов с данным developer_id
        cursor.execute(query, (f"%{developer_id}%",))
        courses = cursor.fetchall()

        if not courses:
            return "No courses found for this developer."

        # Шаг 2: Найти задания по этим курсам с непроверенными решениям
        query = '''
            SELECT *
            FROM student_answers sa
            JOIN tasks t ON sa.task_id = t.id
            JOIN lessons l ON t.lesson_id = l.id
            WHERE l.course_id IN ({})
            AND sa.verdict IS NULL
            ORDER BY sa.submission_date ASC
            LIMIT 1
        '''.format(','.join('?' * len(courses)))

        course_ids = [course[0] for course in courses]
        cursor.execute(query, course_ids)
        result = cursor.fetchone()

        if result:
            answer_id, task_id, student_id, answer_text, submission_date, files_id = result
            return {
                "answer_id": answer_id,
                "task_id": task_id,
                "student_id": student_id,
                "answer_text": answer_text,
                "submission_date": submission_date,
                "files_id": files_id
            }
        else:
            return None

def get_task_from_id(task_id):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        return cursor.fetchone()

def get_lesson_from_id(lesson_id):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM lessons WHERE id=?", (lesson_id,))
        return cursor.fetchone()

def get_student_answer_from_id(sa_id):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM student_answers WHERE id=?", (sa_id,))
        return cursor.fetchone()

def check_student_answer(verdict: str, comment: str | None, student_answer_id: int):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE student_answers SET verdict=? WHERE id=?", (verdict, student_answer_id))
        cursor.execute("UPDATE student_answers SET comment=? WHERE id=?", (comment, student_answer_id))

def create_lesson(course_id: int, name: str):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO lessons (course_id, title, status) VALUES (?, ?, ?)", (course_id, name, "open"))
        conn.commit()

def create_task(lesson_id: int, course_id: int, name: str, description: str):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO tasks (lesson_id, title, status, description) VALUES (?, ?, ?, ?)", (lesson_id, name, "open", description))
        conn.commit()

def bug_report(message: str):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO bug_reports (message, time) VALUES (?, ?)", (message, str(datetime.datetime.now())))
        conn.commit()

def log_action(executor_id: int, action: str, info: str):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO logs (executor_id, action, info) VALUES (?, ?, ?)", (executor_id, action, info))
        conn.commit()

def last_course_id():
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT course_id FROM courses ORDER BY course_id DESC LIMIT 1")
        return cursor.fetchone()[0]

def last_lesson_id():
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM lessons ORDER BY id DESC LIMIT 1")
        return cursor.fetchone()[0]

def last_task_id():
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM tasks ORDER BY id DESC LIMIT 1")
        return cursor.fetchone()[0]

def task_status_by_user(user_id: int, task_id: int, start_solution: int = 0):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("""SELECT verdict FROM student_answers
                        WHERE student_id=? AND task_id=?""", (user_id, task_id))
        verdicts = cursor.fetchall()
        verdicts = [i[0] for i in verdicts]
        if "accept" in verdicts:
            return "✅"
        elif None in verdicts:
            return "⌛️"
        elif "reject" in verdicts:
            return "❌"
        else:
            return ""

def get_course_from_lesson_id(lesson_id: int) -> int:
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("""SELECT course_id FROM lessons
                        WHERE id=?""", (lesson_id, ))
        course_id = cursor.fetchall()
        return int(course_id[0][0])

def all_users() -> list:
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("""SELECT user_id FROM users""")
        return cursor.fetchall()

def count_unchecked_solutions(course_id: int) -> int:
    conn = sqlite3.connect(config["db-name"])
    cursor = conn.cursor()

    cursor.execute('''
        SELECT COUNT(*) FROM student_answers
        WHERE task_id IN (
            SELECT id FROM tasks
            WHERE lesson_id IN (
                SELECT id FROM lessons WHERE course_id = ?
            )
        ) AND verdict IS NULL
    ''', (course_id,))

    count = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    return count

import sqlite3

def get_accessible_solutions(user_id):
    conn = sqlite3.connect(config["db-name"], check_same_thread=False)
    cursor = conn.cursor()
    
    # Получаем ID всех курсов, где пользователь является разработчиком
    cursor.execute("""
        SELECT course_id FROM courses
        WHERE developers LIKE ?
    """, (f'%{user_id}%',))
    
    course_ids = [row[0] for row in cursor.fetchall()]
    
    # Получаем ID всех задач из этих курсов
    if course_ids:
        cursor.execute(f"""
            SELECT tasks.id FROM tasks
            JOIN lessons ON tasks.lesson_id = lessons.id
            WHERE lessons.course_id IN ({','.join('?' * len(course_ids))})
        """, course_ids)
        task_ids = [row[0] for row in cursor.fetchall()]
    else:
        task_ids = []
    
    # Получаем все решения пользователя и его учеников
    query = """
        SELECT * FROM student_answers
        WHERE student_id = ?
    """
    params = [user_id]
    
    if task_ids:
        query += f" OR task_id IN ({','.join('?' * len(task_ids))})"
        params.extend(task_ids)
    
    cursor.execute(query, params)
    solutions = cursor.fetchall()
    
    # Сортируем по ID решений
    solutions.sort(key=lambda x: x[0])
    
    conn.close()
    return solutions

def self_reject(sol_id: int):
    conn = sqlite3.connect(config["db-name"])
    cursor = conn.cursor()

    cursor.execute('''
        UPDATE student_answers
        SET verdict = 'self_reject'
        WHERE id = ?
    ''', (sol_id,))

    # count = cursor.fetchone()[0]

    conn.commit()

    cursor.close()
    conn.close()

def undo_self_reject(sol_id: int):
    conn = sqlite3.connect(config["db-name"])
    cursor = conn.cursor()

    cursor.execute('''
        UPDATE student_answers
        SET verdict = NULL
        WHERE id = ?
    ''', (sol_id,))

    # count = cursor.fetchone()[0]

    conn.commit()

    cursor.close()
    conn.close()

def get_course_from_answer_id(answer_id: int) -> Optional[int]:
    conn = sqlite3.connect(config["db-name"], check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT courses.course_id
        FROM student_answers
        JOIN tasks ON student_answers.task_id = tasks.id
        JOIN lessons ON tasks.lesson_id = lessons.id
        JOIN courses ON lessons.course_id = courses.course_id
        WHERE student_answers.id = ?
    ''', (answer_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_lesson_from_answer_id(answer_id: int) -> Optional[int]:
    conn = sqlite3.connect(config["db-name"], check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT lessons.id
        FROM student_answers
        JOIN tasks ON student_answers.task_id = tasks.id
        JOIN lessons ON tasks.lesson_id = lessons.id
        WHERE student_answers.id = ?
    ''', (answer_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_task_from_answer_id(answer_id: int) -> Optional[int]:
    conn = sqlite3.connect(config["db-name"], check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT task_id FROM student_answers WHERE id = ?
    ''', (answer_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_course_name(course_id: int) -> Optional[str]:
    conn = sqlite3.connect(config["db-name"], check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT course_name FROM courses WHERE course_id = ?
    ''', (course_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_lesson_name(lesson_id: int) -> Optional[str]:
    conn = sqlite3.connect(config["db-name"], check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT title FROM lessons WHERE id = ?
    ''', (lesson_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_task_name(task_id: int) -> Optional[str]:
    conn = sqlite3.connect(config["db-name"], check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT title FROM tasks WHERE id = ?
    ''', (task_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def update_task_status(task_id: int):
    conn = sqlite3.connect(config["db-name"], check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT deadline FROM tasks WHERE id = ?
    ''', (task_id,))
    result = cursor.fetchone()
    conn.close()

    if result[0]:
        if datetime.datetime.now() > datetime.datetime.fromtimestamp(result[0] / 1000.0):
            conn = sqlite3.connect(config["db-name"], check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE tasks
                SET status = 'close'
                WHERE id = ?
            ''', (task_id,))
            conn.close()


def is_task_open(task_id: int) -> bool:
    update_task_status(task_id)
    conn = sqlite3.connect(config["db-name"], check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT status FROM tasks WHERE id = ?
    ''', (task_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] == "open"

if __name__ == "__main__":
    update_task_status(161)