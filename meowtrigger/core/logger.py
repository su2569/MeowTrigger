"""日志模块：分级输出，可选转发到群"""
import asyncio
import time
import traceback
from typing import Callable, Optional


class Logger:
    LEVELS = {"debug": 0, "info": 1, "success": 1, "warning": 2, "error": 3, "critical": 3}
    COLORS = {
        "debug": "\033[90m", "info": "\033[36m", "success": "\033[32m",
        "warning": "\033[33m", "error": "\033[31m", "critical": "\033[35m",
    }
    RESET = "\033[0m"

    def __init__(self):
        self.min_level = "info"
        self.forward_level = "error"
        self._forward_cb: Optional[Callable] = None
        self._send = False
        self._target = ""

    def configure(self, min_level: str = "info", forward_level: str = "error",
                  send_to_group: bool = False, target_group: str = "",
                  forward_cb: Optional[Callable] = None):
        self.min_level = min_level.lower()
        self.forward_level = forward_level.lower()
        self._send = send_to_group
        self._target = target_group
        self._forward_cb = forward_cb

    def _should_print(self, level: str) -> bool:
        return self.LEVELS.get(level.lower(), 1) >= self.LEVELS.get(self.min_level, 1)

    def _should_forward(self, level: str) -> bool:
        return self.LEVELS.get(level.lower(), 1) >= self.LEVELS.get(self.forward_level, 3)

    def _print(self, level: str, msg: str):
        if not self._should_print(level):
            return
        color = self.COLORS.get(level, "")
        ts = time.strftime("%H:%M:%S")
        try:
            print(f"{color}[{ts}][{level.upper()}]{self.RESET} {msg}", flush=True)
        except Exception:
            pass

    def _forward(self, level: str, msg: str):
        if not self._should_forward(level) or not self._send \
                or not self._target or not self._forward_cb:
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(
                    self._forward_cb(int(self._target), f"[{level.upper()}] {msg[:300]}")
                )
        except Exception:
            pass

    def log(self, level: str, msg: str):
        self._print(level, msg)
        self._forward(level, msg)

    def debug(self, msg): self.log("debug", msg)
    def info(self, msg): self.log("info", msg)
    def success(self, msg): self.log("success", msg)
    def warning(self, msg): self.log("warning", msg)
    def error(self, msg): self.log("error", msg)
    def critical(self, msg): self.log("critical", msg)
    def exception(self, msg):
        self.log("error", msg + "\n" + traceback.format_exc())


logger = Logger()
