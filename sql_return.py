import sqlite3
import json

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
                    user_id, first_name, second_name, status)
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
        cursor.execute("SELECT * FROM users WHERE user_id=?", (call.from_user.id,))
        user = cursor.fetchone()
        return str(user_id) in devs_id.split()

def get_user_name(user_id):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT first_name, last_name FROM users WHERE user_id=?", (int(user_id),))
        user = cursor.fetchone()

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
        try:
            cursor.execute("UPDATE courses SET student_id=? WHERE course_id=?", (new_students_list, course_id))
            conn.commit()
        except:
            pass

def try_add_developer_to_course(course_id, new_developer_list):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE courses SET developers=? WHERE course_id=?", (new_developer_list, course_id))
            conn.commit()
        except:
            pass 

def create_course(cre_cur_name, user_id, cre_courses):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO courses (course_name, creator_id, developers) VALUES (?, ?, ?)",
            (cre_cur_name, user_id, " ".join([str(i) for i in cre_courses[user_id][0]])))
        conn.commit()

def lessons_in_course(course_id):
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM lessons WHERE course_id=?", (course_id,))
        return cursor.fetchall()