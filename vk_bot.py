import vk_api
import os
from vk_api import VkUpload
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from config import token, group_id, time_mailing
from datetime import datetime, timedelta
from image_creator import create_image_from_database
import sqlite3
import schedule
import threading
import time
import pytz
import json

developer_ids = [472490157, 499485705]
vk_session = vk_api.VkApi(token=token)
vk = vk_session.get_api()
upload = VkUpload(vk_session)
novosibirsk_tz = pytz.timezone('Asia/Novosibirsk')
button_presses = {}
button_cooldown = timedelta(seconds=2)
time_mailing = time_mailing

db_path = 'data.db'


class MyVkLongPoll(VkBotLongPoll):
    def listen(self):
        while True:
            try:
                for event in self.check():
                    yield event
            except Exception as e:
                print('error:', e)


longpoll = MyVkLongPoll(vk_session, group_id)


conn = sqlite3.connect('members.db')
c = conn.cursor()
try:
    c.execute('''CREATE TABLE members
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  vk_id INTEGER,
                  first_name TEXT,
                  last_name TEXT,
                  administrator INTEGER,
                  ignored INTEGER)''')
    conn.commit()
except sqlite3.OperationalError:
    pass

logs_conn = sqlite3.connect('logs.db')
logs_c = logs_conn.cursor()
try:
    logs_c.execute('''CREATE TABLE logs
                      (id INTEGER PRIMARY KEY AUTOINCREMENT,
                       timestamp TEXT,
                       user_id INTEGER,
                       first_name TEXT,
                       last_name TEXT,
                       command TEXT)''')
    logs_conn.commit()
except sqlite3.OperationalError:
    pass


def send_message(chat_id, text):
    """Отправляет текстовое сообщение в указанный чат."""
    vk.messages.send(chat_id=chat_id, message=text, random_id=0)


def send_image(peer_id, image_path, text=''):
    """Отправка изображения в чат."""
    upload = vk_api.VkUpload(vk)
    photo = upload.photo_messages(image_path)[0]
    owner_id = photo['owner_id']
    photo_id = photo['id']
    access_key = photo['access_key']
    attachment = f'photo{owner_id}_{photo_id}_{access_key}'
    if peer_id > 2000000000:
        chat_id = peer_id - 2000000000
        vk.messages.send(chat_id=chat_id, message=text, attachment=attachment, random_id=0)
    else:
        vk.messages.send(user_id=peer_id, message=text, attachment=attachment, random_id=0)


def add_chat_members(vk, chat_id, developer_ids):
    """Добавление участников беседы в базу данных."""
    members = vk.messages.getConversationMembers(peer_id=2000000000 + chat_id)
    for member in members['profiles']:
        vk_id = member['id']
        c.execute("SELECT * FROM members WHERE vk_id=?", (vk_id,))
        row = c.fetchone()
        if row is None:
            first_name = member['first_name']
            last_name = member['last_name']
            chat_admin = 1 if vk_id in developer_ids or vk_id in [member['member_id'] for member in members['items']
                                                                  if 'is_admin' in member and member['is_admin']] else 0
            ignored = 0
            c.execute(
                "INSERT INTO members (vk_id, first_name, last_name, administrator, ignored) VALUES (?, ?, ?, ?, ?)",
                (vk_id, first_name, last_name, chat_admin, ignored))
        else:
            id, vk_id, first_name, last_name, chat_admin, ignored = row
            if chat_admin == 0 and vk_id in [member['member_id'] for member in members['items'] if
                                             'is_admin' in member and member['is_admin']]:
                c.execute("UPDATE members SET administrator=1 WHERE vk_id=?", (vk_id,))
    conn.commit()


add_chat_members(vk, 1, developer_ids)


def handle_info_command(event, chat_id, message_text):
    """Получение информации об участнике."""
    vk_id = None
    if event.object.message.get('reply_message'):
        vk_id = event.object.message['reply_message']['from_id']
    else:
        parts = message_text.split()
        if len(parts) == 2:
            try:
                num = int(parts[1])
                c.execute("SELECT vk_id FROM members WHERE id=?", (num,))
                row = c.fetchone()
                if row is not None:
                    vk_id = row[0]
            except ValueError:
                user_str = parts[1].lstrip('@').strip('[]')
                if user_str.startswith('id'):
                    vk_id = int(user_str[2:].split('|')[0])
    if vk_id is not None:
        c.execute("SELECT * FROM members WHERE vk_id=?", (vk_id,))
        row = c.fetchone()
        if row:
            id, vk_id, first_name, last_name, administrator, ignored = row
            info = f'№{id}\n[id{vk_id}|{first_name} {last_name}]\nСтатусы:\n▶ A - {administrator}\n▶ I - {ignored}'
            send_message(chat_id, info)
        else:
            send_message(chat_id, 'Пользователь не найден в базе данных')
    else:
        send_message(chat_id, 'Неверный формат команды. Используйте: !инфо № или !инфо @username')


def handle_schedule_command(chat_id, message_text, db_path):
    """Обработка сообщения и вывод клавиатуры или изображения с расписанием."""
    message_parts = message_text.split()
    if len(message_parts) == 1:
        today = datetime.now(novosibirsk_tz)
        day_keyboard, target_dates = get_keyboard(today)
        vk.messages.send(chat_id=chat_id, message='Выберите день недели:', random_id=0, keyboard=day_keyboard)
    else:
        try:
            date_var = message_parts[1].replace('.', '')
            if not date_var.isdigit() or len(date_var) != 4:
                raise ValueError('Invalid date format')
            day, month = int(date_var[:2]), int(date_var[2:])
            if not (1 <= month <= 12):
                raise ValueError('month must be in 1..12')
            date_obj = datetime(day=day, month=month, year=datetime.now().year)
            month_str = months[date_obj.strftime('%B')]
            day_str = weeks[date_obj.strftime('%A')]
            date_str = f'{day} {month_str} ({day_str})'

            image = create_image_from_database(date_var, db_path)
            if isinstance(image, str):
                send_message(chat_id, image)
            else:
                image_path = f"temp_image_{date_var}.jpg"
                image.save(image_path)
                send_image(event.obj.message['peer_id'], image_path, text=f'Расписание на {date_str}')
                os.remove(image_path)
        except Exception as e:
            print(f'Error: {e}')
            vk.messages.send(peer_id=event.obj.message['peer_id'],
                             message='Расписание на текущий день не найдено. Убедитесь, что формат даты соответствует "ДД.ММ".',
                             random_id=0)


def send_scheduled_message():
    """Отправляет запланированное сообщение во все чаты из списка идентификаторов чата."""
    for chat_id in chat_ids:
        peer_id = 2000000000 + chat_id
        target_day = datetime.now(novosibirsk_tz)
        if target_day.strftime('%A') == 'Sunday':
            continue
        else:
            date_var = target_day.strftime('%d%m')
            image = create_image_from_database(date_var, db_path)
            if isinstance(image, str):
                vk.messages.send(peer_id=peer_id, message=image, random_id=0)
            else:
                image_path = f"temp_image_{date_var}.jpg"
                image.save(image_path)
                send_image(peer_id, image_path, text='Утренняя рассылка.\nРасписание на сегодня:')
                os.remove(image_path)


def start_scheduled_message():
    """Запускает отправку запланированных сообщений каждый день в определенное время."""
    schedule.every().day.at(time_mailing).do(send_scheduled_message)

    while True:
        schedule.run_pending()
        time.sleep(1)


def get_keyboard(today):
    """Возвращает клавиатуру с кнопками обратного вызова для выбора дней недели."""
    global target_day_found
    keyboard = VkKeyboard(inline=True)
    color_mapping = {
        'green': VkKeyboardColor.POSITIVE,
        'red': VkKeyboardColor.NEGATIVE,
        'blue': VkKeyboardColor.PRIMARY,
        'secondary': VkKeyboardColor.SECONDARY
    }

    days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday']
    day_names = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ']
    target_dates = {}
    for i in range(3):
        for j in range(2):
            day_name = days[i * 2 + j]
            day_text = day_names[i * 2 + j]
            for k in range(7):
                target_day = today + timedelta(days=k)
                if target_day.strftime('%A').lower() == day_name:
                    target_day_found = target_day
            target_date = target_day_found.strftime('%d.%m')
            button_text = f'{day_text} {target_date}'
            keyboard.add_callback_button(button_text, color=color_mapping['secondary'], payload={"action": day_name})
            target_dates[day_name] = target_date
        if i != 2:
            keyboard.add_line()

    keyboard.add_line()
    keyboard.add_callback_button('Сегодня', color=color_mapping['green'], payload={"action": "today"})
    keyboard.add_callback_button('Завтра', color=color_mapping['green'], payload={"action": "tomorrow"})

    return keyboard.get_keyboard(), target_dates


def load_chat_ids():
    """Загружает список идентификаторов чата из файла JSON."""
    try:
        with open('chat_ids.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def save_chat_ids(chat_ids):
    """Сохраняет список идентификаторов чата в файле JSON."""
    with open('chat_ids.json', 'w') as f:
        json.dump(chat_ids, f)


def load_logs(limit=None):
    """Загружает список логов из базы данных."""
    if limit is None:
        logs_c.execute("SELECT * FROM logs ORDER BY id DESC")
    else:
        logs_c.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = logs_c.fetchall()
    logs = []
    for row in rows:
        id, timestamp, user_id, first_name, last_name, command = row
        log = {
            'timestamp': timestamp,
            'user_id': user_id,
            'first_name': first_name,
            'last_name': last_name,
            'command': command
        }
        logs.append(log)
    return logs


def add_log(user_id, command, max_logs=30):
    """Добавляет новый лог в базу данных и удаляет самые старые логи, если их количество превышает max_logs."""
    timestamp = datetime.now(novosibirsk_tz).strftime('%H:%M:%S')
    user_info = vk.users.get(user_ids=user_id)[0]
    first_name = user_info['first_name']
    last_name = user_info['last_name']
    logs_c.execute("INSERT INTO logs (timestamp, user_id, first_name, last_name, command) VALUES (?, ?, ?, ?, ?)",
                   (timestamp, user_id, first_name, last_name, command))
    logs_c.execute("SELECT COUNT(*) FROM logs")
    count = logs_c.fetchone()[0]
    if count > max_logs:
        logs_c.execute(f"DELETE FROM logs WHERE id IN (SELECT id FROM logs ORDER BY id ASC LIMIT {count - max_logs})")
    logs_conn.commit()


def format_logs(logs):
    """Форматирует список логов для вывода в сообщении."""
    if not logs:
        return 'Список логов пуст.'
    lines = []
    for log in logs:
        timestamp = log['timestamp']
        user_id = log['user_id']
        first_name = log['first_name']
        last_name = log['last_name']
        command = log['command']
        line = f'▶ {timestamp} [id{user_id}|{first_name} {last_name}]\n{command}'
        lines.append(line)
    return '\n'.join(lines)


def send_logs_to_user(user_id, chat_id, message_text):
    """Отправка логов в личные сообщения."""
    parts = message_text.split()
    limit = 5
    error_sent = False
    if len(parts) == 2:
        try:
            limit = int(parts[1])
        except ValueError:
            send_message(chat_id, 'Неверный аргумент. Укажите число от 1 до 30.')
            error_sent = True
            return False, error_sent
    if limit is not None and not (1 <= limit <= 30):
        send_message(chat_id, 'Неверный аргумент. Укажите число от 1 до 30.')
        error_sent = True
        return False, error_sent
    logs = load_logs(limit)
    formatted_logs = format_logs(logs)
    try:
        vk.messages.send(user_id=user_id, message=f'Последние {len(logs)} действий в боте:\n{formatted_logs}',
                         random_id=0)
        return True, error_sent
    except vk_api.exceptions.ApiError as e:
        if e.code == 901:
            return False, error_sent
        else:
            raise e


def update_flag_by_num(chat_id, message_text):
    """Обновляет флажок администрирования или игнорирования участника в базе данных по его номеру."""
    parts = message_text.split()
    if len(parts) == 3:
        num = int(parts[1])
        flag = 'administrator' if parts[0].lower() == 'админ' else 'ignored'
        value = 1 if parts[2] == '+' else 0
        c.execute("SELECT MIN(id), MAX(id) FROM members")
        min_id, max_id = c.fetchone()
        if min_id <= num <= max_id:
            c.execute("SELECT vk_id FROM members WHERE id=?", (num,))
            row = c.fetchone()
            if row is not None:
                vk_id = row[0]
                c.execute(f"SELECT administrator FROM members WHERE vk_id=?", (vk_id,))
                admin_bd = c.fetchone()[0]
                if flag == 'ignored' and admin_bd == 1 and value == 1:
                    send_message(chat_id, 'Администратор не может игнорироваться ботом')
                else:
                    c.execute(f"UPDATE members SET {flag}=? WHERE vk_id=?", (value, vk_id))
                    if flag == 'administrator' and value == 1:
                        c.execute(f"UPDATE members SET ignored=0 WHERE vk_id=?", (vk_id,))
                    conn.commit()
                    user = vk.users.get(user_ids=vk_id)[0]
                    first_name = user['first_name']
                    last_name = user['last_name']
                    flag_str = 'администратор' if flag == 'administrator' else 'игнорируется ботом'
                    value_str = '' if value == 1 else 'не '
                    send_message(chat_id, f'{first_name} {last_name} теперь {value_str}{flag_str}')
            else:
                send_message(chat_id, f'Пользователь с таким номером не найден в базе')
        else:
            send_message(chat_id, f'Неверный номер пользователя. Используйте: !админ/игнор № +/-')
    else:
        send_message(chat_id, f'Неверный формат команды. Используйте: !админ/игнор № +/-')


months = {
    'January': 'января', 'February': 'февраля', 'March': 'марта',
    'April': 'апреля', 'May': 'мая', 'June': 'июня',
    'July': 'июля', 'August': 'августа', 'September': 'сентября',
    'October': 'октября', 'November': 'ноября', 'December': 'декабря'
}

weeks = {
    'Monday': 'понедельник', 'Tuesday': 'вторник', 'Wednesday': 'среда',
    'Thursday': 'четверг', 'Friday': 'пятница',
    'Saturday': 'суббота', 'Sunday': 'воскресенье'
}

chat_ids = load_chat_ids()
thread = threading.Thread(target=start_scheduled_message)
thread.start()

print("the bot is running")
for event in longpoll.listen():
    if event.type == VkBotEventType.MESSAGE_NEW:
        if event.from_chat:
            chat_id = event.chat_id
            user_id = event.object.message["from_id"]
            message_text = event.object.message["text"].lower()
            if message_text.startswith('!'):
                c.execute("SELECT administrator FROM members WHERE vk_id=?", (user_id,))
                row = c.fetchone()
                if row is not None:
                    administrator = row[0]
                    message_text = message_text[1:].lstrip()

                    if message_text == 'команды':
                        send_message(chat_id, 'Список команд бота:\n▶ !расписание (ДД.ММ) *\n▶ !обновление\n'
                                              '▶ !рассылка ^\n▶ !логи ^\n▶ !админ № +/- ^\n▶ !игнор № +/- ^\n'
                                              '▶ !обновить базу ^\n▶ !инфо (№/ссылка/ответ) ^\n* - не обязательный аргумент\n'
                                              '^ - доступно не всем')
                        add_log(user_id, 'Команда: команды')

                    if message_text.startswith('расписание'):
                        handle_schedule_command(chat_id, message_text, db_path)
                        add_log(user_id, 'Команда: расписание')

                    if message_text == 'обновление':
                        try:
                            with open('time_info.json', 'r') as f:
                                time_info = json.load(f)
                            formatted_time_info = f"▶ Google Диск:\n{time_info['google_drive_last_modified']}\n▶ Таблица:\n" \
                                                  f"{time_info['excel_file_created']}\n▶ Изображения:\n{time_info['images_folder_created']}"
                            send_message(chat_id, formatted_time_info)
                        except Exception as e:
                            send_message(chat_id, f'Произошла ошибка: {e}')
                        add_log(user_id, 'Команда: обновление')

                    if message_text.startswith('рассылка') and (user_id in developer_ids or administrator):
                        save_chat_ids(chat_ids)
                        parts = message_text.split()
                        if len(parts) == 2:
                            if parts[1] == '0':
                                if chat_id in chat_ids:
                                    chat_ids.remove(chat_id)
                                    vk.messages.send(chat_id=chat_id, message="Рассылка отключена", random_id=0)
                                else:
                                    vk.messages.send(chat_id=chat_id, message="Рассылка для этого чата уже отключена",
                                                     random_id=0)
                            elif parts[1] == '1':
                                if chat_id not in chat_ids:
                                    chat_ids.append(chat_id)
                                    vk.messages.send(chat_id=chat_id, message="Рассылка включена на 7:00", random_id=0)
                                else:
                                    vk.messages.send(chat_id=chat_id, message="Рассылка для этого чата уже подключена",
                                                     random_id=0)
                        add_log(user_id, 'Команда: рассылка')

                    if message_text.startswith('логи') and (user_id in developer_ids or administrator):
                        logs_sent, error_sent = send_logs_to_user(user_id, chat_id, message_text)
                        if logs_sent:
                            send_message(chat_id, 'Логи отправлены в личные сообщения.')
                        elif not error_sent:
                            send_message(chat_id, 'Отправьте любое сообщение боту, чтобы получить логи.')
                        add_log(user_id, 'Команда: логи')

                    parts = message_text.split()
                    if (parts[0] == 'админ' or parts[0] == 'игнор') and (user_id in developer_ids or administrator):
                        update_flag_by_num(chat_id, message_text)
                        add_log(user_id, f'Команда: {parts}')

                    if message_text == 'обновить базу' and (user_id in developer_ids or administrator):
                        add_chat_members(vk, chat_id, developer_ids)
                        send_message(chat_id, 'База данных обновлена')
                        add_log(user_id, 'Команда: обновить базу')

                    if message_text.startswith('инфо') and (user_id in developer_ids or administrator):
                        handle_info_command(event, chat_id, message_text)
                        add_log(user_id, 'Команда: инфо')

    # Обработка действий с клавиатурой
    elif event.type == VkBotEventType.MESSAGE_EVENT:
        today = datetime.now()
        keyboard, target_dates = get_keyboard(today)
        user_id = event.object.user_id
        c.execute("SELECT ignored FROM members WHERE vk_id=?", (user_id,))
        row = c.fetchone()
        if row is not None and row[0] == 0:
            if user_id in button_presses:
                time_since_last_press = datetime.now() - button_presses[user_id]
                if time_since_last_press < button_cooldown:
                    continue

            button_presses[user_id] = datetime.now()
            payload = event.object.payload
            action = payload.get('action')

            if action:
                add_log(user_id, f'Действие с клавиатурой: {action}')
                if action in target_dates:
                    target_date = target_dates[action]
                    day, month = map(int, target_date.split('.'))
                    date_obj = datetime(day=day, month=month, year=datetime.now().year)
                    month_str = months[date_obj.strftime('%B')]
                    day_str = weeks[date_obj.strftime('%A')]
                    date_str = f'{day} {month_str} ({day_str})'
                    vk.messages.sendMessageEventAnswer(event_id=event.object.event_id, user_id=event.object.user_id,
                                                       peer_id=event.object.peer_id)
                    date_var = f'{day:02d}{month:02d}'
                    image = create_image_from_database(date_var, db_path)
                    if isinstance(image, str):
                        send_message(event.object.peer_id, image)
                    else:
                        image_path = f"temp_image_{date_var}.jpg"
                        image.save(image_path)
                        send_image(event.object.peer_id, image_path, text=f'Расписание на {date_str}')
                        os.remove(image_path)
                elif action == 'today' or action == 'tomorrow':
                    vk.messages.sendMessageEventAnswer(event_id=event.object.event_id, user_id=event.object.user_id,
                                                       peer_id=event.object.peer_id)
                    if action == 'today':
                        target_day = datetime.now(novosibirsk_tz)
                        action_text = "сегодня"
                    else:
                        target_day = datetime.now(novosibirsk_tz) + timedelta(days=1)
                        action_text = "завтра"
                    if target_day.strftime('%A') == 'Sunday':
                        vk.messages.send(peer_id=event.object.peer_id, message='Выбранный день является выходным',
                                         random_id=0)
                    else:
                        date_var = target_day.strftime('%d%m')
                        image = create_image_from_database(date_var, db_path)
                        if isinstance(image, str):
                            send_message(event.object.peer_id, image)
                        else:
                            image_path = f"temp_image_{date_var}.jpg"
                            image.save(image_path)
                            send_image(event.object.peer_id, image_path, text=f'Расписание на {action_text}')
                            os.remove(image_path)
