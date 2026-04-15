import flet as ft
import folium
import tempfile
import webbrowser
import os
import requests
import json
from datetime import datetime, date
import threading
import time
import hashlib
from math import atan2, degrees, pi
import sqlite3
from pathlib import Path
from decimal import Decimal
import random
from functools import lru_cache
import platform

# Подключение к MySQL
from db_config import get_db_connection

# ==================== КОНФИГУРАЦИЯ ====================
CENTER_LAT = 61.0056
CENTER_LON = 69.0282

# Бесплатные OSRM серверы
OSRM_SERVERS = [
    "https://routing.openstreetmap.de",
    "https://router.project-osrm.org",
    "https://routing.terrestris.de"
]

# Реалистичные скорости (км/ч)
WALKING_SPEED = 5
DRIVING_SPEED = 40

# Настройки кэша
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)
CACHE_DB_PATH = CACHE_DIR / "offline_cache.db"
CACHE_EXPIRY_DAYS = 7

# Цветовая схема
LIGHT_GREEN_BG = "#E8F5E9"
DARK_GREEN = "#2E7D32"
BRIGHT_BLUE = "#1976D2"
LIGHT_BLUE = "#64B5F6"
SNOW_WHITE = "#FFFFFF"
PINE_BROWN = "#8D6E63"
BERRIES_RED = "#EF5350"
DEEP_BLUE = "#1565C0"

# Эмодзи животных
TAIGA_ANIMALS = ["🐻", "🐺", "🦊", "🦌", "🐿️", "🦅", "🐇", "🦋"]


# =====================================================

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ СЕРИАЛИЗАЦИИ ---
def convert_to_serializable(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, date):
        return obj.isoformat()
    elif isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, tuple):
        return tuple(convert_to_serializable(item) for item in obj)
    elif isinstance(obj, list):
        return [convert_to_serializable(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: convert_to_serializable(value) for key, value in obj.items()}
    return obj


# --- КЛАСС ДЛЯ OFFLINE-КЭША ---
class OfflineCache:
    def __init__(self):
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(CACHE_DB_PATH)
        cursor = conn.cursor()

        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS cache_data
                       (
                           key
                           TEXT
                           PRIMARY
                           KEY,
                           data
                           TEXT,
                           timestamp
                           REAL,
                           expiry_days
                           INTEGER
                       )
                       ''')

        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS favorites
                       (
                           attraction_id
                           INTEGER
                           PRIMARY
                           KEY,
                           timestamp
                           REAL
                       )
                       ''')

        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS stats
                       (
                           key
                           TEXT
                           PRIMARY
                           KEY,
                           value
                           TEXT,
                           timestamp
                           REAL
                       )
                       ''')

        conn.commit()
        conn.close()

    def get(self, key):
        conn = sqlite3.connect(CACHE_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT data, timestamp, expiry_days FROM cache_data WHERE key = ?", (key,))
        result = cursor.fetchone()
        conn.close()

        if result:
            data, timestamp, expiry_days = result
            if expiry_days and (time.time() - timestamp) > (expiry_days * 86400):
                return None
            try:
                return json.loads(data)
            except:
                return None
        return None

    def set(self, key, data, expiry_days=CACHE_EXPIRY_DAYS):
        try:
            serializable_data = convert_to_serializable(data)
            conn = sqlite3.connect(CACHE_DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO cache_data (key, data, timestamp, expiry_days) VALUES (?, ?, ?, ?)",
                (key, json.dumps(serializable_data, ensure_ascii=False), time.time(), expiry_days)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Ошибка сохранения в кэш: {e}")

    def clear_expired(self):
        conn = sqlite3.connect(CACHE_DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM cache_data WHERE expiry_days IS NOT NULL AND (timestamp + (expiry_days * 86400)) < ?",
            (time.time(),))
        conn.commit()
        conn.close()

    def get_favorites(self):
        conn = sqlite3.connect(CACHE_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT attraction_id FROM favorites ORDER BY timestamp DESC")
        favorites = [row[0] for row in cursor.fetchall()]
        conn.close()
        return favorites

    def add_favorite(self, attraction_id):
        conn = sqlite3.connect(CACHE_DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO favorites (attraction_id, timestamp) VALUES (?, ?)",
            (attraction_id, time.time())
        )
        conn.commit()
        conn.close()

    def remove_favorite(self, attraction_id):
        conn = sqlite3.connect(CACHE_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM favorites WHERE attraction_id = ?", (attraction_id,))
        conn.commit()
        conn.close()

    def update_stat(self, key, value):
        conn = sqlite3.connect(CACHE_DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO stats (key, value, timestamp) VALUES (?, ?, ?)",
            (key, str(value), time.time())
        )
        conn.commit()
        conn.close()

    def get_stat(self, key):
        conn = sqlite3.connect(CACHE_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM stats WHERE key = ?", (key,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None


cache = OfflineCache()


# --- ФУНКЦИИ ДЛЯ ПРОВЕРКИ СОЕДИНЕНИЯ ---
@lru_cache(maxsize=1)
def is_online():
    try:
        requests.get("https://www.google.com", timeout=2)
        return True
    except:
        return False


# --- ФУНКЦИИ ДЛЯ ЗАГРУЗКИ ДАННЫХ С КЭШИРОВАНИЕМ ---
def get_attractions_with_cache(force_refresh=False):
    cache_key = "attractions"
    if force_refresh or is_online():
        try:
            data = get_attractions()
            if data:
                serializable_data = convert_to_serializable(data)
                cache.set(cache_key, serializable_data)
                return data
        except Exception as e:
            print(f"Ошибка загрузки с сервера: {e}")
    cached_data = cache.get(cache_key)
    if cached_data:
        return [tuple(item) if isinstance(item, list) else item for item in cached_data]
    return []


def get_events_with_cache(force_refresh=False):
    cache_key = "events"
    if force_refresh or is_online():
        try:
            data = get_events()
            if data:
                serializable_data = convert_to_serializable(data)
                cache.set(cache_key, serializable_data)
                return data
        except Exception as e:
            print(f"Ошибка загрузки с сервера: {e}")
    cached_data = cache.get(cache_key)
    if cached_data:
        return [tuple(item) if isinstance(item, list) else item for item in cached_data]
    return []


def get_routes_with_cache(force_refresh=False):
    cache_key = "routes"
    if force_refresh or is_online():
        try:
            data = get_routes()
            if data:
                serializable_data = convert_to_serializable(data)
                cache.set(cache_key, serializable_data)
                return data
        except Exception as e:
            print(f"Ошибка загрузки с сервера: {e}")
    cached_data = cache.get(cache_key)
    if cached_data:
        return [tuple(item) if isinstance(item, list) else item for item in cached_data]
    return []


def get_route_points_with_cache(route_id, force_refresh=False):
    cache_key = f"route_points_{route_id}"
    print(f"Загрузка точек маршрута {route_id} из кэша...")

    if force_refresh or is_online():
        try:
            data = get_route_points(route_id)
            if data:
                print(f"Загружено {len(data)} точек из БД")
                serializable_data = convert_to_serializable(data)
                cache.set(cache_key, serializable_data)
                return data
            else:
                print(f"Точки для маршрута {route_id} не найдены в БД")
        except Exception as e:
            print(f"Ошибка загрузки с сервера: {e}")

    cached_data = cache.get(cache_key)
    if cached_data:
        print(f"Загружено {len(cached_data)} точек из кэша")
        return [tuple(item) if isinstance(item, list) else item for item in cached_data]

    print(f"Точки для маршрута {route_id} не найдены нигде")
    return []


# --- ФУНКЦИИ ДЛЯ РАБОТЫ С БД ---
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
    print(f"Прямой запрос точек для маршрута {route_id} из MySQL...")
    conn = get_db_connection()
    if not conn:
        print("Нет подключения к БД")
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
    print(f"Найдено {len(points)} точек")
    cursor.close()
    conn.close()

    # Если точек нет, создаем тестовые на основе доступных достопримечательностей
    if len(points) == 0:
        print(f"⚠️ Для маршрута {route_id} нет точек, создаем тестовые...")
        conn2 = get_db_connection()
        if conn2:
            cursor2 = conn2.cursor()
            cursor2.execute(
                "SELECT id, name, description, lat, lon, work_time, contact, website FROM attractions LIMIT 5")
            all_attractions = cursor2.fetchall()
            cursor2.close()
            conn2.close()

            if all_attractions:
                points = []
                for i, attr in enumerate(all_attractions[:5]):
                    points.append((attr[3], attr[4], attr[1], attr[2]))
                print(f"Создано {len(points)} тестовых точек")

    return points


# --- Функция для получения погоды с иконкой ---
def get_weather_icon(weather_code, is_day=1):
    weather_icons = {
        0: ("☀️", "Ясно", "sunny"),
        1: ("🌤️", "Малооблачно", "partly_cloudy"),
        2: ("⛅", "Облачно", "cloudy"),
        3: ("☁️", "Пасмурно", "overcast"),
        45: ("🌫️", "Туман", "fog"),
        51: ("🌧️", "Морось", "drizzle"),
        61: ("🌧️", "Дождь", "rain"),
        63: ("🌧️", "Сильный дождь", "heavy_rain"),
        71: ("❄️", "Снег", "snow"),
        73: ("❄️", "Сильный снег", "heavy_snow"),
        95: ("⛈️", "Гроза", "thunderstorm")
    }
    return weather_icons.get(weather_code, ("🌡️", "Неизвестно", "unknown"))


# Кэш для погоды
weather_cache = {}
weather_cache_time = {}


def get_weather_data_fast(lat, lon):
    cache_key = f"{lat}_{lon}"

    if cache_key in weather_cache and (time.time() - weather_cache_time.get(cache_key, 0)) < 1800:
        return weather_cache[cache_key]

    default_weather = {'temp': 'N/A', 'windspeed': 'N/A', 'icon': '🌡️', 'description': 'Загрузка...'}

    def load_weather():
        if is_online():
            try:
                url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&timezone=auto"
                response = requests.get(url, timeout=3)
                if response.status_code == 200:
                    data = response.json()
                    current = data.get('current_weather', {})
                    temp = current.get('temperature', 'N/A')
                    windspeed = current.get('windspeed', 'N/A')
                    weathercode = current.get('weathercode', 0)
                    icon, description, icon_name = get_weather_icon(weathercode)
                    weather_data = {'temp': temp, 'windspeed': windspeed, 'icon': icon, 'description': description}
                    weather_cache[cache_key] = weather_data
                    weather_cache_time[cache_key] = time.time()
            except:
                pass

    threading.Thread(target=load_weather, daemon=True).start()
    return default_weather


# --- Построение маршрута через OSRM (сокращенный путь) ---
def build_osrm_route_fast(waypoints, profile='foot'):
    """Быстрое построение маршрута с кэшем и сокращенным путем"""
    if not waypoints or len(waypoints) < 2:
        print("Недостаточно точек для построения маршрута")
        return {'success': False, 'coords': waypoints, 'distance_km': 0, 'duration_min': 0, 'offline': False}

    cache_key = f"route_{profile}_{hash(str(waypoints))}"
    cached_route = cache.get(cache_key)
    if cached_route:
        print(f"Маршрут найден в кэше")
        return cached_route

    if not is_online():
        print("Оффлайн режим, возвращаем прямую линию")
        short_waypoints = [waypoints[0], waypoints[-1]]
        return {
            'success': True,
            'coords': short_waypoints,
            'distance_km': 0,
            'duration_min': 0,
            'offline': True
        }

    try:
        if profile == 'foot':
            osrm_profile = 'foot'
        else:
            osrm_profile = 'driving'

        # Для сокращения маршрута берем только ключевые точки
        if len(waypoints) > 4:
            reduced_waypoints = [waypoints[0]]
            for i in range(2, len(waypoints) - 1, 2):
                reduced_waypoints.append(waypoints[i])
            reduced_waypoints.append(waypoints[-1])
        else:
            reduced_waypoints = waypoints

        # Формируем строку координат
        coords_str = ';'.join([f"{lon},{lat}" for lat, lon in reduced_waypoints])
        print(f"Координаты для OSRM (сокращенные: {len(reduced_waypoints)} точек): {coords_str}")

        for server in OSRM_SERVERS:
            try:
                url = f"{server}/route/v1/{osrm_profile}/{coords_str}?overview=full&geometries=geojson&steps=false&alternatives=false"
                print(f"Запрос к OSRM: {url}")
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('code') == 'Ok' and data.get('routes'):
                        route = data['routes'][0]
                        geometry = route['geometry']['coordinates']
                        full_coords = [[coord[1], coord[0]] for coord in geometry]
                        simplified_coords = []
                        for i in range(0, len(full_coords), 5):
                            simplified_coords.append(full_coords[i])
                        if full_coords[-1] not in simplified_coords:
                            simplified_coords.append(full_coords[-1])

                        distance_km = route['distance'] / 1000

                        if profile == 'foot':
                            duration_hours = distance_km / WALKING_SPEED
                        else:
                            duration_hours = distance_km / DRIVING_SPEED

                        duration_min = round(duration_hours * 60)

                        result = {
                            'success': True,
                            'coords': simplified_coords,
                            'distance_km': round(distance_km, 1),
                            'duration_min': duration_min,
                            'offline': False
                        }

                        cache.set(cache_key, result, expiry_days=30)
                        print(
                            f"Маршрут построен: {distance_km} км, {duration_min} мин (упрощено: {len(simplified_coords)} точек)")
                        return result
            except Exception as e:
                print(f"Ошибка с сервером {server}: {e}")
                continue

        print("Все серверы недоступны")
        return {'success': False, 'coords': waypoints, 'distance_km': 0, 'duration_min': 0, 'offline': False}
    except Exception as e:
        print(f"Ошибка OSRM: {e}")
        return {'success': False, 'coords': waypoints, 'distance_km': 0, 'duration_min': 0, 'offline': False}


# --- Функция для добавления стрелок направления ---
def add_direction_arrows(m, route_coords, color='blue'):
    arrow_spacing = 20
    if len(route_coords) <= arrow_spacing:
        return
    for i in range(0, len(route_coords) - arrow_spacing, arrow_spacing):
        if i + arrow_spacing < len(route_coords):
            p1 = route_coords[i]
            p2 = route_coords[i + arrow_spacing // 2]
            dx = p2[1] - p1[1]
            dy = p2[0] - p1[0]
            angle = degrees(atan2(dx, dy))
            mid_lat = (p1[0] + p2[0]) / 2
            mid_lon = (p1[1] + p2[1]) / 2
            arrow_html = f'<div style="transform: rotate({angle}deg); font-size: 20px; color: {color};">▶</div>'
            folium.Marker(
                location=[mid_lat, mid_lon],
                icon=folium.DivIcon(html=arrow_html, icon_size=(20, 20)),
                popup='Направление движения'
            ).add_to(m)


# --- Функция создания HTML карты ---
def create_map_html(center_lat=CENTER_LAT, center_lon=CENTER_LON, zoom=12, route_coords=None,
                    highlight_attraction=None, route_color='green', start_name="СТАРТ", end_name="ФИНИШ",
                    duration_min=0, distance_km=0, transport_type="пешком", map_mode='info'):
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=zoom,
        control_scale=True,
        tiles='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        attr='© OpenStreetMap contributors'
    )
    attractions = get_attractions_with_cache()
    for attr in attractions:
        is_highlight = highlight_attraction and attr[1] == highlight_attraction
        if map_mode == 'info':
            popup_text = f"""
            <div style="font-family: Arial; min-width: 300px;">
                <b style="color: #2E7D32; font-size: 16px;">🏛️ {attr[1]}</b><br>
                <hr style="margin: 5px 0;">
                <small>{attr[2] if attr[2] else 'Описание отсутствует'}</small><br><br>
                <small>🕒 {attr[5] if attr[5] else 'Часы не указаны'}</small><br>
                <small>📞 {attr[6] if attr[6] else 'Телефон не указан'}</small><br>
                <small>🌐 <a href='{attr[7] if attr[7] else "#"}' target='_blank'>Сайт</a></small>
            </div>
            """
            icon_color = 'red' if is_highlight else 'blue'
            folium.Marker(
                location=[attr[3], attr[4]],
                popup=folium.Popup(popup_text, max_width=350),
                tooltip=f"📍 {attr[1]}",
                icon=folium.Icon(color=icon_color, icon='circle', prefix='fa')
            ).add_to(m)
        else:
            weather = get_weather_data_fast(attr[3], attr[4])
            popup_text = f"""
            <div style="font-family: Arial; min-width: 260px;">
                <b style="color: #2E7D32; font-size: 16px;">🏛️ {attr[1]}</b><br>
                <hr style="margin: 5px 0;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span style="font-size: 32px;">{weather['icon']}</span>
                    <div><b>{weather['temp']}°C</b><br><small>{weather['description']}</small></div>
                </div>
                <small>💨 Ветер: {weather['windspeed']} км/ч</small><br>
                <small>🕒 {attr[5] if attr[5] else 'Часы не указаны'}</small>
            </div>
            """
            icon_color = 'red' if is_highlight else 'green'
            weather_html = f'''
            <div style="background:white;border-radius:20px;padding:4px 10px;border:2px solid {icon_color};font-size:14px;font-weight:bold;white-space:nowrap;">
                {weather['icon']} {weather['temp']}°C
            </div>
            '''
            folium.Marker(
                location=[attr[3], attr[4]],
                popup=folium.Popup(popup_text, max_width=320),
                tooltip=f"{attr[1]} | {weather['temp']}°C",
                icon=folium.DivIcon(html=weather_html, icon_size=(70, 28))
            ).add_to(m)
    if route_coords and len(route_coords) > 1:
        folium.PolyLine(route_coords, color=route_color, weight=5, opacity=0.9,
                        popup=f'{transport_type}: {distance_km} км, {duration_min} мин',
                        tooltip=f'{distance_km} км | {duration_min} мин').add_to(m)
        add_direction_arrows(m, route_coords, route_color)
        time_str = f"{duration_min} мин" if duration_min < 60 else f"{duration_min // 60} ч {duration_min % 60} мин"
        start_popup = f'<div style="text-align:center;"><b>🏁 {start_name}</b><br><small>⏱️ {time_str}<br>📏 {distance_km} км</small></div>'
        folium.Marker(location=[route_coords[0][0], route_coords[0][1]],
                      popup=folium.Popup(start_popup, max_width=200),
                      icon=folium.Icon(color='darkblue', icon='play', prefix='fa')).add_to(m)
        folium.Marker(location=[route_coords[-1][0], route_coords[-1][1]],
                      popup=f"🏁 {end_name}",
                      icon=folium.Icon(color='darkgreen', icon='flag-checkered', prefix='fa')).add_to(m)
    legend_html = f'''
    <div style="position:fixed; bottom:20px; right:10px; background:white; padding:8px 12px; border-radius:8px; box-shadow:0 2px 5px rgba(0,0,0,0.2); font-family:Arial; font-size:11px; z-index:1000;">
        {"<b>📍 ИНФО режим</b><br>🔵 Синяя точка - место<br>👉 Нажмите для информации" if map_mode == 'info' else "<b>🌤️ ПОГОДА режим</b><br>☀️ Ясно &nbsp; 🌧️ Дождь<br>⛅ Облачно &nbsp; ❄️ Снег"}
    </div>
    <div style="position:fixed; top:10px; left:10px; background:white; padding:8px 12px; border-radius:8px; box-shadow:0 2px 5px rgba(0,0,0,0.2); font-family:Arial; font-size:12px; font-weight:bold;">
        {"📍 ИНФО" if map_mode == 'info' else "🌤️ ПОГОДА"}
    </div>
    '''
    m.get_root().html.add_child(folium.Element(legend_html))
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.html')
    m.save(temp_file.name)
    return temp_file.name


def open_map_in_browser(map_file):
    webbrowser.open(f'file://{map_file}')


def close_dialog(dialog):
    dialog.open = False
    if hasattr(dialog.page, 'update'):
        dialog.page.update()


def show_map_in_app(page: ft.Page, map_file):
    """Показывает карту внутри приложения через WebView"""
    try:
        # Читаем HTML файл
        with open(map_file, 'r', encoding='utf-8') as f:
            html_content = f.read()

        # Создаем WebView
        web_view = ft.WebView(
            content=html_content,
            width=page.window_width - 40,
            height=page.window_height - 150,
        )

        # Создаем диалог с WebView
        dialog = ft.AlertDialog(
            title=ft.Text("🗺️ Карта маршрута", size=20, weight=ft.FontWeight.BOLD, color=DARK_GREEN),
            content=ft.Container(
                content=web_view,
                width=page.window_width - 40,
                height=page.window_height - 150,
                bgcolor=SNOW_WHITE,
                border_radius=10,
            ),
            actions=[
                ft.TextButton("Закрыть", on_click=lambda e: close_dialog(dialog)),
                ft.TextButton("Открыть в браузере",
                              on_click=lambda e: [open_map_in_browser(map_file), close_dialog(dialog)]),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        page.dialog = dialog
        dialog.open = True
        page.update()
    except Exception as ex:
        print(f"Ошибка открытия WebView: {ex}")
        # Fallback - открываем в браузере
        open_map_in_browser(map_file)


# --- ГЛАВНАЯ ФУНКЦИЯ ПРИЛОЖЕНИЯ ---
def main(page: ft.Page):
    page.title = "Югра Тур"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = LIGHT_GREEN_BG
    page.padding = 0
    page.window_width = 450
    page.window_height = 800
    page.window_resizable = True

    # Состояние
    favorites = cache.get_favorites()
    online_status = is_online()
    app_start_time = time.time()
    app_running = True

    # Загружаем данные
    attractions = get_attractions_with_cache()
    events = get_events_with_cache()
    routes = get_routes_with_cache()

    current_map_mode = 'info'
    current_event_filter = 'all'

    # --- ФУНКЦИИ СТАТИСТИКИ ---
    def update_stats():
        visited_count = len(favorites)
        events_count = 0
        today = date.today()
        for e in events:
            if e[3]:
                if isinstance(e[3], date):
                    if e[3] <= today:
                        events_count += 1
                elif isinstance(e[3], str):
                    try:
                        event_date = datetime.strptime(e[3], '%Y-%m-%d').date()
                        if event_date <= today:
                            events_count += 1
                    except:
                        pass
        app_time = int((time.time() - app_start_time) / 60)

        cache.update_stat("visited", visited_count)
        cache.update_stat("events_participated", events_count)
        cache.update_stat("app_time", app_time)

        return visited_count, events_count, app_time

    def get_stats():
        visited = cache.get_stat("visited") or 0
        events_participated = cache.get_stat("events_participated") or 0
        app_time = cache.get_stat("app_time") or 0
        return int(visited), int(events_participated), int(app_time)

    def refresh_profile_stats():
        visited, events_participated, app_time = get_stats()
        stats_text.content = ft.Column([
            ft.Row([ft.Icon(ft.Icons.FAVORITE, color=BERRIES_RED, size=20),
                    ft.Text(f"Понравившиеся места: {visited}", size=14, color=PINE_BROWN)]),
            ft.Row([ft.Icon(ft.Icons.EVENT, color=BRIGHT_BLUE, size=20),
                    ft.Text(f"Посещенные события: {events_participated}", size=14, color=PINE_BROWN)]),
            ft.Row([ft.Icon(ft.Icons.TIMER, color=DARK_GREEN, size=20),
                    ft.Text(f"Время в приложении: {app_time} мин", size=14, color=PINE_BROWN)]),
        ], spacing=10)
        page.update()

    # --- ФУНКЦИЯ ОБНОВЛЕНИЯ ВРЕМЕНИ ---
    def update_time_periodically():
        while app_running:
            time.sleep(60)
            if hasattr(page, 'update'):
                update_stats()
                refresh_profile_stats()

    # --- СТИЛИЗОВАННЫЕ КОМПОНЕНТЫ ---
    class TaigaCard(ft.Container):
        def __init__(self, content, height=None):
            super().__init__(
                content=content,
                bgcolor=SNOW_WHITE,
                border_radius=15,
                padding=15,
                margin=ft.margin.only(bottom=10),
                shadow=ft.BoxShadow(
                    spread_radius=1,
                    blur_radius=5,
                    color=DARK_GREEN,
                ),
                height=height
            )

    def create_button(text, on_click, icon=None, expand=False, is_active=False):
        button_content = ft.Row([
            ft.Icon(icon, size=20, color=SNOW_WHITE if is_active else DARK_GREEN) if icon else ft.Container(),
            ft.Text(text, size=14, weight=ft.FontWeight.W_500, color=SNOW_WHITE if is_active else DARK_GREEN),
        ], spacing=8, alignment=ft.MainAxisAlignment.CENTER)

        button = ft.Container(
            content=button_content,
            on_click=on_click,
            bgcolor=DARK_GREEN if is_active else SNOW_WHITE,
            border=ft.border.all(1, DARK_GREEN),
            border_radius=10,
            padding=ft.padding.symmetric(vertical=10, horizontal=15),
            expand=expand,
            ink=True,
        )
        return button

    def create_section_header(title, icon, color=DARK_GREEN):
        random_animal = random.choice(TAIGA_ANIMALS)
        return ft.Container(
            content=ft.Row([
                ft.Icon(icon, color=color, size=28),
                ft.Text(f"{random_animal} {title}", size=20, weight=ft.FontWeight.BOLD, color=color),
            ], spacing=10),
            margin=ft.margin.only(bottom=15, top=10),
        )

    def update_connection_status():
        nonlocal online_status
        new_status = is_online()
        if new_status != online_status:
            online_status = new_status
            if online_status:
                update_all_views()
                page.snack_bar = ft.SnackBar(content=ft.Text("✅ Интернет восстановлен!"), open=True)
            else:
                page.snack_bar = ft.SnackBar(content=ft.Text("⚠️ Оффлайн режим"), open=True)
            page.update()

    def update_all_views():
        nonlocal attractions, events, routes
        attractions = get_attractions_with_cache()
        events = get_events_with_cache()
        routes = get_routes_with_cache()

        attractions_list.controls.clear()
        for attr in attractions:
            attractions_list.controls.append(create_attraction_card(attr))

        refresh_events_view()

        routes_list.controls.clear()
        for route in routes:
            route_points = get_route_points_with_cache(route[0])
            points_preview = " → ".join([p[2] for p in route_points[:3]]) if route_points else "Нет точек"
            route_card = TaigaCard(
                ft.Column([
                    ft.Row([ft.Icon(ft.Icons.ROUTE, color=BRIGHT_BLUE),
                            ft.Text(route[1], size=16, weight=ft.FontWeight.BOLD, color=DARK_GREEN, expand=True)]),
                    ft.Text(
                        route[2][:100] + "..." if route[2] and len(route[2]) > 100 else (route[2] if route[2] else ""),
                        size=12, color=PINE_BROWN),
                    ft.Text(f"📏 {route[3] if route[3] else '?'} км", size=11, color=PINE_BROWN),
                    ft.Text(f"📍 {points_preview}", size=11, color=PINE_BROWN),
                    ft.Row([
                        create_button("🚶 Пешком",
                                      lambda e, rid=route[0], rname=route[1]: show_route(rid, rname, 'foot', DARK_GREEN,
                                                                                         "пешком"),
                                      expand=True, is_active=True),
                        create_button("🚗 На авто",
                                      lambda e, rid=route[0], rname=route[1]: show_route(rid, rname, 'driving',
                                                                                         BERRIES_RED, "на авто"),
                                      expand=True),
                    ], spacing=10),
                ])
            )
            routes_list.controls.append(route_card)

        refresh_favorites_view()
        refresh_profile_stats()
        page.update()

    # --- ФУНКЦИИ ИЗБРАННОГО ---
    def toggle_favorite(attr_id, attr_name, button_ref):
        nonlocal favorites
        if attr_id in favorites:
            cache.remove_favorite(attr_id)
            favorites.remove(attr_id)
            button_ref.icon = ft.Icons.FAVORITE_BORDER
            button_ref.icon_color = PINE_BROWN
            page.snack_bar = ft.SnackBar(content=ft.Text(f"❌ {attr_name} удалено из избранного"), open=True)
        else:
            cache.add_favorite(attr_id)
            favorites.append(attr_id)
            button_ref.icon = ft.Icons.FAVORITE
            button_ref.icon_color = BERRIES_RED
            page.snack_bar = ft.SnackBar(content=ft.Text(f"❤️ {attr_name} добавлено в избранное"), open=True)

        refresh_favorites_view()
        update_stats()
        refresh_profile_stats()
        page.update()

    def refresh_favorites_view():
        fav_attractions_list.controls.clear()
        if favorites:
            for attr in attractions:
                if attr[0] in favorites:
                    fav_attractions_list.controls.append(create_attraction_card(attr, show_favorite_button=True))
        else:
            fav_attractions_list.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Text("🦊", size=64),
                        ft.Text("У вас пока нет избранных мест", size=14, color=PINE_BROWN),
                        ft.Text("Добавляйте достопримечательности в избранное", size=12, color=PINE_BROWN),
                        ft.Text("нажмите на сердечко во вкладке 'Места'", size=12, color=PINE_BROWN),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                    padding=30,
                )
            )
        page.update()

    def update_attractions_favorite_buttons():
        attractions_list.controls.clear()
        for attr in attractions:
            attractions_list.controls.append(create_attraction_card(attr, show_favorite_button=True))
        page.update()

    # --- ФУНКЦИИ ПРИЛОЖЕНИЯ ---
    def open_map(e, center_lat=CENTER_LAT, center_lon=CENTER_LON, zoom=12, route_coords=None,
                 highlight_attraction=None, route_color='green', start_name="СТАРТ", end_name="ФИНИШ",
                 duration_min=0, distance_km=0, transport_type="пешком"):
        try:
            map_file = create_map_html(center_lat, center_lon, zoom, route_coords, highlight_attraction,
                                       route_color, start_name, end_name, duration_min, distance_km,
                                       transport_type, current_map_mode)

            # На мобильных устройствах используем WebView, на ПК - браузер
            if platform.system() in ['Android', 'iOS']:
                show_map_in_app(page, map_file)
            else:
                open_map_in_browser(map_file)
            page.update()
        except Exception as ex:
            page.snack_bar = ft.SnackBar(content=ft.Text(f"Ошибка: {ex}"), open=True)
            page.update()

    def show_route(route_id, route_name, profile='foot', color='green', transport_type="пешком"):
        print(f"\n=== Построение маршрута {route_name} ===")
        print(f"ID маршрута: {route_id}")
        print(f"Тип транспорта: {transport_type}, профиль: {profile}")

        route_points = get_route_points_with_cache(route_id)
        print(f"Получено точек маршрута: {len(route_points)}")

        if len(route_points) < 2:
            page.snack_bar = ft.SnackBar(content=ft.Text("Недостаточно точек для маршрута (нужно минимум 2)"),
                                         open=True)
            page.update()
            return

        waypoints = []
        for i, p in enumerate(route_points):
            lat = float(p[0]) if p[0] else 0
            lon = float(p[1]) if p[1] else 0
            waypoints.append((lat, lon))
            print(f"Точка {i + 1}: {p[2]} - широта: {lat}, долгота: {lon}")

        start_point_name = route_points[0][2] if len(route_points[0]) > 2 else "Начало"
        end_point_name = route_points[-1][2] if len(route_points[-1]) > 2 else "Конец"

        print(f"Старт: {start_point_name}")
        print(f"Финиш: {end_point_name}")

        page.snack_bar = ft.SnackBar(content=ft.Text(f"🏔️ Построение маршрута {transport_type}..."), open=True)
        page.update()

        def build_and_show():
            try:
                print("Вызов build_osrm_route_fast...")
                result = build_osrm_route_fast(waypoints, profile)
                print(f"Результат построения: success={result['success']}")

                center_lat = waypoints[0][0]
                center_lon = waypoints[0][1]

                if result['success']:
                    route_coords = result['coords']
                    distance = result['distance_km']
                    duration = result['duration_min']
                    print(f"Маршрут успешно построен: {distance} км, {duration} мин")
                    print(f"Количество координат маршрута: {len(route_coords)}")

                    try:
                        print("Создание HTML карты...")
                        map_file = create_map_html(
                            center_lat, center_lon, 13,
                            route_coords, None, color,
                            start_point_name, end_point_name,
                            duration, distance, transport_type,
                            current_map_mode
                        )
                        print(f"Карта создана: {map_file}")

                        # На мобильных устройствах используем WebView
                        if platform.system() in ['Android', 'iOS']:
                            show_map_in_app(page, map_file)
                        else:
                            open_map_in_browser(map_file)

                        time_str = f"{duration} мин" if duration < 60 else f"{duration // 60} ч {duration % 60} мин"
                        page.snack_bar = ft.SnackBar(
                            content=ft.Text(f"✅ {route_name}: {distance} км, {time_str}"),
                            open=True)
                        print("Маршрут успешно открыт!")
                    except Exception as ex:
                        print(f"Ошибка при создании карты: {ex}")
                        page.snack_bar = ft.SnackBar(content=ft.Text(f"Ошибка создания карты: {ex}"), open=True)
                else:
                    print("Маршрут не удалось построить (сервер недоступен)")
                    page.snack_bar = ft.SnackBar(content=ft.Text(f"⚠️ {route_name} (сервер недоступен)"), open=True)
                page.update()
            except Exception as ex:
                print(f"Критическая ошибка: {ex}")
                page.snack_bar = ft.SnackBar(content=ft.Text(f"Ошибка: {ex}"), open=True)
                page.update()

        thread = threading.Thread(target=build_and_show, daemon=True)
        thread.start()

    def create_attraction_card(attr, show_favorite_button=False):
        is_favorite = attr[0] in favorites

        favorite_icon = ft.IconButton(
            icon=ft.Icons.FAVORITE if is_favorite else ft.Icons.FAVORITE_BORDER,
            icon_color=BERRIES_RED if is_favorite else PINE_BROWN,
            icon_size=24,
            on_click=lambda e, aid=attr[0], aname=attr[1]: toggle_favorite(aid, aname, e.control)
        )

        full_description = attr[2] if attr[2] else "Описание отсутствует"

        return TaigaCard(
            ft.Column([
                ft.Row([
                    ft.Text(attr[1], size=18, weight=ft.FontWeight.BOLD, color=DARK_GREEN, expand=True),
                    favorite_icon if show_favorite_button else ft.Text("")
                ]),
                ft.Text(full_description, size=13, color=PINE_BROWN),
                ft.Divider(height=5, color=LIGHT_BLUE),
                ft.Row([
                    ft.Icon(ft.Icons.ACCESS_TIME, size=16, color=BRIGHT_BLUE),
                    ft.Text(attr[5] if attr[5] else 'Часы не указаны', size=12, color=PINE_BROWN, expand=True),
                ], spacing=5),
                ft.Row([
                    ft.Icon(ft.Icons.PHONE, size=16, color=BRIGHT_BLUE),
                    ft.Text(attr[6] if attr[6] else 'Телефон не указан', size=12, color=PINE_BROWN, expand=True),
                ], spacing=5),
                create_button("📍 Смотреть на карте",
                              lambda e, lat=attr[3], lon=attr[4], name=attr[1]: open_map(e, lat, lon, 15, None, name),
                              icon=ft.Icons.MAP, expand=True, is_active=True),
            ], spacing=10)
        )

    # --- СОБЫТИЯ ---
    def filter_events():
        filtered = list(events)
        if current_event_filter == "soon":
            def get_date(event):
                if event[3]:
                    if isinstance(event[3], date):
                        return event[3]
                    elif isinstance(event[3], str):
                        try:
                            return datetime.strptime(event[3], '%Y-%m-%d').date()
                        except:
                            return date.max
                return date.max

            filtered.sort(key=get_date)
            today = date.today()
            filtered = [e for e in filtered if e[3] and (
                    (isinstance(e[3], date) and e[3] >= today) or
                    (isinstance(e[3], str) and datetime.strptime(e[3], '%Y-%m-%d').date() >= today)
            )]
        return filtered

    def set_event_filter(filter_type):
        nonlocal current_event_filter
        current_event_filter = filter_type
        all_btn.is_active = (filter_type == 'all')
        soon_btn.is_active = (filter_type == 'soon')
        all_btn.bgcolor = DARK_GREEN if filter_type == 'all' else SNOW_WHITE
        all_btn.content.controls[1].color = SNOW_WHITE if filter_type == 'all' else DARK_GREEN
        soon_btn.bgcolor = DARK_GREEN if filter_type == 'soon' else SNOW_WHITE
        soon_btn.content.controls[1].color = SNOW_WHITE if filter_type == 'soon' else DARK_GREEN
        refresh_events_view()
        page.update()

    def refresh_events_view():
        events_list.controls.clear()
        filtered = filter_events()
        if not filtered:
            events_list.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Text("🦌", size=48),
                        ft.Text("Нет предстоящих событий", size=14, color=PINE_BROWN),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=20, alignment=ft.alignment.center
                )
            )
        else:
            for i, event in enumerate(filtered, 1):
                status_text = ""
                try:
                    if event[3]:
                        if isinstance(event[3], date):
                            event_date = event[3]
                            today = date.today()
                            if event_date == today:
                                status_text = " 🔥 СЕГОДНЯ"
                            elif event_date > today:
                                days_left = (event_date - today).days
                                status_text = f" ⏰ через {days_left} дн."
                        elif isinstance(event[3], str):
                            event_date = datetime.strptime(event[3], '%Y-%m-%d').date()
                            today = date.today()
                            if event_date == today:
                                status_text = " 🔥 СЕГОДНЯ"
                            elif event_date > today:
                                days_left = (event_date - today).days
                                status_text = f" ⏰ через {days_left} дн."
                except:
                    pass
                event_card = TaigaCard(
                    ft.Column([
                        ft.Row([
                            ft.Text(f"{i}", size=20, weight=ft.FontWeight.BOLD, color=BRIGHT_BLUE),
                            ft.Text(event[1], size=16, weight=ft.FontWeight.BOLD, color=DARK_GREEN, expand=True),
                        ], spacing=10),
                        ft.Text(f"📅 {event[3] if event[3] else 'Дата не указана'}{status_text}", size=13,
                                color=PINE_BROWN),
                        ft.Text(f"📍 {event[4] if event[4] else 'Место не указано'}", size=13, color=PINE_BROWN),
                        ft.Text(event[2][:120] + "..." if event[2] and len(event[2]) > 120 else (
                            event[2] if event[2] else ""), size=12, color=PINE_BROWN),
                    ], spacing=8)
                )
                events_list.controls.append(event_card)
        page.update()

    # --- ПЕРЕКЛЮЧЕНИЕ РЕЖИМОВ КАРТЫ ---
    def set_info_mode(e):
        nonlocal current_map_mode
        current_map_mode = 'info'
        info_btn.is_active = True
        weather_btn.is_active = False
        info_btn.bgcolor = DARK_GREEN
        weather_btn.bgcolor = SNOW_WHITE
        info_btn.content.controls[1].color = SNOW_WHITE
        weather_btn.content.controls[1].color = DARK_GREEN
        page.snack_bar = ft.SnackBar(content=ft.Text("📍 Режим карты: Информация"), open=True)
        page.update()

    def set_weather_mode(e):
        nonlocal current_map_mode
        current_map_mode = 'weather'
        weather_btn.is_active = True
        info_btn.is_active = False
        weather_btn.bgcolor = DARK_GREEN
        info_btn.bgcolor = SNOW_WHITE
        weather_btn.content.controls[1].color = SNOW_WHITE
        info_btn.content.controls[1].color = DARK_GREEN
        page.snack_bar = ft.SnackBar(content=ft.Text("🌤️ Режим карты: Погода"), open=True)
        page.update()

    def manual_sync(e):
        if not online_status:
            page.snack_bar = ft.SnackBar(content=ft.Text("❌ Нет подключения к интернету"), open=True)
            page.update()
            return

        page.snack_bar = ft.SnackBar(content=ft.Text("🔄 Синхронизация..."), open=True)
        page.update()

        def sync():
            cache.clear_expired()
            update_all_views()
            page.snack_bar = ft.SnackBar(content=ft.Text("✅ Данные синхронизированы"), open=True)
            page.update()

        threading.Thread(target=sync).start()

    # --- СОЗДАНИЕ ВКЛАДОК ---
    attractions_list = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)
    for attr in attractions:
        attractions_list.controls.append(create_attraction_card(attr, show_favorite_button=True))
    attractions_view = ft.Column([
        create_section_header("Достопримечательности", ft.Icons.LOCATION_ON, DARK_GREEN),
        ft.Text(f"🌲 {len(attractions)} мест для исследования", size=14, color=PINE_BROWN),
        attractions_list
    ], scroll=ft.ScrollMode.AUTO, expand=True)

    events_list = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)

    all_btn = ft.Container(
        content=ft.Row([
            ft.Text("📋", size=16),
            ft.Text("Все события", size=14, weight=ft.FontWeight.W_500, color=SNOW_WHITE),
        ], spacing=8, alignment=ft.MainAxisAlignment.CENTER),
        on_click=lambda e: set_event_filter("all"),
        bgcolor=DARK_GREEN,
        border_radius=10,
        padding=ft.padding.symmetric(vertical=10, horizontal=15),
        expand=True,
        ink=True,
    )
    all_btn.is_active = True

    soon_btn = ft.Container(
        content=ft.Row([
            ft.Text("⭐", size=16),
            ft.Text("Ближайшие", size=14, weight=ft.FontWeight.W_500, color=DARK_GREEN),
        ], spacing=8, alignment=ft.MainAxisAlignment.CENTER),
        on_click=lambda e: set_event_filter("soon"),
        bgcolor=SNOW_WHITE,
        border=ft.border.all(1, DARK_GREEN),
        border_radius=10,
        padding=ft.padding.symmetric(vertical=10, horizontal=15),
        expand=True,
        ink=True,
    )
    soon_btn.is_active = False

    filter_row = ft.Row([all_btn, soon_btn], spacing=10)
    refresh_events_view()
    events_view = ft.Column([
        create_section_header("События", ft.Icons.EVENT, BRIGHT_BLUE),
        filter_row,
        events_list
    ], scroll=ft.ScrollMode.AUTO, expand=True)

    routes_list = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)
    for route in routes:
        route_points = get_route_points_with_cache(route[0])
        points_preview = " → ".join([p[2] for p in route_points[:3]]) if route_points else "Нет точек"
        route_card = TaigaCard(
            ft.Column([
                ft.Row([ft.Icon(ft.Icons.ROUTE, color=BRIGHT_BLUE, size=28),
                        ft.Text(route[1], size=18, weight=ft.FontWeight.BOLD, color=DARK_GREEN, expand=True)]),
                ft.Text(route[2][:100] + "..." if route[2] and len(route[2]) > 100 else (route[2] if route[2] else ""),
                        size=13, color=PINE_BROWN),
                ft.Row([
                    ft.Icon(ft.Icons.STRAIGHTEN, size=16, color=DARK_GREEN),
                    ft.Text(f"{route[3] if route[3] else '?'} км", size=13, color=PINE_BROWN),
                ], spacing=5),
                ft.Text(f"🗺️ {points_preview}", size=12, color=PINE_BROWN),
                ft.Row([
                    create_button("🚶 Пешком",
                                  lambda e, rid=route[0], rname=route[1]: show_route(rid, rname, 'foot', DARK_GREEN,
                                                                                     "пешком"),
                                  expand=True, is_active=True),
                    create_button("🚗 На авто",
                                  lambda e, rid=route[0], rname=route[1]: show_route(rid, rname, 'driving', BERRIES_RED,
                                                                                     "на авто"),
                                  expand=True),
                ], spacing=10),
            ], spacing=10)
        )
        routes_list.controls.append(route_card)
    routes_view = ft.Column([
        create_section_header("Маршруты", ft.Icons.ROUTE, DEEP_BLUE),
        ft.Text(f"🗺️ {len(routes)} живописных маршрутов", size=14, color=PINE_BROWN),
        routes_list
    ], scroll=ft.ScrollMode.AUTO, expand=True)

    fav_attractions_list = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)
    favorites_view = ft.Column([
        create_section_header("Избранное", ft.Icons.FAVORITE, BERRIES_RED),
        ft.Text("❤️ Ваши любимые уголки Югры", size=14, color=PINE_BROWN),
        fav_attractions_list,
    ], scroll=ft.ScrollMode.AUTO, expand=True)
    refresh_favorites_view()

    # Статистика
    visited_count, events_count, app_time = get_stats()
    stats_text = ft.Container(
        content=ft.Column([
            ft.Row([ft.Icon(ft.Icons.FAVORITE, color=BERRIES_RED, size=20),
                    ft.Text(f"Понравившиеся места: {visited_count}", size=14, color=PINE_BROWN)]),
            ft.Row([ft.Icon(ft.Icons.EVENT, color=BRIGHT_BLUE, size=20),
                    ft.Text(f"Посещенные события: {events_count}", size=14, color=PINE_BROWN)]),
            ft.Row([ft.Icon(ft.Icons.TIMER, color=DARK_GREEN, size=20),
                    ft.Text(f"Время в приложении: {app_time} мин", size=14, color=PINE_BROWN)]),
        ], spacing=10),
        padding=15,
        bgcolor=SNOW_WHITE,
        border_radius=15,
    )

    # Кнопки режимов карты в профиле
    info_btn = ft.Container(
        content=ft.Row([
            ft.Text("📍", size=16),
            ft.Text("Инфо", size=14, weight=ft.FontWeight.W_500, color=SNOW_WHITE),
        ], spacing=8, alignment=ft.MainAxisAlignment.CENTER),
        on_click=set_info_mode,
        bgcolor=DARK_GREEN,
        border_radius=10,
        padding=ft.padding.symmetric(vertical=10, horizontal=15),
        expand=True,
        ink=True,
    )
    info_btn.is_active = True

    weather_btn = ft.Container(
        content=ft.Row([
            ft.Text("🌤️", size=16),
            ft.Text("Погода", size=14, weight=ft.FontWeight.W_500, color=DARK_GREEN),
        ], spacing=8, alignment=ft.MainAxisAlignment.CENTER),
        on_click=set_weather_mode,
        bgcolor=SNOW_WHITE,
        border=ft.border.all(1, DARK_GREEN),
        border_radius=10,
        padding=ft.padding.symmetric(vertical=10, horizontal=15),
        expand=True,
        ink=True,
    )
    weather_btn.is_active = False

    # Профиль
    profile_view = ft.Column([
        ft.Row([
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.WIFI if online_status else ft.Icons.WIFI_OFF, size=16,
                            color=DARK_GREEN if online_status else PINE_BROWN),
                    ft.Text("Online" if online_status else "Offline", size=12,
                            color=DARK_GREEN if online_status else PINE_BROWN)
                ], spacing=5),
                padding=ft.padding.all(8),
                bgcolor=SNOW_WHITE,
                border_radius=20,
                border=ft.border.all(1, DARK_GREEN),
            ),
            ft.Container(expand=True),
            ft.IconButton(icon=ft.Icons.SYNC, on_click=manual_sync, icon_color=DARK_GREEN,
                          tooltip="Синхронизировать данные"),
        ]),
        ft.Container(
            content=ft.Column([
                ft.Text("🐻", size=60),
                ft.Text("Гость Югры", size=24, weight=ft.FontWeight.BOLD, color=DARK_GREEN),
                ft.Text("Исследуйте Югру вместе с нами!", size=12, color=PINE_BROWN),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
            padding=20,
            bgcolor=SNOW_WHITE,
            border_radius=15,
        ),
        ft.Divider(height=20),
        ft.Container(
            content=ft.Column([
                ft.Text("🎛️ Режим карты", size=18, weight=ft.FontWeight.BOLD, color=DARK_GREEN),
                ft.Row([info_btn, weather_btn], spacing=20),
            ], spacing=15),
            padding=15,
            bgcolor=SNOW_WHITE,
            border_radius=15,
        ),
        ft.Divider(height=20),
        ft.Container(
            content=ft.Column([
                ft.Text("📊 Моя статистика", size=18, weight=ft.FontWeight.BOLD, color=DARK_GREEN),
                stats_text,
            ], spacing=15),
            padding=15,
            bgcolor=SNOW_WHITE,
            border_radius=15,
        ),
        ft.Divider(height=20),
        create_button("🗺️ Открыть карту", lambda e: open_map(None), icon=ft.Icons.MAP, is_active=True),
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=20, scroll=ft.ScrollMode.AUTO, expand=True)

    # --- НАВИГАЦИЯ ---
    content_container = ft.Column([attractions_view], expand=True)

    def switch_content(view, tab_name):
        content_container.controls.clear()
        content_container.controls.append(view)
        for item in nav_items:
            if item["tab"] == tab_name:
                item["icon"].color = BRIGHT_BLUE
                item["text"].color = BRIGHT_BLUE
                item["icon"].size = 26
            else:
                item["icon"].color = LIGHT_BLUE
                item["text"].color = LIGHT_BLUE
                item["icon"].size = 24
        page.update()

    nav_items = []

    nav_attractions_icon = ft.Icon(ft.Icons.LIST, color=BRIGHT_BLUE, size=26)
    nav_attractions_text = ft.Text("Места", size=12, color=BRIGHT_BLUE)
    nav_items.append({"tab": "attractions", "icon": nav_attractions_icon, "text": nav_attractions_text})

    nav_events_icon = ft.Icon(ft.Icons.EVENT, color=LIGHT_BLUE, size=24)
    nav_events_text = ft.Text("События", size=12, color=LIGHT_BLUE)
    nav_items.append({"tab": "events", "icon": nav_events_icon, "text": nav_events_text})

    nav_routes_icon = ft.Icon(ft.Icons.ROUTE, color=LIGHT_BLUE, size=24)
    nav_routes_text = ft.Text("Маршруты", size=12, color=LIGHT_BLUE)
    nav_items.append({"tab": "routes", "icon": nav_routes_icon, "text": nav_routes_text})

    nav_fav_icon = ft.Icon(ft.Icons.FAVORITE, color=LIGHT_BLUE, size=24)
    nav_fav_text = ft.Text("Избранное", size=12, color=LIGHT_BLUE)
    nav_items.append({"tab": "favorites", "icon": nav_fav_icon, "text": nav_fav_text})

    nav_profile_icon = ft.Icon(ft.Icons.PERSON, color=LIGHT_BLUE, size=24)
    nav_profile_text = ft.Text("Профиль", size=12, color=LIGHT_BLUE)
    nav_items.append({"tab": "profile", "icon": nav_profile_icon, "text": nav_profile_text})

    nav_bar = ft.Container(
        content=ft.Row([
            ft.Container(content=ft.Column([nav_attractions_icon, nav_attractions_text],
                                           horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=5),
                         on_click=lambda e: switch_content(attractions_view, "attractions"), expand=True),
            ft.Container(content=ft.Column([nav_events_icon, nav_events_text],
                                           horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=5),
                         on_click=lambda e: switch_content(events_view, "events"), expand=True),
            ft.Container(content=ft.Column([nav_routes_icon, nav_routes_text],
                                           horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=5),
                         on_click=lambda e: switch_content(routes_view, "routes"), expand=True),
            ft.Container(content=ft.Column([nav_fav_icon, nav_fav_text],
                                           horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=5),
                         on_click=lambda e: switch_content(favorites_view, "favorites"), expand=True),
            ft.Container(content=ft.Column([nav_profile_icon, nav_profile_text],
                                           horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=5),
                         on_click=lambda e: switch_content(profile_view, "profile"), expand=True),
        ], alignment=ft.MainAxisAlignment.SPACE_AROUND),
        bgcolor=SNOW_WHITE,
        padding=ft.padding.only(top=10, bottom=10),
        shadow=ft.BoxShadow(spread_radius=1, blur_radius=10, color=LIGHT_BLUE),
    )

    # Верхняя часть (белая)
    header_animals = random.sample(TAIGA_ANIMALS, 3)
    header = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text(header_animals[0], size=30),
                ft.Text(header_animals[1], size=30),
                ft.Text(header_animals[2], size=30),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=15),
            ft.Row([
                ft.Icon(ft.Icons.PARK, color=DARK_GREEN, size=32),
                ft.Text("Югра Тур", size=34, weight=ft.FontWeight.BOLD, color=DARK_GREEN),
                ft.Icon(ft.Icons.WATER, color=BRIGHT_BLUE, size=32),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=10),
            ft.Text("Путеводитель по Югре", size=12, color=PINE_BROWN),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
        padding=ft.padding.only(top=20, bottom=15),
        bgcolor=SNOW_WHITE,
        shadow=ft.BoxShadow(spread_radius=1, blur_radius=5, color=LIGHT_BLUE),
    )

    page.add(header, content_container, nav_bar)

    # Обновляем статистику при запуске
    update_stats()
    refresh_profile_stats()

    # Запускаем фоновый поток для обновления времени
    time_thread = threading.Thread(target=update_time_periodically, daemon=True)
    time_thread.start()

    print("✅ Приложение 'Югра Тур' запущено!")
    print(f"   - 📊 Загружено достопримечательностей: {len(attractions)}")
    print(f"   - 📅 Загружено событий: {len(events)}")
    print(f"   - 🗺️ Загружено маршрутов: {len(routes)}")
    print("   - ❤️ Избранное: Работает без авторизации")
    print("   - 📈 Статистика обновляется автоматически")
    print("   - 🚀 Маршруты и погода работают быстро")


if __name__ == "__main__":
    try:
        from db_config import get_db_connection

        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM attractions")
            count = cursor.fetchone()[0]
            cursor.close()
            conn.close()
            print(f"✅ Подключено к базе данных! {count} достопримечательностей")

            cursor2 = conn.cursor()
            cursor2.execute("SELECT id, name FROM routes")
            routes_list = cursor2.fetchall()
            print(f"📋 Найдено маршрутов: {len(routes_list)}")
            for route in routes_list:
                cursor3 = conn.cursor()
                cursor3.execute("SELECT COUNT(*) FROM route_points WHERE route_id = %s", (route[0],))
                points_count = cursor3.fetchone()[0]
                print(f"   - Маршрут '{route[1]}' (ID={route[0]}): {points_count} точек")
                cursor3.close()
            cursor2.close()
            conn.close()
        else:
            print("❌ Ошибка подключения к MySQL")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

    ft.app(target=main)