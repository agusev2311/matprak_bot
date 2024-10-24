import sqlite3
import json
import datetime
import os

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
            submission_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            verdict TEXT,           -- Вердикт преподавателя
            comment TEXT,           -- Комментарий к вердикту
            FOREIGN KEY(task_id) REFERENCES tasks(id),
            FOREIGN KEY(student_id) REFERENCES users(user_id)
        );
    ''')

    # Verdict:
    # accepted
    # rejected
    
    conn.commit()
    cursor.close()

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
    
def is_course_dev(user_id, devs_id):
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

def create_course(cre_cur_name: str, user_id: int, cre_courses):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO courses (course_name, creator_id, developers) VALUES (?, ?, ?)",
            (cre_cur_name, user_id, " ".join([str(i) for i in cre_courses[user_id][0]])))
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
    
def new_student_answer(task_id: int, student_id: int, answer_text: str):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO student_answers (task_id, student_id, answer_text, submission_date, verdict, comment) VALUES (?, ?, ?, ?, ?, ?)",
                       (task_id, student_id, answer_text, str(datetime.datetime.now()), None, None))  # Здесь кортеж
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
            SELECT sa.id, sa.task_id, sa.student_id, sa.answer_text, sa.submission_date
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

        # Шаг 2: Найти задания по этим курсам с непроверенными решениями
        query = '''
            SELECT sa.id, sa.task_id, sa.student_id, sa.answer_text, sa.submission_date
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
            answer_id, task_id, student_id, answer_text, submission_date = result
            return {
                "answer_id": answer_id,
                "task_id": task_id,
                "student_id": student_id,
                "answer_text": answer_text,
                "submission_date": submission_date
            }
        else:
            return "No unchecked answers found."

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