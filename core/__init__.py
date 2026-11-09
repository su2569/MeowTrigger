"""兼容层：``core.*`` 已迁移到 ``meowtrigger.core.*``

老代码里的 ``from core import ScriptExecutor`` 依旧能用，
新代码请直接 ``from meowtrigger.core import ...``。
"""
import importlib
import sys

from meowtrigger import core as _core

__all__ = list(getattr(_core, "__all__", []))

for _name in __all__:
    globals()[_name] = getattr(_core, _name)

_SUBMODULES = (
    "logger", "parser", "anti_spam", "dedup", "security", "sandbox",
    "sandbox_policy", "executor", "onebot", "event", "config_loader",
    "handler", "commands", "emergency",
)
for _sub in _SUBMODULES:
    try:
        sys.modules.setdefault(f"core.{_sub}",
                               importlib.import_module(f"meowtrigger.core.{_sub}"))
    except Exception:  # pragma: no cover - 某个子模块缺失时不影响其它导入
        pass

del _sub
try:
    del _name
except NameError:  # pragma: no cover - __all__ 为空时
    pass
