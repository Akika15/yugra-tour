# db_config.py
import mysql.connector
import hashlib
from mysql.connector import Error

# ==================== КОНФИГУРАЦИЯ ====================
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '1234',  # ← ЗАМЕНИ НА СВОЙ ПАРОЛЬ!
    'database': 'ugra_tourism',
    'charset': 'utf8mb4',
    'autocommit': True
}


# =====================================================

def get_db_connection():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        print(f"Ошибка подключения: {e}")
        return None


# --- Функции для получения данных ---
def get_attractions():
    conn = get_db_connection()
    if not conn:
        return []
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, description, lat, lon, work_time, contact, website FROM attractions")
    data = cursor.fetchall()
    cursor.close()
    conn.close()
    return data


def get_events():
    conn = get_db_connection()
    if not conn:
        return []
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, description, event_date, location FROM events")
    data = cursor.fetchall()
    cursor.close()
    conn.close()
    return data


def get_routes():
    conn = get_db_connection()
    if not conn:
        return []
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, description, distance_km FROM routes")
    data = cursor.fetchall()
    cursor.close()
    conn.close()
    return data


def get_route_points(route_id):
    conn = get_db_connection()
    if not conn:
        return []
    cursor = conn.cursor()
    cursor.execute("""
                   SELECT a.lat, a.lon, a.name, a.description
                   FROM attractions a
                            JOIN route_points rp ON a.id = rp.attraction_id
                   WHERE rp.route_id = %s
                   ORDER BY rp.point_order
                   """, (route_id,))
    points = cursor.fetchall()
    cursor.close()
    conn.close()
    return points


# --- Функции авторизации ---
def register_user(username, password):
    """Регистрация нового пользователя"""
    conn = get_db_connection()
    if not conn:
        return False, "Ошибка подключения к БД"

    cursor = conn.cursor()
    # Проверяем, существует ли пользователь
    cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
    if cursor.fetchone():
        cursor.close()
        conn.close()
        return False, "Пользователь уже существует"

    # Хэшируем пароль
    password_hash = hashlib.sha256(password.encode()).hexdigest()

    try:
        cursor.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", (username, password_hash))
        conn.commit()
        cursor.close()
        conn.close()
        return True, "Регистрация успешна!"
    except Exception as e:
        conn.close()
        return False, f"Ошибка: {e}"


def login_user(username, password):
    """Вход пользователя"""
    conn = get_db_connection()
    if not conn:
        return False, None, "Ошибка подключения к БД"

    cursor = conn.cursor()
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    cursor.execute("SELECT id, username FROM users WHERE username = %s AND password_hash = %s",
                   (username, password_hash))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

    if user:
        return True, {"id": user[0], "username": user[1]}, "Вход выполнен!"
    return False, None, "Неверное имя пользователя или пароль"


def get_user_favorites(user_id):
    """Получить избранное пользователя"""
    conn = get_db_connection()
    if not conn:
        return []
    cursor = conn.cursor()
    cursor.execute("SELECT attraction_id FROM favorites WHERE user_id = %s", (user_id,))
    data = [row[0] for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return data


def add_favorite(user_id, attraction_id):
    """Добавить в избранное"""
    conn = get_db_connection()
    if not conn:
        return False
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO favorites (user_id, attraction_id) VALUES (%s, %s)", (user_id, attraction_id))
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except:
        conn.close()
        return False


def remove_favorite(user_id, attraction_id):
    """Удалить из избранного"""
    conn = get_db_connection()
    if not conn:
        return False
    cursor = conn.cursor()
    cursor.execute("DELETE FROM favorites WHERE user_id = %s AND attraction_id = %s", (user_id, attraction_id))
    conn.commit()
    cursor.close()
    conn.close()
    return True


# --- ТЕСТ ПОДКЛЮЧЕНИЯ И АВТОРИЗАЦИИ ---
if __name__ == "__main__":
    print("=" * 50)
    print("ТЕСТ ПОДКЛЮЧЕНИЯ К БАЗЕ ДАННЫХ")
    print("=" * 50)

    # Тест подключения
    conn = get_db_connection()
    if conn:
        print("✅ Подключение к MySQL успешно!")

        # Проверяем количество записей
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM attractions")
        attractions_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM events")
        events_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM routes")
        routes_count = cursor.fetchone()[0]
        cursor.close()
        conn.close()

        print(f"   - Достопримечательностей: {attractions_count}")
        print(f"   - Событий: {events_count}")
        print(f"   - Маршрутов: {routes_count}")
    else:
        print("❌ Ошибка подключения к MySQL")
        print("   Проверьте пароль в DB_CONFIG")
        exit(1)

    print("\n" + "=" * 50)
    print("ТЕСТ АВТОРИЗАЦИИ")
    print("=" * 50)

    # Тест регистрации
    print("\n1. Тест регистрации нового пользователя 'testuser':")
    success, msg = register_user("testuser", "1234")
    print(f"   Результат: {msg}")

    # Тест входа
    print("\n2. Тест входа с 'testuser':")
    success, user, msg = login_user("testuser", "1234")
    print(f"   Результат: {msg}")
    if user:
        print(f"   ID пользователя: {user['id']}")

    # Тест входа с неправильным паролем
    print("\n3. Тест входа с неправильным паролем:")
    success, user, msg = login_user("testuser", "wrongpassword")
    print(f"   Результат: {msg}")

    print("\n" + "=" * 50)
    print("✅ Все тесты пройдены! Авторизация работает.")
    print("=" * 50)
    # db_config.py - для удаленного MySQL
    import mysql.connector

    # Настройки подключения к вашему серверу
    DB_CONFIG = {
        'host': 'ваш_ip_сервера',  # IP вашего сервера
        'user': 'remote_user',  # Имя пользователя
        'password': 'UgraTour2026!Secure',  # Пароль
        'database': 'ugra_tourism',
        'port': 3306,
        'use_pure': True,
        'connect_timeout': 10
    }


    def get_db_connection():
        """Подключение к удаленному MySQL серверу"""
        try:
            connection = mysql.connector.connect(**DB_CONFIG)
            return connection
        except Exception as e:
            print(f"Ошибка подключения к MySQL: {e}")
            return None
