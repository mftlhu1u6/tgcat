# tgcat

[![python](https://img.shields.io/badge/python-3.10+-blue?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![telethon](https://img.shields.io/badge/telethon-1.36+-2BA6E1?style=flat&logo=telegram&logoColor=white)](https://github.com/LonamiWebs/Telethon)
[![platform](https://img.shields.io/badge/platform-linux%20%7C%20raspberry_pi-c51a4a?style=flat&logo=raspberrypi&logoColor=white)](https://www.raspberrypi.com/)
[![license](https://img.shields.io/badge/license-GPLv3-blue?style=flat)](LICENSE)

Скрипт для автоматической смены аватарки профиля в Telegram на случайные фотографии котов и публикации их в канал по расписанию (`:00`, `:15`, `:30`, `:45`).

## Возможности

- Смена аватарки профиля через Telethon MTProto.
- Публикация фото в канал с настраиваемым счетчиком.
- Встроенный зашифрованный SSH-туннель для надежного обхода блокировок.
- Поддержка SOCKS5 и HTTP прокси с авторизацией, а также прямого подключения.
- Предварительная загрузка за 30 секунд до наступления интервала.
- Автоматический откат (удаление поста и фото), если операция не уложилась в тайминг.
- Валидация форматов (JPEG, PNG, WEBP) и проверка целостности файлов.

## Установка

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Настройка

При первом запуске скрипт автоматически создаст шаблон `config.json`.
Заполните в нем свои данные:
- `api_id` и `api_hash`: ключи приложения с сайта my.telegram.org.
- `channel_id`: юзернейм или ID канала.
- `target_minutes`: список минут каждого часа для смены аватарок (по умолчанию `[0, 15, 30, 45]`).
- `delete_old_avatar`: удалять ли предыдущие аватарки из профиля (`false` сохраняет историю).
- `stop_on_flood_wait`: экстренная остановка при получении ограничения FloodWait для защиты аккаунта (по умолчанию `true`).
- `cat_api_key`: бесплатный API-ключ от thecatapi.com (необязательно, для доступа ко всей базе фото).
- `ssh_tunnel`: параметры встроенного SSH-туннеля для обхода блокировок.
- `proxy`: параметры стороннего SOCKS5 или HTTP прокси.

Файлы `counter.txt` и сессия `*.session` также создаются скриптом автоматически.

## Запуск

```bash
tmux new -s tgcat
source venv/bin/activate
python main.py
```

При первом запуске скрипт запросит номер телефона и код авторизации Telegram.
- Отключиться от tmux: `Ctrl + B`, затем `D`.
- Вернуться в сессию: `tmux attach -t tgcat`.
