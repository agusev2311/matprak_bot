import sqlite3
import psycopg2
from psycopg2 import sql
import json
import datetime
import os

with open('config.json', 'r') as file:
    config = json.load(file)

def get_db_connection():
    return psycopg2.connect(
        dbname=config["database"]["dbname"],
        user=config["database"]["user"],
        password=config["database"]["password"],
        host=config["database"]["host"],
        port=config["database"]["port"]
    )

def init_db():
    conn = get_db_connection()
    
    with conn.cursor() as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id SERIAL PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                status TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS lessons (
                id SERIAL PRIMARY KEY,
                course_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                open_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(course_id) REFERENCES courses(course_id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
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
                course_id SERIAL PRIMARY KEY,
                course_name TEXT,
                creator_id INTEGER,
                student_id TEXT,
                developers TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS student_answers (
                id SERIAL PRIMARY KEY,
                task_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                answer_text TEXT,
                files_id TEXT,
                submission_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                verdict TEXT,
                comment TEXT,
                FOREIGN KEY(task_id) REFERENCES tasks(id),
                FOREIGN KEY(student_id) REFERENCES users(user_id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bug_reports (
                id SERIAL PRIMARY KEY,
                message TEXT,
                time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id SERIAL PRIMARY KEY,
                executor_id INTEGER,
                action TEXT,
                time TIMESTAMP DEFAULT NOW(),
                info TEXT
            )
        ''')
        
        conn.commit()
    
    conn.close()

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
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
            return cursor.fetchone()

def reg_user(user_id, first_name, second_name, status="pending"):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO users (user_id, first_name, last_name, status) VALUES (%s, %s, %s, %s)",
                        (user_id, first_name, second_name, status))
            return cursor.fetchone()

def set_user_status(user_id, status):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE users SET status=%s WHERE user_id=%s", (status, user_id))
            conn.commit()

def delete_user(user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM users WHERE user_id=%s", (user_id,))
            conn.commit()

def all_courses():
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM courses")
            return cursor.fetchall()

def find_course_id(course_id):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM courses WHERE course_id=%s", (course_id,))
            return cursor.fetchone()

def is_course_dev(user_id: int, devs_id: str) -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
            user = cursor.fetchone()
            return str(user_id) in devs_id.split()

def get_user_name(user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT first_name, last_name FROM users WHERE user_id=%s", (int(user_id),))
            return cursor.fetchone()

def students_list(course_id):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT student_id FROM courses WHERE course_id=%s", (course_id,))
            result = cursor.fetchone()
            return result[0] if result else ""

def developers_list(course_id):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT developers FROM courses WHERE course_id=%s", (course_id,))
            result = cursor.fetchone()
            return result[0] if result else ""

def try_add_student_to_course(course_id, new_students_list):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE courses SET student_id=%s WHERE course_id=%s", (new_students_list, course_id))
            conn.commit()

def try_add_developer_to_course(course_id, new_developer_list):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE courses SET developers=%s WHERE course_id=%s", (new_developer_list, course_id))
            conn.commit()

def create_course(cre_cur_name: str, user_id: int, developers: str):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO courses (course_name, creator_id, developers) VALUES (%s, %s, %s)",
                (cre_cur_name, user_id, developers))
            conn.commit()

def lessons_in_course(course_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM lessons WHERE course_id=%s", (course_id,))
            return cursor.fetchall()

def tasks_in_lesson(lesson_id):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM tasks WHERE lesson_id=%s", (lesson_id,))
            return cursor.fetchall()

def task_info(task_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM tasks WHERE id=%s", (task_id,))
            return cursor.fetchone()
    
def new_student_answer(task_id: int, student_id: int, answer_text: str, files_id: str = None):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO student_answers (task_id, student_id, answer_text, submission_date, verdict, comment, files_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (task_id, student_id, answer_text, str(datetime.datetime.now()), None, None, files_id))
            conn.commit()

def next_name(dir: str) -> str:
    files = os.listdir(dir)
    new_files = [i.split(".")[0] for i in files]
    i = 0
    while True:
        numb = hex(i)[2:]
        if numb not in new_files:
            break
        i += 1
    return hex(i)[2:]

def save_photo(downloaded_file):
    save_path = f'files/{next_name("files")}.jpg'
    with open(save_path, 'wb') as new_file:
        new_file.write(downloaded_file)

def last_student_answer_course(course_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT *
                FROM student_answers sa
                JOIN tasks t ON sa.task_id = t.id
                JOIN lessons l ON t.lesson_id = l.id
                JOIN courses c ON l.course_id = c.course_id
                WHERE c.course_id = %s AND sa.verdict IS NULL
                ORDER BY sa.submission_date ASC
                LIMIT 1;
            """, (course_id,))
            return cursor.fetchone()

def last_student_answer_all(developer_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT course_id
                FROM courses
                WHERE developers LIKE %s
            """, (f"%{developer_id}%",))
            courses = cursor.fetchall()

            if not courses:
                return "No courses found for this developer."

            cursor.execute("""
                SELECT *
                FROM student_answers sa
                JOIN tasks t ON sa.task_id = t.id
                JOIN lessons l ON t.lesson_id = l.id
                WHERE l.course_id IN (%s)
                AND sa.verdict IS NULL
                ORDER BY sa.submission_date ASC
                LIMIT 1
            """, tuple(course[0] for course in courses))
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
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM tasks WHERE id=%s", (task_id,))
            return cursor.fetchone()

def get_lesson_from_id(lesson_id):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM lessons WHERE id=%s", (lesson_id,))
            return cursor.fetchone()

def get_student_answer_from_id(sa_id):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM student_answers WHERE id=%s", (sa_id,))
            return cursor.fetchone()

def check_student_answer(verdict: str, comment: str, student_answer_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE student_answers SET verdict=%s WHERE id=%s", (verdict, student_answer_id))
            cursor.execute("UPDATE student_answers SET comment=%s WHERE id=%s", (comment, student_answer_id))
            conn.commit()

def create_lesson(course_id: int, name: str):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO lessons (course_id, title, status) VALUES (%s, %s, %s)", (course_id, name, "open"))
            conn.commit()

def create_task(lesson_id: int, course_id: int, name: str, description: str):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO tasks (lesson_id, title, status, description) VALUES (%s, %s, %s, %s)", (lesson_id, name, "open", description))
            conn.commit()

def bug_report(message: str):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO bug_reports (message, time) VALUES (%s, %s)", (message, str(datetime.datetime.now())))
            conn.commit()

def log_action(executor_id: int, action: str, info: str):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO logs (executor_id, action, info) VALUES (%s, %s, %s)", (executor_id, action, info))
            conn.commit()

def last_course_id():
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT course_id FROM courses ORDER BY course_id DESC LIMIT 1")
            return cursor.fetchone()[0]

def last_lesson_id():
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM lessons ORDER BY id DESC LIMIT 1")
            return cursor.fetchone()[0]

def last_task_id():
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM tasks ORDER BY id DESC LIMIT 1")
            return cursor.fetchone()[0]

def task_status_by_user(user_id: int, task_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT verdict 
                FROM student_answers 
                WHERE student_id=%s AND task_id=%s
            """, (user_id, task_id))
            verdicts = [i[0] for i in cursor.fetchall()]
            if "accept" in verdicts:
                return "✅"
            elif None in verdicts:
                return "⌛️"
            elif "reject" in verdicts:
                return "❌"
            else:
                return "⬜️"

def get_course_from_lesson_id(lesson_id: int) -> int:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT course_id FROM lessons 
                WHERE id=%s
            """, (lesson_id,))
            course_id = cursor.fetchall()
            return int(course_id[0][0])
    
def all_users() -> list:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""SELECT user_id FROM users""")
            return cursor.fetchall()

def count_unchecked_solutions(course_id: int) -> int:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) FROM student_answers
                WHERE task_id IN (
                    SELECT id FROM tasks
                    WHERE lesson_id IN (
                        SELECT id FROM lessons WHERE course_id = %s
                    )
                ) AND verdict IS NULL
            """, (course_id,))
            count = cursor.fetchone()[0]
            return count
