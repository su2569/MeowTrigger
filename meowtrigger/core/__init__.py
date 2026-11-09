"""MeowTrigger core 模块（惰性导出）

这里不直接 import 具体模块，避免「只想用引擎」的程序被迫装 websockets。
``from meowtrigger.core import ScriptExecutor`` 依旧可用，第一次访问时才真正导入。
"""
import importlib
from typing import Any

_EXPORTS = {
    "logger": ".logger",
    "MessageParser": ".parser",
    "AntiSpam": ".anti_spam",
    "MessageDeduplicator": ".dedup",
    "RuntimeSecurityChecker": ".security",
    "SandboxExecutor": ".sandbox",
    "ScriptExecutor": ".executor",
    "OneBotClient": ".onebot",
    "OneBotAPI": ".onebot",
    "OneBotEvent": ".event",
    "ConfigLoader": ".config_loader",
    "EventHandler": ".handler",
    "CommandHandler": ".commands",
    "EmergencyController": ".emergency",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    mod = _EXPORTS.get(name)
    if mod is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(mod, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(__all__)
