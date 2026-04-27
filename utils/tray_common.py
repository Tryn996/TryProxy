from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import psutil

from proxy import __version__, get_link_host, parse_dc_ip_list, proxy_config
from proxy.tg_ws_proxy import _run
from utils.default_config import default_tray_config

log = logging.getLogger("tg-ws-tray")

APP_NAME = "TgWsProxy"

def _app_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME

APP_DIR = _app_dir()
CONFIG_FILE = APP_DIR / "config.json"
LOG_FILE = APP_DIR / "proxy.log"
FIRST_RUN_MARKER = APP_DIR / ".first_run_done_mtproto"
IPV6_WARN_MARKER = APP_DIR / ".ipv6_warned"

DEFAULT_CONFIG: Dict[str, Any] = default_tray_config()
IS_FROZEN = bool(getattr(sys, "frozen", False))

def ensure_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)

def load_config() -> dict:
    ensure_dirs()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                data.setdefault(k, v)
            return data
        except Exception as exc:
            log.warning("Failed to load config: %s", repr(exc))
    return dict(DEFAULT_CONFIG)

def save_config(cfg: dict) -> None:
    ensure_dirs()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

_proxy_thread: Optional[threading.Thread] = None
_async_stop: Optional[Tuple[asyncio.AbstractEventLoop, asyncio.Event]] = None

def _run_proxy_thread(on_port_busy: Callable[[str], None]) -> None:
    global _async_stop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    stop_ev = asyncio.Event()
    _async_stop = (loop, stop_ev)
    try:
        loop.run_until_complete(_run(stop_event=stop_ev))
    except Exception as exc:
        log.error("Proxy thread crashed: %s", repr(exc))
        if "Address already in use" in str(exc) or "10048" in str(exc):
            on_port_busy("Порт уже используется другим приложением.")
    finally:
        loop.close()
        _async_stop = None

def apply_proxy_config(cfg: dict) -> bool:
    dc_ip_list = cfg.get("dc_ip", DEFAULT_CONFIG["dc_ip"])
    try:
        dc_redirects = parse_dc_ip_list(dc_ip_list)
    except ValueError as e:
        log.error("Bad config dc_ip: %s", e)
        return False
    pc = proxy_config
    pc.port = cfg.get("port", DEFAULT_CONFIG["port"])
    pc.host = cfg.get("host", DEFAULT_CONFIG["host"])
    pc.secret = cfg.get("secret", DEFAULT_CONFIG["secret"])
    pc.dc_redirects = dc_redirects
    pc.buffer_size = max(4, cfg.get("buf_kb", DEFAULT_CONFIG["buf_kb"])) * 1024
    pc.pool_size = max(0, cfg.get("pool_size", DEFAULT_CONFIG["pool_size"]))
    pc.fallback_cfproxy = cfg.get("cfproxy", DEFAULT_CONFIG["cfproxy"])
    pc.fallback_cfproxy_priority = cfg.get("cfproxy_priority", DEFAULT_CONFIG["cfproxy_priority"])
    pc.cfproxy_user_domain = cfg.get("cfproxy_user_domain", DEFAULT_CONFIG["cfproxy_user_domain"])
    return True

def start_proxy(cfg: dict, on_error: Callable[[str], None]) -> None:
    global _proxy_thread
    if _proxy_thread and _proxy_thread.is_alive(): return
    if not apply_proxy_config(cfg):
        on_error("Ошибка конфигурации.")
        return
    _proxy_thread = threading.Thread(target=_run_proxy_thread, args=(on_error,), daemon=True)
    _proxy_thread.start()

def stop_proxy() -> None:
    global _async_stop
    if _async_stop:
        loop, stop_ev = _async_stop
        loop.call_soon_threadsafe(stop_ev.set)

def tg_proxy_url(cfg: dict) -> str:
    host = cfg.get("host")
    if not host or host in ("0.0.0.0", "::"): host = get_link_host()
    port = cfg.get("port", DEFAULT_CONFIG["port"])
    secret = cfg.get("secret", DEFAULT_CONFIG["secret"])
    return f"https://t.me{host}&port={port}&secret={secret}"
