import sqlite3
from PIL import Image, ImageDraw, ImageFont
import sql_return

font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

def generate_lesson_table(db_path, lesson_id, course_id, output_path="table.png"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT user_id, first_name, last_name FROM users")
    all_students = cursor.fetchall()

    cursor.execute("SELECT student_id FROM courses WHERE course_id = ?", (course_id))
    students = cursor.fetchall()
    students_2 = []

    for i in students[0][0].split():
        students_2.append([i, sql_return.get_user_name(i)[0], sql_return.get_user_name(i)[1]])
        
    cursor.execute("SELECT id, title FROM tasks WHERE lesson_id = ?", (lesson_id,))
    tasks = cursor.fetchall()

    cursor.execute("""
        SELECT student_id, task_id, verdict
        FROM student_answers
        WHERE task_id IN (SELECT id FROM tasks WHERE lesson_id = ?)
    """, (lesson_id,))
    answers = cursor.fetchall()
    
    conn.close()

    student_results = {int(student[0]): {task[0]: "white" for task in tasks} for student in students_2}
    
    for student_id, task_id, verdict in answers:
        if verdict == "accept":
            student_results[student_id][task_id] = "green"
        elif verdict == "reject" and student_results[student_id][task_id] != "green":
            student_results[student_id][task_id] = "red"
        elif verdict is None and student_results[student_id][task_id] not in ["green", "red"]:
            student_results[student_id][task_id] = "yellow"
    
    cell_size = 50
    padding = 10
    font_size = 25
    font = ImageFont.truetype(font_path, font_size)
    
    max_name_width = max(font.getbbox(f"{student[1]} {student[2]}")[2] for student in students_2) + 10
    name_column_width = max(cell_size, max_name_width)
    
    img_width = name_column_width + (len(tasks) * cell_size) + padding * 2
    img_height = (len(students_2) + 1) * cell_size + padding * 2
    
    img = Image.new("RGB", (img_width, img_height), "white")
    draw = ImageDraw.Draw(img)
    
    for j, task in enumerate(tasks):
        draw.text((padding + name_column_width + (j * cell_size) + 5, padding + 5), task[1][:3], fill="black", font=font)

    for i, student in enumerate(students_2):
        draw.text((padding, padding + (i + 1) * cell_size + 5), f"{student[1]} {student[2]}", fill="black", font=font)
        
        for j, task in enumerate(tasks):
            color = student_results[int(student[0])][task[0]]
            x1, y1 = padding + name_column_width + (j * cell_size), padding + (i + 1) * cell_size
            x2, y2 = x1 + cell_size, y1 + cell_size
            draw.rectangle([x1, y1, x2, y2], fill=color, outline="black")
            draw.line([0, y1, x2, y2 - 50], fill="black")
            draw.line([x1, y1 + 50, 0, y2], fill="black")
    
    img.save(output_path)

inp = input()
generate_lesson_table("users.db", lesson_id=int(inp), course_id=f"{sql_return.get_course_from_lesson_id(int(inp))}", output_path="lesson_table.png")
