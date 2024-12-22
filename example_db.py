import sqlite3
import json
import os
import sql_return
import time

config = json.load(open("config.json"))

print("Do you really want to remove the database? (y/n) (\"a\" to automatically setup)")

if input() == "y" or input() == "a":
    if os.path.exists(config["db-name"]):
        os.remove(config["db-name"])
        print(f"Old database at {config['db-name']} has been removed.")
    else:
        print(f"No database found at {config['db-name']} to remove.")
else:
    print("Enter the new name of the old db")
    nn = input()
    os.rename(config["db-name"], nn)
    print(f"Old database at {config['db-name']} has been renamed to {nn}")

sql_return.init_db()
sql_return.reg_user(1133611562, "Артём", "Гусев", "approved")
sql_return.create_course("Example course", 1133611562, "1133611562")
sql_return.create_lesson(1, "Example lesson 1")
sql_return.create_lesson(1, "Example lesson 2")
sql_return.create_task(1, 1, "Example task 1", "Example task description 1")
sql_return.create_task(1, 1, "Example task 2", "Example task description 2")
sql_return.create_task(1, 1, "Example task 3", "Example task description 3")
sql_return.create_task(1, 1, "Example task 4", "Example task description 4")
sql_return.create_task(2, 1, "Example task 5", "Example task description 5")
sql_return.create_task(2, 1, "Example task 6", "Example task description 6")
sql_return.create_task(2, 1, "Example task 7", "Example task description 7")
sql_return.create_task(2, 1, "Example task 8", "Example task description 8")

reg_users = [1133611562]

while True:
    with sqlite3.connect(config["db-name"]) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        users = cursor.fetchall()

        # for user in users:
        #     user_data = sql_return.find_user_id(user[0])
        #     if user_data and user_data[3] != "approved":
        #         sql_return.set_user_status(user[0], "approved")
        #         print(f"User {user[0]} has been approved.")

        print(users)
        
        cursor.execute("SELECT student_id FROM courses WHERE course_id=1")
        course_students = cursor.fetchone()[0]
        
        if course_students:
            course_students_list = course_students.split()
        else:
            course_students_list = []
        print(course_students_list)

        for user in users:
            if str(user[0]) not in course_students_list and user[0] != 1133611562:
                sql_return.try_add_student_to_course(1, user[0])
                print(f"User {user[0]} added to course 1")
            if (not user[0] in reg_users) and user[0] != 1133611562:
                reg_users.append(user[0])
                if len(reg_users) == 2:
                    sql_return.create_course("Example course", reg_users[1], f"{reg_users[1]}")
                    sql_return.create_lesson(2, "Example lesson 1")
                    sql_return.create_lesson(2, "Example lesson 2")
                    sql_return.create_task(3, 2, "Example task 1", "Example task description 1")
                    sql_return.create_task(3, 2, "Example task 2", "Example task description 2")
                    sql_return.create_task(3, 2, "Example task 3", "Example task description 3")
                    sql_return.create_task(3, 2, "Example task 4", "Example task description 4")
                    sql_return.create_task(4, 2, "Example task 5", "Example task description 5")
                    sql_return.create_task(4, 2, "Example task 6", "Example task description 6")
                    sql_return.create_task(4, 2, "Example task 7", "Example task description 7")
                    sql_return.create_task(4, 2, "Example task 8", "Example task description 8")
                    sql_return.try_add_student_to_course(2, reg_users[0])
                else:
                    sql_return.try_add_developer_to_course(2, reg_users[-1])
                
    time.sleep(10)
