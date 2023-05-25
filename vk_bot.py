import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from config import group_id, token, im_font, db_path, time_mailing
import datetime
import time
import sqlite3
import json
import pytz
import os
from PIL import Image, ImageDraw, ImageFont
import threading
import schedule


class MyVkLongPoll(VkBotLongPoll):
    def listen(self):
        reconnected = False
        while True:
            try:
                for event in self.check():
                    if reconnected:
                        print("Переподключение прошло успешно")
                        reconnected = False
                    yield event
            except Exception as e:
                print('error:', e, '\nПовторная попытка переподключения через 10 секунд')
                time.sleep(10)
                reconnected = True


vk_session = vk_api.VkApi(token=token)
vk = vk_session.get_api()
longpoll = MyVkLongPoll(vk_session, group_id)


# Обработка команд и кнопок


def handle_start_command(vk, peer_id):
    """ Функция для обработки команды "начать". Отправляет сообщение с клавиатурой VK с кнопками. """
    vk.messages.send(
        peer_id=peer_id,
        message="Клавиатура с быстрыми командами открыта. Для получения более подробной информации, введите \"помощь\"",
        keyboard=keyboard(),
        random_id=0
    )


def handle_schedule_command(vk, peer_id, date_arg):
    """ Функция для обработки команды "расписание".
    Создает изображение расписания на указанную дату и отправляет его пользователю. """
    if date_arg in ["пн", "вт", "ср", "чт", "пт", "сб"]:
        weekdays = ["пн", "вт", "ср", "чт", "пт", "сб"]
        target_weekday = weekdays.index(date_arg)
        today = datetime.date.today()
        current_weekday = today.weekday()
        delta_days = (target_weekday - current_weekday) % 7
        target_date = today + datetime.timedelta(days=delta_days)
        date = target_date.strftime('%d%m')
    else:
        date = date_arg.replace('.', '')

    image, timestamp = create_image_from_database(date, db_path)
    if isinstance(image, Image.Image):
        temp_file = save_image(image)
        attachment = upload_image(vk, peer_id, temp_file)
        date_text = datetime.datetime.strptime(date, '%d%m').strftime('%d.%m')
        vk.messages.send(
            peer_id=peer_id,
            message=f"Обновлено: {timestamp}\nРасписание на {date_text}:",
            attachment=attachment,
            random_id=0
        )
        delete_image(temp_file)
    else:
        vk.messages.send(
            peer_id=peer_id,
            message=image,
            random_id=0
        )


def handle_day_button(vk, peer_id, button_text):
    """ Функция для обработки нажатия на кнопку дня недели или "сегодня"/"завтра".
    Определяет дату на основе текста кнопки и отправляет расписание на эту дату. """
    date = get_date_from_button(button_text)
    handle_schedule_command(vk, peer_id, date)


def handle_subscription(vk, peer_id):
    """Подписывает или отписывает пользователя на/от рассылку(и)"""
    global subscribers_ids
    subscribers_ids = load_subscribers_ids()
    if peer_id in subscribers_ids:
        subscribers_ids.remove(peer_id)
        save_subscribers_ids(subscribers_ids)
        vk.messages.send(
            peer_id=peer_id,
            message="Вы отписались от рассылки. Чтобы подписаться, введите команду снова",
            random_id=0
        )
    else:
        subscribers_ids.append(peer_id)
        save_subscribers_ids(subscribers_ids)
        vk.messages.send(
            peer_id=peer_id,
            message="Вы подписались на рассылку. Время рассылки 07:00. Чтобы отписаться, введите команду снова",
            random_id=0
        )


def handle_update_command(vk, peer_id):
    """Функция для обработки команды "обновление".
    Загружает информацию об обновлениях из файла time_info.json и отправляет ее пользователю."""
    with open('time_info.json', 'r') as f:
        time_info = json.load(f)
    message = f"▶ Google Диск:\n{time_info['google_drive_last_modified']}\n▶ Таблица:\n" \
              f"{time_info['excel_file_created']}\n▶ Данные:\n{time_info['database_updated']}"
    vk.messages.send(peer_id=peer_id, message=message, random_id=0)


def handle_remove_keyboard_command(vk, peer_id):
    """ Функция для обработки команды "удалить".
    Отправляет сообщение с пустой клавиатурой для удаления текущей клавиатуры. """
    vk.messages.send(
        peer_id=peer_id,
        message="Клавиатура скрыта",
        keyboard=VkKeyboard.get_empty_keyboard(),
        random_id=0
    )


def handle_week_schedule_command(vk, peer_id):
    attachments = []
    weekdays = ["пн", "вт", "ср", "чт", "пт", "сб"]
    for weekday in weekdays:
        target_weekday = weekdays.index(weekday)
        today = datetime.date.today()
        current_weekday = today.weekday()
        delta_days = (target_weekday - current_weekday) % 7
        target_date = today + datetime.timedelta(days=delta_days)
        date = target_date.strftime('%d%m')
        image, timestamp = create_image_from_database(date, db_path)
        if isinstance(image, Image.Image):
            temp_file = save_image(image)
            attachment = upload_image(vk, peer_id, temp_file)
            attachments.append(attachment)
            delete_image(temp_file)
    vk.messages.send(
        peer_id=peer_id,
        message="Расписание на неделю:",
        attachment=','.join(attachments),
        random_id=0
    )


def handle_help_command(vk, peer_id):
    """Функция для обработки команды "помощь". Отправляет сообщение с информацией о доступных командах бота."""
    help_message = """
Доступные команды:
▶ "начать": открывает клавиатуру с быстрыми командами, доступно только в ЛС с ботом
▶ "расп ДД.ММ/день недели": отправляет расписание на указанную дату
▶ "р неделя": отправляет расписание на неделю, доступно только в ЛС с ботом
▶ "время": отправляет время начала и икончания занятий
▶ "рассылка": подписывает или отписывает пользователя от рассылки расписания
▶ "обновления": отправляет информацию об обновлениях
▶ "удалить": скрывает клавиатуру с быстрыми командами
P.S. В беседе команды начинаются с !
    """
    vk.messages.send(
        peer_id=peer_id,
        message=help_message,
        random_id=0
    )


def handle_timing_command(vk, peer_id):
    """Функция для обработки команды "тайминг". Отправляет сообщение с распорядком дня."""
    timing_message = """
Время занятий
Категория «Раздуплиться бы»:
1️⃣ 08:00-09:30
2️⃣ 09:50-11:20
3️⃣ 11:40-13:10
4️⃣ 13:30-15:00
Категория «Боже упаси...»:
5️⃣ 15:20-16:50
6️⃣ 17:10-18:40
7️⃣ 19:00-20:30
    """
    vk.messages.send(
        peer_id=peer_id,
        message=timing_message,
        random_id=0
    )


# Работа с расписанием


def create_image_from_database(date, db_path):
    """Создаёт изображения по заданным данным. """
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT matrix, timestamp FROM data WHERE date=?", (date,))
    result = c.fetchone()
    conn.close()

    if result is None:
        return get_schedule_message(date)

    matrix = json.loads(result[0])
    timestamp = result[1]

    image_height = 420
    image_width = 700
    image = Image.new('RGB', (image_width, image_height), '#fff2e0')
    draw = ImageDraw.Draw(image)

    year = datetime.datetime.now().year
    date_obj = datetime.datetime.strptime(f"{date}{year}", '%d%m%Y')
    weekdays = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]
    weekday_text = weekdays[date_obj.weekday()]
    date_text = date_obj.strftime('%d.%m')
    text = f"{weekday_text} {date_text}"
    text_color = "#ededed"
    text_size = 120
    text_font = ImageFont.truetype(im_font, text_size)

    text_bbox = draw.textbbox((0, 0), text, font=text_font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]

    text_x = (image_width - text_width) // 2
    text_y = (image_height - text_height) // 2 - 20

    draw.text((text_x, text_y), text, fill=text_color, font=text_font)

    font = ImageFont.truetype(im_font, 14)

    x_offset = 20
    y_offset = 20

    row_height = 30
    first_column_width = 600
    text_x_offset = -10
    text_y_offset = 10
    column_spacing = 20

    for i in range(len(matrix)):
        line_width = 2 if i % 2 == 0 else 1
        draw.line((0, y_offset + i * row_height - (row_height if i == 0 else 0) - y_offset, image.width,
                   y_offset + i * row_height - (row_height if i == 0 else 0) - y_offset), fill='gray',
                  width=line_width)

        draw.line((x_offset + first_column_width, y_offset - y_offset,
                   x_offset + first_column_width,
                   y_offset + len(matrix) * row_height - y_offset), fill='gray', width=3)

        for col_index, cell_value in enumerate(matrix[i]):
            if col_index == 0 and len(cell_value) > 100:
                cell_value = cell_value[:90] + '...' + cell_value[-10:]
            draw.text((x_offset + col_index * (first_column_width + column_spacing) + text_x_offset,
                       y_offset + i * row_height - text_y_offset), str(cell_value),
                      fill='black', font=font)

    return image, timestamp


def get_schedule_message(date):
    """ Функция для получения сообщения об ошибке или отсутствии расписания на указанную дату. """
    if len(date) == 4 and date.isdigit():
        date_text = f"{date[:2]}.{date[2:]}"
        try:
            year = datetime.datetime.now().year
            date_obj = datetime.datetime.strptime(f"{date_text}.{year}", '%d.%m.%Y')
            if date_obj.weekday() == 6:
                return "На воскресенье расписания нет", None
            else:
                return f"Кажется, на {date_text} расписания нет", None
        except ValueError:
            return "Вы ввели неверный аргумент, введите \"расписание ДД.ММ/день недели\"", None
    else:
        return "Вы ввели неверный аргумент, введите \"расписание ДД.ММ/день недели\"", None


# Работа с изображениями


def save_image(image):
    """ Функция для сохранения изображения во временный файл. """
    temp_file = 'temp_image.jpg'
    image.save(temp_file)
    return temp_file


def delete_image(image_path):
    """ Функция для удаления временного файла изображения. """
    if os.path.exists(image_path):
        os.remove(image_path)


def upload_image(vk, peer_id, image_path):
    """Отправка изображение на сервер ВКонтакте. """
    upload = vk_api.VkUpload(vk)
    photo = upload.photo_messages(image_path)[0]
    owner_id = photo['owner_id']
    photo_id = photo['id']
    attachment = f'photo{owner_id}_{photo_id}'
    return attachment


# Работа с подписками


def send_scheduled_message():
    """Отправляет запланированное сообщение всем пользователям и беседам из списка идентификаторов."""
    print(f"Рассылка: {time_mailing}")
    global subscribers_ids
    subscribers_ids = load_subscribers_ids()
    for peer_id in subscribers_ids:
        target_day = datetime.datetime.now()
        if target_day.strftime('%A') == 'Sunday':
            continue
        else:
            date_var = target_day.strftime('%d%m')
            image, timestamp = create_image_from_database(date_var, db_path)
            if isinstance(image, str):
                vk.messages.send(peer_id=peer_id, message=image, random_id=0)
            else:
                temp_file = save_image(image)
                attachment = upload_image(vk, peer_id, temp_file)
                vk.messages.send(
                    peer_id=peer_id,
                    message=f"Обновлено: {timestamp}\nУтренняя рассылка 🥱\nЧтобы отписаться от рассылки, "
                            f"используйте команду \"рассылка\"\n[https://vk.me/club219271967|Расписание] на сегодня:",
                    attachment=attachment,
                    random_id=0
                )
                delete_image(temp_file)


def start_scheduled_message():
    """Запускает отправку запланированных сообщений каждый день в определенное время."""
    schedule.every().day.at(time_mailing).do(send_scheduled_message)

    while True:
        schedule.run_pending()
        time.sleep(5)


def load_subscribers_ids():
    """Загружает список идентификаторов пользователей и бесед из файла JSON."""
    try:
        with open('subscribers_ids.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        with open('subscribers_ids.json', 'w') as f:
            json.dump([], f)
        return []


def save_subscribers_ids(subscribers_ids):
    """Сохраняет список идентификаторов пользователей и бесед в файле JSON."""
    with open('subscribers_ids.json', 'w') as f:
        json.dump(subscribers_ids, f)


# Создание клавиатуры


def keyboard():
    """Функция для создания и возврата клавиатуры VK с кнопками. """
    kb = VkKeyboard(one_time=False)
    kb.add_button("ПН 💀", color=VkKeyboardColor.SECONDARY)
    kb.add_button("ВТ 🤕", color=VkKeyboardColor.PRIMARY)
    kb.add_button("СР 😑", color=VkKeyboardColor.SECONDARY)
    kb.add_button("Сегодня", color=VkKeyboardColor.POSITIVE)
    kb.add_line()
    kb.add_button("ЧТ 😖", color=VkKeyboardColor.PRIMARY)
    kb.add_button("ПТ 🍺", color=VkKeyboardColor.SECONDARY)
    kb.add_button("СБ 🥲", color=VkKeyboardColor.PRIMARY)
    kb.add_button("Завтра", color=VkKeyboardColor.POSITIVE)
    kb.add_line()
    kb.add_openlink_button("Свериться с таблицей 🤨",
                           "https://docs.google.com/spreadsheets/d/1Dtj-BZEOSwNFHKouInetUhtTmxKKl1Rp/edit#gid=1436307775",)
    return kb.get_keyboard()


def get_date_from_button(button_text):
    """Определение даты. """
    button_text = button_text.lower()
    novosibirsk_tz = pytz.timezone('Asia/Novosibirsk')
    today = datetime.datetime.now(novosibirsk_tz).date()
    if button_text == "сегодня":
        return today.strftime('%d%m')
    elif button_text == "завтра":
        tomorrow = today + datetime.timedelta(days=1)
        return tomorrow.strftime('%d%m')
    else:
        if button_text in days_with_emoji:
            weekdays = days_with_emoji
        elif button_text in days_without_emoji:
            weekdays = days_without_emoji
        else:
            return None
        target_weekday = weekdays.index(button_text)
        current_weekday = today.weekday()
        delta_days = (target_weekday - current_weekday) % 7
        target_date = today + datetime.timedelta(days=delta_days)
        return target_date.strftime('%d%m')


# Словарь значений


days = {
    "with_emoji": ["пн 💀", "вт 🤕", "ср 😑", "чт 😖", "пт 🍺", "сб 🥲"],
    "without_emoji": ["пн", "вт", "ср", "чт", "пт", "сб"],
    "today_tomorrow": ["сегодня", "завтра"]
}

days_with_emoji = days["with_emoji"]
days_without_emoji = days["without_emoji"]
today_tomorrow = days["today_tomorrow"]


# Основная функция


def main():
    for event in longpoll.listen():
        if event.type == VkBotEventType.MESSAGE_NEW:
            message_text = event.obj.message['text'].lower()
            peer_id = event.obj.message['peer_id']
            not_chat = peer_id < 2000000000
            if not not_chat:
                if not message_text.startswith('!'):
                    continue
                message_text = message_text[1:].lstrip()
            else:
                if message_text.startswith('!'):
                    message_text = message_text[1:].lstrip()

            # Команды бота

            if message_text == "начать" and not_chat:
                handle_start_command(vk, peer_id)
            elif message_text.startswith("расп"):
                message_parts = message_text.split()
                if len(message_parts) < 2:
                    vk.messages.send(peer_id=peer_id, message="Вы не указали аргумент ДД.ММ/день недели", random_id=0)
                else:
                    date = message_parts[1].replace('.', '')
                    handle_schedule_command(vk, peer_id, date)
            elif message_text == "р неделя" and not_chat:
                vk.messages.send(peer_id=peer_id, message="Секундочку . . .", random_id=0)
                handle_week_schedule_command(vk, peer_id)
            elif message_text in days_with_emoji + days_without_emoji + today_tomorrow:
                handle_day_button(vk, peer_id, message_text.lstrip('!'))
            elif message_text == "рассылка":
                handle_subscription(vk, peer_id)
            elif message_text == "обновления":
                handle_update_command(vk, peer_id)
            elif message_text == "удалить":
                handle_remove_keyboard_command(vk, peer_id)
            elif message_text == "помощь" or message_text == "команды":
                handle_help_command(vk, peer_id)
            elif message_text == "лс" and not not_chat:
                vk.messages.send(peer_id=peer_id, message="Удобней [https://vk.me/club219271967|ТУТ]", random_id=0)
            elif message_text == "время":
                handle_timing_command(vk, peer_id)


if __name__ == "__main__":
    print("Бот запущен")
    subscribers_ids = load_subscribers_ids()
    threading.Thread(target=start_scheduled_message).start()
    while True:
        try:
            main()
        except Exception as e:
            print(f"Произошла ошибка: {e}")
