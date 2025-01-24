import sql_return

def sort(list):
    print(list)
    return sorted(list, key=lambda x: (sql_return.get_user_name(int(x))[1], sql_return.get_user_name(int(x))[0]))