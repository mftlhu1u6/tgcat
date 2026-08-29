#!/usr/bin/env python3
import asyncio
import io
import json
import logging
import os
import signal
import sys
from datetime import datetime, timedelta

import aiohttp
import asyncssh
from aiohttp_socks import ProxyConnector
from telethon import TelegramClient, types
from telethon.tl.functions.photos import (
    DeletePhotosRequest,
    GetUserPhotosRequest,
    UploadProfilePhotoRequest,
)

config_path = os.path.join(os.path.dirname(__file__), "config.json")
counter_path = os.path.join(os.path.dirname(__file__), "counter.txt")

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger("tgcat")


def load_config() -> dict:
    if not os.path.exists(config_path):
        default_cfg = {
            "api_id": 1234567,
            "api_hash": "your_api_hash_here",
            "session_name": "tgcat_session",
            "channel_id": "@your_channel_username",
            "post_caption_template": "#{counter}",
            "delete_old_avatar": false,
            "prep_seconds_before": 30,
            "target_minutes": [0, 15, 30, 45],
            "cat_api_key": "",
            "ssh_tunnel": {
                "enabled": false,
                "host": "1.2.3.4",
                "port": 22,
                "username": "root",
                "password": "",
                "local_port": 10808
            },
            "proxy": {
                "enabled": false,
                "protocol": "socks5",
                "ip": "1.2.3.4",
                "port": 10808,
                "username": "",
                "password": ""
            }
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(default_cfg, f, indent=2, ensure_ascii=False)
        logger.info("created default config.json, please fill api_id and api_hash and run again")
        sys.exit(0)
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_counter() -> int:
    if not os.path.exists(counter_path):
        return 1
    try:
        with open(counter_path, "r", encoding="utf-8") as f:
            content = f.read().strip().lstrip("#").strip()
            return int(content) if content else 1
    except Exception:
        return 1


def save_counter(value: int) -> None:
    tmp_path = counter_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(f"{value}\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, counter_path)


def parse_channel_id(target):
    if not target or target == "@your_channel_username":
        return None
    if isinstance(target, int):
        return target
    s = str(target).strip()
    if (s.startswith("-") and s[1:].isdigit()) or s.isdigit():
        return int(s)
    return s


async def start_ssh_tunnel(cfg: dict):
    ssh_cfg = cfg.get("ssh_tunnel", {})
    if not ssh_cfg.get("enabled"):
        return None, None

    host = ssh_cfg.get("host")
    port = int(ssh_cfg.get("port", 22))
    username = ssh_cfg.get("username", "root")
    password = ssh_cfg.get("password") or None
    local_port = int(ssh_cfg.get("local_port", 10808))

    logger.info("connecting ssh tunnel to %s:%d (user: %s)...", host, port, username)
    try:
        conn = await asyncssh.connect(
            host,
            port=port,
            username=username,
            password=password,
            known_hosts=None,
            keepalive_interval=30,
            keepalive_count_max=3,
        )
        listener = await conn.forward_socks("127.0.0.1", local_port)
        logger.info("ssh tunnel established (local socks5 on 127.0.0.1:%d)", local_port)
        return conn, listener
    except Exception as e:
        logger.error("ssh tunnel failed: %s", e)
        raise


async def ensure_ssh_tunnel(cfg: dict, ssh_conn, ssh_listener):
    if not cfg.get("ssh_tunnel", {}).get("enabled"):
        return None, None

    if ssh_conn is not None and not ssh_conn.is_closed():
        return ssh_conn, ssh_listener

    if ssh_conn is not None and ssh_conn.is_closed():
        logger.warning("ssh tunnel dropped, reconnecting...")

    if ssh_listener:
        ssh_listener.close()
    if ssh_conn:
        ssh_conn.close()

    return await start_ssh_tunnel(cfg)


def get_runtime_proxy(cfg: dict, ssh_listener=None) -> dict:
    if ssh_listener:
        ssh_cfg = cfg.get("ssh_tunnel", {})
        local_port = int(ssh_cfg.get("local_port", 10808))
        return {
            "enabled": True,
            "protocol": "socks5",
            "ip": "127.0.0.1",
            "port": local_port,
            "username": "",
            "password": "",
        }
    return cfg.get("proxy", {"enabled": False})


def get_telethon_proxy(proxy_cfg: dict):
    if not proxy_cfg.get("enabled"):
        return None
    p_type = proxy_cfg.get("protocol", "socks5").lower()
    proxy = {
        "proxy_type": p_type,
        "addr": proxy_cfg["ip"],
        "port": int(proxy_cfg["port"]),
    }
    if proxy_cfg.get("username"):
        proxy["username"] = proxy_cfg["username"]
    if proxy_cfg.get("password"):
        proxy["password"] = proxy_cfg["password"]
    return proxy


def get_aiohttp_connector(proxy_cfg: dict) -> aiohttp.BaseConnector:
    if not proxy_cfg.get("enabled"):
        return aiohttp.TCPConnector()
    proto = proxy_cfg.get("protocol", "socks5").lower()
    ip = proxy_cfg["ip"]
    port = proxy_cfg["port"]
    user = proxy_cfg.get("username")
    pwd = proxy_cfg.get("password")

    auth_str = f"{user}:{pwd}@" if user and pwd else ""
    proxy_url = f"{proto}://{auth_str}{ip}:{port}"
    return ProxyConnector.from_url(proxy_url)


def is_valid_image(data: bytes) -> bool:
    if len(data) < 1024:
        return False
    # jpeg, png, webp magic byte signatures
    if data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"RIFF"):
        return True
    return False


async def check_proxy_and_fetch_cat(
    proxy_cfg: dict, retries: int = 3, timeout_per_try: int = 8, cat_api_key: str | None = None
) -> bytes | None:
    proxy_enabled = proxy_cfg.get("enabled", False)
    headers = {}
    if cat_api_key:
        headers["x-api-key"] = cat_api_key.strip()

    for attempt in range(1, retries + 1):
        try:
            connector = get_aiohttp_connector(proxy_cfg)
            timeout = aiohttp.ClientTimeout(total=timeout_per_try)
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                try:
                    async with session.get(
                        "https://api.thecatapi.com/v1/images/search?mime_types=jpg,png",
                        headers=headers,
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data and "url" in data[0]:
                                image_url = data[0]["url"]
                                async with session.get(image_url) as img_resp:
                                    if img_resp.status == 200:
                                        img_bytes = await img_resp.read()
                                        if is_valid_image(img_bytes):
                                            if proxy_enabled:
                                                logger.info("proxy connected successfully (%s:%s)", proxy_cfg["ip"], proxy_cfg["port"])
                                            return img_bytes
                except Exception as e:
                    logger.warning("thecatapi error (%s), trying cataas.com", e)

                async with session.get("https://cataas.com/cat?json=false") as resp:
                    if resp.status == 200:
                        img_bytes = await resp.read()
                        if is_valid_image(img_bytes):
                            if proxy_enabled:
                                logger.info("proxy connected successfully (%s:%s)", proxy_cfg["ip"], proxy_cfg["port"])
                            return img_bytes
                    raise RuntimeError(f"http {resp.status} or invalid image data")
        except Exception as e:
            logger.warning("proxy check attempt %d/%d failed: %s", attempt, retries, e)
            if attempt < retries:
                await asyncio.sleep(1)

    return None


def get_next_target_time(target_minutes: list[int]) -> datetime:
    now = datetime.now()
    if not target_minutes:
        target_minutes = [0, 15, 30, 45]
    candidates = []
    for m in sorted(target_minutes):
        cand = now.replace(minute=m, second=0, microsecond=0)
        if cand > now:
            candidates.append(cand)

    if candidates:
        return candidates[0]

    return (now + timedelta(hours=1)).replace(minute=min(target_minutes), second=0, microsecond=0)


async def sleep_until_exact_second(target_time: datetime):
    now = datetime.now()
    coarse_sleep = (target_time - now).total_seconds() - 0.05
    if coarse_sleep > 0:
        await asyncio.sleep(coarse_sleep)

    # sub-millisecond spin to hit :01.000 exactly
    while datetime.now() < target_time:
        await asyncio.sleep(0.001)


async def delete_previous_avatars(client: TelegramClient):
    try:
        photos = await client(GetUserPhotosRequest(user_id="me", offset=0, max_id=0, limit=10))
        if photos and len(photos.photos) > 1:
            old_photos = [p for p in photos.photos[1:] if isinstance(p, types.Photo)]
            if old_photos:
                to_delete = [
                    types.InputPhoto(id=p.id, access_hash=p.access_hash, file_reference=p.file_reference)
                    for p in old_photos
                ]
                await client(DeletePhotosRequest(id=to_delete))
                logger.info("cleaned %d old avatar(s)", len(to_delete))
    except Exception as e:
        logger.warning("failed to clean old avatars: %s", e)


async def execute_round(client: TelegramClient, cfg: dict, proxy_cfg: dict, target_time: datetime):
    logger.info("prep target: %s", target_time.strftime("%H:%M:%S"))

    cat_bytes = await check_proxy_and_fetch_cat(
        proxy_cfg, retries=3, timeout_per_try=8, cat_api_key=cfg.get("cat_api_key")
    )
    if not cat_bytes:
        logger.error("proxy unavailable after 3 retries, skipping round until next interval")
        return

    logger.info("image downloaded (%d bytes)", len(cat_bytes))

    try:
        file_obj = io.BytesIO(cat_bytes)
        file_obj.name = "cat.jpg"
        try:
            input_file = await client.upload_file(file_obj)
            logger.info("image pre-uploaded to telegram")
        finally:
            file_obj.close()
    except Exception as e:
        logger.error("pre-upload failed: %s", e)
        return

    if not client.is_connected():
        logger.info("reconnecting client to telegram...")
        await client.connect()

    now = datetime.now()
    time_diff = (target_time - now).total_seconds()

    if time_diff < -2.0:
        logger.warning("missed target tick during prep (lag: %.2fs), aborting", -time_diff)
        return

    # target second :01 to ensure telegram server clock registers exact target minute
    fire_time = target_time + timedelta(seconds=1)
    logger.info("waiting until target tick %s", fire_time.strftime("%H:%M:%S"))
    await sleep_until_exact_second(fire_time)

    commit_start = datetime.now()
    logger.info("commit tick: %s", commit_start.strftime("%H:%M:%S.%f")[:12])

    photo_res = None
    sent_msg = None
    channel_target = parse_channel_id(cfg.get("channel_id"))
    counter = get_counter()
    caption_tpl = cfg.get("post_caption_template", "#{counter}")
    caption = caption_tpl.replace("{counter}", str(counter))

    try:
        photo_res = await client(UploadProfilePhotoRequest(file=input_file))
        logger.info("profile photo applied")

        if channel_target:
            post_media = photo_res.photo if hasattr(photo_res, "photo") and photo_res.photo else input_file
            sent_msg = await client.send_message(channel_target, caption, file=post_media)
            logger.info("channel post sent: %s (id: %d)", caption, sent_msg.id)
    except Exception as e:
        logger.error("commit failed: %s", e)

    commit_end = datetime.now()
    is_in_exact_target_minute = (commit_end.hour, commit_end.minute) == (target_time.hour, target_time.minute)

    if is_in_exact_target_minute:
        save_counter(counter + 1)
        logger.info("done, next counter: %d (finished at %s)", counter + 1, commit_end.strftime("%H:%M:%S"))

        if cfg.get("delete_old_avatar", True):
            await delete_previous_avatars(client)
    else:
        logger.warning("rollback triggered (time: %s, target: %s)", commit_end.strftime("%H:%M:%S"), target_time.strftime("%H:%M:%S"))
        if sent_msg and channel_target:
            try:
                await client.delete_messages(channel_target, [sent_msg.id])
                logger.info("rollback: deleted channel post")
            except Exception as e:
                logger.error("rollback delete post error: %s", e)

        if photo_res and hasattr(photo_res, "photo") and isinstance(photo_res.photo, types.Photo):
            try:
                p = photo_res.photo
                in_p = types.InputPhoto(id=p.id, access_hash=p.access_hash, file_reference=p.file_reference)
                await client(DeletePhotosRequest(id=[in_p]))
                logger.info("rollback: removed uploaded avatar")
            except Exception as e:
                logger.error("rollback remove avatar error: %s", e)


async def main():
    cfg = load_config()

    ssh_conn, ssh_listener = None, None
    ssh_conn, ssh_listener = await ensure_ssh_tunnel(cfg, ssh_conn, ssh_listener)

    active_proxy = get_runtime_proxy(cfg, ssh_listener)
    telethon_proxy = get_telethon_proxy(active_proxy)

    if active_proxy.get("enabled"):
        logger.info("proxy active: %s://%s:%s", active_proxy.get("protocol", "socks5"), active_proxy["ip"], active_proxy["port"])

    session_name = cfg.get("session_name", "tgcat_session")
    session_file = os.path.join(os.path.dirname(__file__), session_name)

    client = TelegramClient(
        session_file,
        cfg["api_id"],
        cfg["api_hash"],
        proxy=telethon_proxy,
    )

    logger.info("starting telegram client")
    await client.start()
    logger.info("authorized")

    prep_seconds = cfg.get("prep_seconds_before", 30)
    target_minutes = cfg.get("target_minutes", [0, 15, 30, 45])

    stop_event = asyncio.Event()

    def handle_signal():
        logger.info("shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            pass

    while not stop_event.is_set():
        try:
            ssh_conn, ssh_listener = await ensure_ssh_tunnel(cfg, ssh_conn, ssh_listener)
            active_proxy = get_runtime_proxy(cfg, ssh_listener)

            target_time = get_next_target_time(target_minutes)
            prep_time = target_time - timedelta(seconds=prep_seconds)
            now = datetime.now()

            wait_until_prep = (prep_time - now).total_seconds()
            if wait_until_prep > 0:
                logger.info(
                    "next: %s, sleep %.1fs until prep (%s)",
                    target_time.strftime("%H:%M:%S"),
                    wait_until_prep,
                    prep_time.strftime("%H:%M:%S"),
                )
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=wait_until_prep)
                    break
                except asyncio.TimeoutError:
                    pass

            if stop_event.is_set():
                break

            await execute_round(client, cfg, active_proxy, target_time)

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass

        except Exception as e:
            logger.error("main loop exception: %s", e, exc_info=True)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=10)
            except asyncio.TimeoutError:
                pass

    logger.info("disconnecting client...")
    await client.disconnect()

    if ssh_listener:
        ssh_listener.close()
    if ssh_conn:
        ssh_conn.close()
        await ssh_conn.wait_closed()

    logger.info("shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
