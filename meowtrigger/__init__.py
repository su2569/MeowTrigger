"""MeowTrigger — 自定义触发器引擎（独立运行 / 作为包嵌入）

两种用法：

1. 独立运行::

       python main.py            # 或 python -m meowtrigger

2. 作为包嵌入（ElyBot 等）::

       from meowtrigger import TriggerEngine, MessageContext

       engine = TriggerEngine("/path/to/MeowTrigger")
       engine.reload()
       reply = await engine.handle(
           MessageContext(text="你好", umo="onebot:GroupMessage:123456789",
                          user_id="10001", group_id="123456789"))

核心概念：

- **UMO**：``platform:message_type:session_id``，声明触发器属于哪个会话
- **MTPlugins**：``plugins/MTPlugins/G<群号>_<名字>/`` 与 ``U<QQ>_<名字>/``
  目录，专门放群配置和用户配置
"""
from __future__ import annotations

__version__ = "1.1.0"

from .context import MessageContext
from .engine import TriggerEngine, NullAPI
from .scope import (Scope, build_scope_name, parse_scope, iter_scope_dirs,
                    find_scope_dir, ensure_scope_dir, list_scope_dirs)
from .umo import (UMO, UMOError, build_umo, parse_umo, try_parse_umo,
                  is_valid_umo, umo_matches, umo_of, normalize_message_type)

__all__ = [
    "__version__",
    # 引擎
    "TriggerEngine", "NullAPI", "MessageContext",
    # UMO
    "UMO", "UMOError", "build_umo", "parse_umo", "try_parse_umo",
    "is_valid_umo", "umo_matches", "umo_of", "normalize_message_type",
    # MTPlugins 目录
    "Scope", "build_scope_name", "parse_scope", "iter_scope_dirs",
    "find_scope_dir", "ensure_scope_dir", "list_scope_dirs",
    # 入口
    "create_engine", "create_app", "main",
]


def create_engine(base_dir=None, config=None, **kwargs) -> TriggerEngine:
    """建一个已加载配置的引擎"""
    engine = TriggerEngine(base_dir, config or None)
    engine.reload()
    return engine


def create_app(base_dir=None, config=None):
    """建一个独立运行的 App（需要 websockets）"""
    from .app import MeowTriggerApp
    return MeowTriggerApp(base_dir, config)


def main(argv=None):
    """命令行入口，等价于 python main.py"""
    from .cli import main as _main
    return _main(argv)


def __getattr__(name):  # 懒加载：缺 websockets 时不影响纯嵌入使用
    if name == "MeowTriggerApp":
        from .app import MeowTriggerApp
        return MeowTriggerApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
