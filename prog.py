import gspread
from gspread_formatting import *
from oauth2client.service_account import ServiceAccountCredentials
import time
import random
from gspread_formatting import format_cell_range, CellFormat, Color
import json
import sql_return

# Подключение к Google Таблице
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
client = gspread.authorize(creds)

# # Открываем таблицу по её названию (или можно по URL)
spreadsheet = client.open("Копия Математика Силаэдр 2024-25")

# # Выбираем лист (по умолчанию первый)
worksheet = spreadsheet.worksheet("7mp")

# # Читаем данные
data = worksheet.get_all_values()
data_dict = {}
for row_idx, row in enumerate(data):
    for col_idx, value in enumerate(row):
        col_letter = ""
        temp_col_idx = col_idx
        while temp_col_idx >= 0:
            col_letter = chr(65 + (temp_col_idx % 26)) + col_letter
            temp_col_idx = temp_col_idx // 26 - 1
        cell = f"{col_letter}{row_idx + 1}"
        data_dict[cell] = value

# Записываем данные
# worksheet.update([["Привет, мир!"]], "A1")
# worksheet.append_row(["Новая строка", 123, True])  # Добавить строку
# worksheet.acell("B2").value = "Пока, мир!"
# for i in ["A1", "B1", "C1", "A2", "B2", "C2", "A3", "B3", "C3"]:
#     worksheet.update([["{:08x}".format(random.randint(0, 2**32 - 1))]], i)
#     cell_format = CellFormat(backgroundColor=Color(red=random.random(), green=random.random(), blue=random.random()))
#     format_cell_range(worksheet, i, cell_format)
# cell = worksheet.acell("B2").value

# for i in ["CN10", "CQ10", "CQ11"]:
#     # worksheet.update([["{:08x}".format(random.randint(0, 2**32 - 1))]], i)
#     cell_format = CellFormat(backgroundColor=Color(red=191/256, green=149/256, blue=50/256))
#     format_cell_range(worksheet, i, cell_format)
#     time.sleep(2)
#     reset_format = CellFormat(backgroundColor=Color(red=1, green=1, blue=1))
#     format_cell_range(worksheet, i, reset_format)
# cell = worksheet.acell("B2").value
# print(cell)


# Найти строку по значению
# cell = worksheet.find("Новая строка")
# print(f"Нашёл в строке {cell.row}, колонке {cell.col}")

def update_sheet():
    start_solution = 0
    with open("setup.json", "r", encoding="utf-8") as file:
        setup = json.load(file)
    
    for i in setup.keys():
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
        client = gspread.authorize(creds)

        spreadsheet = client.open(setup[i]["spreadsheet"])

        worksheet = spreadsheet.worksheet(setup[i]["worksheet"])

        data = worksheet.get_all_values()
        data_dict = {}
        for row_idx, row in enumerate(data):
            for col_idx, value in enumerate(row):
                col_letter = ""
                temp_col_idx = col_idx
                while temp_col_idx >= 0:
                    col_letter = chr(65 + (temp_col_idx % 26)) + col_letter
                    temp_col_idx = temp_col_idx // 26 - 1
                cell = f"{col_letter}{row_idx + 1}"
                data_dict[cell] = value
        for j in setup[i]["users"].keys():
            if j == "":
                continue
            for k in setup[i]["tasks"].keys():
                if data_dict[f"{setup[i]['tasks'][k]}{setup[i]['users'][j]}"] == "1":
                    continue
                else:
                    status = sql_return.task_status_by_user(int(j), int(k), start_solution)
                    if status == "✅":
                        worksheet.update([["1"]], f"{setup[i]['tasks'][k]}{setup[i]['users'][j]}")
                        reset_format = CellFormat(backgroundColor=Color(red=132/256, green=163/256, blue=141/256))
                        format_cell_range(worksheet, f"{setup[i]['tasks'][k]}{setup[i]['users'][j]}", reset_format)
                    elif status == "⌛️":
                        reset_format = CellFormat(backgroundColor=Color(red=166/256, green=152/256, blue=111/256))
                        format_cell_range(worksheet, f"{setup[i]['tasks'][k]}{setup[i]['users'][j]}", reset_format)
                    elif status == "❌":
                        reset_format = CellFormat(backgroundColor=Color(red=1, green=1, blue=1))
                        format_cell_range(worksheet, f"{setup[i]['tasks'][k]}{setup[i]['users'][j]}", reset_format)
                if f"{setup[i]['tasks'][k]}{setup[i]['users'][j]}" == "GM14":
                    print(f"{setup[i]['tasks'][k]}{setup[i]['users'][j]}: {data_dict[f"{setup[i]['tasks'][k]}{setup[i]['users'][j]}"]}, {sql_return.task_status_by_user(int(j), int(k), start_solution)}")
    

update_sheet()
