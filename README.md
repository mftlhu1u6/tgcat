# tgcat

[![python](https://img.shields.io/badge/python-3.10+-blue?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![telethon](https://img.shields.io/badge/telethon-1.36+-2BA6E1?style=flat&logo=telegram&logoColor=white)](https://github.com/LonamiWebs/Telethon)
[![platform](https://img.shields.io/badge/platform-linux%20%7C%20raspberry_pi-c51a4a?style=flat&logo=raspberrypi&logoColor=white)](https://www.raspberrypi.com/)
[![license](https://img.shields.io/badge/license-MIT-green?style=flat)](LICENSE)

Скрипт для автоматической смены аватарки профиля в Telegram на случайные фотографии котов и публикации их в канал по расписанию (`:00`, `:20`, `:40`).

## Возможности

- Смена аватарки профиля через Telethon MTProto.
- Публикация фото в канал с настраиваемым счетчиком.
- Поддержка SOCKS5 и HTTP прокси с авторизацией.
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

Заполните параметры в файле `config.json`:
- `api_id` и `api_hash`: ключи приложения с сайта my.telegram.org.
- `channel_id`: юзернейм или ID канала.
- `proxy`: параметры SOCKS5 или HTTP прокси.

## Запуск

```bash
tmux new -s tgcat
source venv/bin/activate
python main.py
```

При первом запуске скрипт запросит номер телефона и код авторизации Telegram.
- Отключиться от tmux: `Ctrl + B`, затем `D`.
- Вернуться в сессию: `tmux attach -t tgcat`.
