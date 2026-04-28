from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

from utils.tray_common import (
    FIRST_RUN_MARKER, ensure_dirs, load_config, log,
    start_proxy, stop_proxy, tg_proxy_url
)

_config: dict = {}
_exiting = False
_win_mutex_handle = None
_ERROR_ALREADY_EXISTS = 183


def _acquire_win_mutex() -> bool | None:
    global _win_mutex_handle
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        handle = kernel32.CreateMutexW(None, True, "Local\\TgWsProxy_SingleInstance")
        if kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            return False
        if not handle: return None
        _win_mutex_handle = handle
        return True
    except Exception:
        return None


def _release_win_mutex() -> None:
    global _win_mutex_handle
    if _win_mutex_handle:
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.ReleaseMutex(ctypes.c_void_p(_win_mutex_handle))
            kernel32.CloseHandle(ctypes.c_void_p(_win_mutex_handle))
        except Exception:
            pass
        _win_mutex_handle = None


def _on_proxy_error(error_msg: str):
    log.error(f"Proxy Error: {error_msg}")


def main():
    global _config

    if not _acquire_win_mutex():
        print("Application is already running.")
        sys.exit(0)

    ensure_dirs()

    is_first_run = FIRST_RUN_MARKER.exists()

    _config = load_config()

    try:
        start_proxy(_config, on_error=_on_proxy_error)
        log.info("Proxy started successfully.")

        if is_first_run:
            link = tg_proxy_url(_config)
            if link:
                log.info(f"First run: opening {link}")
                webbrowser.open(link)
            try:
                FIRST_RUN_MARKER.unlink()
            except Exception:
                pass

        while not _exiting:
            time.sleep(1)

    except KeyboardInterrupt:
        log.info("Shutting down...")
    finally:
        stop_proxy()
        _release_win_mutex()


if __name__ == "__main__":
    main()
