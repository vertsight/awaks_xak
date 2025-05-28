import telebot
from telebot import types
from telebot.types import BotCommand
import json
import os
import sys
import threading
import time
from typing import List
from DataStorage import DataStorage, Theme
from DataTypes import Subtheme
from Configs import BOT_TOKEN, MYSQL_CONFIG
import LoadData

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
storage = DataStorage(MYSQL_CONFIG)

user_state = {}
UPDATE_RATE = 1
THEMES_PER_PAGE = 8
COLUMNS = 4
IS_SHOW_LOGS = True

CHATS_FILE = "chats_for_updates.json"
CHATS_ID_SHOWING_NEWS: List[int] = []
LOCK_FILE = "bot.lock"

def crop_for_callback(data: str, prefix: str = "", max_length: int = 64) -> str:
    allowed = max_length - len(prefix)
    if len(data.encode('utf-8')) <= allowed:
        return prefix + data
    return prefix + data.encode('utf-8')[:allowed - 3].decode('utf-8', errors='ignore') + "..."

def set_bot_commands():
    bot.set_my_commands([
        BotCommand("start", "Начать взаимодействие с ботом"),
        BotCommand("setnews", "Подписаться на уведомления о новых темах"),
        BotCommand("unsetnews", "Отписаться от уведомлений"),
        BotCommand("checknews", "Проверить обновления вручную"),
        BotCommand("searcht", "Поиск обсуждения по названию"),
        BotCommand("chooset", "Выбрать обсуждение из списка"),
        BotCommand("help", "Показать список всех команд"),
    ])

def load_chats_for_updates():
    global CHATS_ID_SHOWING_NEWS
    if os.path.exists(CHATS_FILE):
        try:
            with open(CHATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    CHATS_ID_SHOWING_NEWS = [int(x) for x in data if isinstance(x, (int, str)) and str(x).lstrip('-').isdigit()]
                else:
                    CHATS_ID_SHOWING_NEWS = []
            if IS_SHOW_LOGS:
                print(f"[INIT] Загружено {len(CHATS_ID_SHOWING_NEWS)} чатов для уведомлений")
        except Exception as e:
            print(f"[ERROR] Ошибка загрузки {CHATS_FILE}: {e}")
            CHATS_ID_SHOWING_NEWS = []
    else:
        CHATS_ID_SHOWING_NEWS = []
        if IS_SHOW_LOGS:
            print(f"[INFO] Файл {CHATS_FILE} не найден. Создан пустой список.")

def save_chats_for_updates():
    try:
        with open(CHATS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(set(CHATS_ID_SHOWING_NEWS)), f, indent=2, ensure_ascii=False)
        if IS_SHOW_LOGS:
            print("[SAVE] Список чатов для уведомлений обновлён")
    except Exception as e:
        print(f"[ERROR] Ошибка сохранения {CHATS_FILE}: {e}")

def safe_send_message(chat_id, text, reply_markup=None):
    if chat_id not in user_state:
        user_state[chat_id] = {}
    last_msg_id = user_state[chat_id].get("last_bot_message_id")
    if last_msg_id:
        try:
            bot.delete_message(chat_id, last_msg_id)
        except Exception as e:
            if IS_SHOW_LOGS:
                print(f"[WARN] Не удалось удалить сообщение {last_msg_id}: {e}")
    try:
        sent = bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="HTML")
        user_state[chat_id]["last_bot_message_id"] = sent.message_id
    except Exception as e:
        if IS_SHOW_LOGS:
            print(f"[ERROR] Не удалось отправить сообщение в {chat_id}: {e}")

def send_new_conference_notification(chat_id: int, theme: Theme):
    text = (
        f"Добавлено новое обсуждение <b>{theme.conference.name}</b>!\n"
        f"{theme.conference.description or 'Описание отсутствует'}\n"
    )
    if theme.subthemes:
        text += "Содержит темы:\n" + "\n".join(f" - <b>{st.name}</b>" for st in theme.subthemes)
    safe_send_message(chat_id, text)

def send_new_subtheme_notification(chat_id: int, conference_name: str, subtheme: Subtheme):
    text = (
        f"В обсуждение <b>{conference_name}</b> добавлена новая тема <b>{subtheme.name}</b>!\n"
        f"{subtheme.description or 'Описание отсутствует'}"
    )
    safe_send_message(chat_id, text)

def notify_new_data(chat_ids: List[int] = None):
    new_confs, new_subthemes = storage.get_new_conferences_and_subthemes()
    if not chat_ids:
        chat_ids = CHATS_ID_SHOWING_NEWS

    for chat_id in chat_ids:
        for conf in new_confs:
            send_new_conference_notification(chat_id, conf)
        for conf_name, subthemes in new_subthemes.items():
            for subtheme in subthemes:
                send_new_subtheme_notification(chat_id, conf_name, subtheme)

def check_updates_loop():
    if IS_SHOW_LOGS:
        print(f"[AUTO-UPDATE] Проверка обновлений БД")
    try:
        LoadData.fetch_all_conferences(MYSQL_CONFIG)
        storage.load_themes()
        if IS_SHOW_LOGS:
            print("[AUTO-UPDATE] Данные обновлены из базы данных")
    except Exception as e:
        print(f"[ERROR] Ошибка обновления данных из БД: {e}")
    notify_new_data()
    threading.Timer(UPDATE_RATE, check_updates_loop).start()

@bot.message_handler(commands=["start"])
def cmd_start(message):
    if IS_SHOW_LOGS:
        print(f"[LOG] Пользователь {message.chat.id} использовал /start")
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Найти обсуждение", callback_data=crop_for_callback("start_search")))
    markup.add(types.InlineKeyboardButton("Выбрать обсуждение", callback_data=crop_for_callback("choose_theme")))
    safe_send_message(message.chat.id,
                      "Я - бот цифровой помощник)\nПо какому обсуждению Вы хотите увидеть содержание?",
                      reply_markup=markup)

@bot.message_handler(commands=["help"])
def cmd_help(message):
    help_text = (
        "<b>Список доступных команд:</b>\n"
        "/start — начать взаимодействие с ботом\n"
        "/setnews — подписаться на уведомления о новых темах\n"
        "/unsetnews — отписаться от уведомлений\n"
        "/checknews — проверить обновления\n"
        "/searcht — поиск обсуждения\n"
        "/chooset — выбрать обсуждение\n"
        "/help — список всех команд"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Ок", callback_data=crop_for_callback("ok_dismiss")))
    safe_send_message(message.chat.id, help_text, reply_markup=markup)

@bot.message_handler(commands=["setnews"])
def cmd_set_show_news(message):
    chat_id = message.chat.id
    if chat_id not in CHATS_ID_SHOWING_NEWS:
        CHATS_ID_SHOWING_NEWS.append(chat_id)
        save_chats_for_updates()
        text = "Вы подписались на уведомления о новых обсуждениях и темах."
        if IS_SHOW_LOGS:
            print(f"[SETNEWS] Чат {chat_id} добавлен в список рассылки.")
    else:
        text = "Вы уже подписаны на уведомления."
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Ок", callback_data=crop_for_callback("ok_dismiss")))
    safe_send_message(chat_id, text, reply_markup=markup)

@bot.message_handler(commands=["unsetnews"])
def cmd_unset_show_news(message):
    chat_id = message.chat.id
    if chat_id in CHATS_ID_SHOWING_NEWS:
        CHATS_ID_SHOWING_NEWS.remove(chat_id)
        save_chats_for_updates()
        text = "Вы отписались от уведомлений."
    else:
        text = "Вы не были подписаны на уведомления."
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Ок", callback_data=crop_for_callback("ok_dismiss")))
    safe_send_message(chat_id, text, reply_markup=markup)

@bot.message_handler(commands=["checknews"])
def cmd_check_updates(message):
    if IS_SHOW_LOGS:
        print(f"[UPDATE] Проверка обновлений БД по запросу {message.chat.id}")
    try:
        LoadData.fetch_all_conferences(MYSQL_CONFIG)
        storage.load_themes()
        if IS_SHOW_LOGS:
            print("[UPDATE] Данные обновлены из базы данных")
    except Exception as e:
        print(f"[ERROR] Ошибка обновления данных из БД: {e}")
    notify_new_data([message.chat.id])

@bot.message_handler(commands=["searcht"])
def cmd_search(message):
    if IS_SHOW_LOGS:
        print(f"[LOG] Пользователь {message.chat.id} перешел в режим поиска")
    chat_id = message.chat.id
    user_state[chat_id] = {"mode": "search"}
    safe_send_message(chat_id, "Введите название обсуждения:")

@bot.message_handler(commands=["chooset"])
def cmd_choose(message):
    if IS_SHOW_LOGS:
        print(f"[LOG] Пользователь {message.chat.id} перешел в режим выбора")
    chat_id = message.chat.id
    user_state[chat_id] = {"mode": "choose", "page": 0}
    send_theme_list(chat_id)

@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("mode") == "search")
def handle_theme_search(message):
    chat_id = message.chat.id
    if IS_SHOW_LOGS:
        print(f"[SEARCH] Пользователь {chat_id} ищет: {message.text}")
    theme = storage.find_theme(message.text)
    if not theme:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Ок", callback_data=crop_for_callback("start_search")))
        safe_send_message(chat_id, "Не нашёл такого обсуждения...", reply_markup=markup)
    else:
        if IS_SHOW_LOGS:
            print(f"[SEARCH] Найдено: {theme.conference.name}")
        user_state[chat_id] = {"mode": "view", "theme": theme, "page": 0}
        send_theme_page(chat_id, theme, 0)

def send_theme_page(chat_id, theme: Theme, page: int):
    subthemes = theme.subthemes
    start = page * THEMES_PER_PAGE
    end = start + THEMES_PER_PAGE
    current = subthemes[start:end]

    markup = types.InlineKeyboardMarkup(row_width=COLUMNS)
    for i in range(0, len(current), COLUMNS):
        row = [
            types.InlineKeyboardButton(st.name, callback_data=crop_for_callback(f"subtheme:{start + i + j}"))
            for j, st in enumerate(current[i:i+COLUMNS])
        ]
        markup.row(*row)

    nav = []
    if start > 0:
        nav.append(types.InlineKeyboardButton("Назад", callback_data=crop_for_callback("prev_page")))
    if end < len(subthemes):
        nav.append(types.InlineKeyboardButton("Вперёд", callback_data=crop_for_callback("next_page")))
    if nav:
        markup.row(*nav)

    markup.row(types.InlineKeyboardButton("Закончить просмотр обсуждения", callback_data=crop_for_callback("end_session")))

    if IS_SHOW_LOGS:
        print(f"[VIEW] Страница {page} обсуждения '{theme.conference.name}'")
    safe_send_message(chat_id,
                      f"<b>Обсуждение:</b> {theme.conference.name}\n{theme.conference.description or 'Описание отсутствует'}",
                      reply_markup=markup)

def send_theme_list(chat_id):
    all_themes = storage.themes
    state = user_state.get(chat_id, {})
    page = state.get("page", 0)
    start = page * THEMES_PER_PAGE
    end = start + THEMES_PER_PAGE
    current = all_themes[start:end]

    markup = types.InlineKeyboardMarkup(row_width=COLUMNS)
    for i in range(0, len(current), COLUMNS):
        row = [
            types.InlineKeyboardButton(t.conference.name, callback_data=crop_for_callback(f"choose:{t.conference.id}"))
            for t in current[i:i+COLUMNS]
        ]
        markup.row(*row)

    nav = []
    if start > 0:
        nav.append(types.InlineKeyboardButton("Назад", callback_data=crop_for_callback("choose_prev")))
    if end < len(all_themes):
        nav.append(types.InlineKeyboardButton("Вперёд", callback_data=crop_for_callback("choose_next")))
    if nav:
        markup.row(*nav)

    markup.row(types.InlineKeyboardButton("Закончить просмотр обсуждения", callback_data=crop_for_callback("end_session")))

    if IS_SHOW_LOGS:
        print(f"[CHOOSE] Список тем: страница {page}")
    safe_send_message(chat_id, "Выберите обсуждение:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    state = user_state.get(chat_id)
    data = call.data

    if IS_SHOW_LOGS:
        print(f"[CALLBACK] Пользователь {chat_id}, действие: {data}")

    def delete_callback_message():
        try:
            bot.delete_message(chat_id, message_id)
        except Exception as e:
            if IS_SHOW_LOGS:
                print(f"[WARN] Не удалось удалить сообщение {message_id}: {e}")

    if data == "start_search":
        delete_callback_message()
        user_state[chat_id] = {"mode": "search"}
        safe_send_message(chat_id, "Введите название обсуждения:")

    elif data == "choose_theme":
        delete_callback_message()
        user_state[chat_id] = {"mode": "choose", "page": 0}
        send_theme_list(chat_id)

    elif data == "end_session":
        delete_callback_message()
        user_state.pop(chat_id, None)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Ок", callback_data=crop_for_callback("end_ok")))
        safe_send_message(chat_id,
                          "Сеанс завершён. Введите /start, /searcht или /chooset чтобы начать заново.",
                          reply_markup=markup)

    elif data == "end_ok":
        delete_callback_message()

    elif data == "ok_dismiss":
        try:
            bot.delete_message(chat_id, message_id)
        except Exception as e:
            if IS_SHOW_LOGS:
                print(f"[WARN] Не удалось удалить сообщение с 'Ок': {e}")

    elif data == "next_page" and state and "theme" in state:
        delete_callback_message()
        state["page"] += 1
        send_theme_page(chat_id, state["theme"], state["page"])

    elif data == "prev_page" and state and "theme" in state:
        delete_callback_message()
        state["page"] -= 1
        send_theme_page(chat_id, state["theme"], state["page"])

    elif data == "choose_next" and state and state.get("mode") == "choose":
        delete_callback_message()
        state["page"] += 1
        send_theme_list(chat_id)

    elif data == "choose_prev" and state and state.get("mode") == "choose":
        delete_callback_message()
        state["page"] -= 1
        send_theme_list(chat_id)

    elif data.startswith("choose:"):
        delete_callback_message()
        conf_id = int(data.split(":", 1)[1])
        theme = next((t for t in storage.themes if t.conference.id == conf_id), None)
        if theme:
            user_state[chat_id] = {"mode": "view", "theme": theme, "page": 0}
            send_theme_page(chat_id, theme, 0)

    elif data.startswith("subtheme:"):
        delete_callback_message()
        index = int(data.split(":", 1)[1])
        theme = state.get("theme")
        if theme and 0 <= index < len(theme.subthemes):
            selected = theme.subthemes[index]
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("Назад", callback_data=crop_for_callback("return_to_theme")))
            markup.add(types.InlineKeyboardButton("Закончить просмотр обсуждения", callback_data=crop_for_callback("end_session")))
            safe_send_message(chat_id,
                              f"<b>Обсуждение:</b> {theme.conference.name}\n"
                              f"<b>Тема:</b> {selected.name}\n"
                              f"{selected.description or 'Описание отсутствует'}",
                              reply_markup=markup)

    elif data == "return_to_theme" and state and "theme" in state:
        delete_callback_message()
        send_theme_page(chat_id, state["theme"], state["page"])

def acquire_lock():
    if os.path.exists(LOCK_FILE):
        print("Another instance of the bot is already running.")
        sys.exit(1)
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))
    return True

def release_lock():
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)

if __name__ == "__main__":
    try:
        if acquire_lock():
            print(f"Бот запускается... PID: {os.getpid()}")
            set_bot_commands()
            load_chats_for_updates()
            check_updates_loop()
            bot.infinity_polling()
    except KeyboardInterrupt:
        print("Остановка бота...")
        bot.stop_polling()
        release_lock()
        sys.exit(0)
    except Exception as e:
        print(f"Ошибка: {e}")
        release_lock()
        sys.exit(1)
    finally:
        release_lock()