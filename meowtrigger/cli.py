"""命令行入口

用法::

    python main.py                      # 用 config/config.json 启动
    python main.py --check              # 只检查配置，不连 WS
    python main.py --config other.json
    python -m meowtrigger
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import List, Optional


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="meowtrigger", description="MeowTrigger 自定义触发器机器人")
    parser.add_argument("-c", "--config", default="", help="配置文件路径")
    parser.add_argument("-d", "--dir", default="", help="项目根目录")
    parser.add_argument("--plugins", default="", help="插件目录（默认 plugins）")
    parser.add_argument("--mt-plugins", default="", help="MTPlugins 目录")
    parser.add_argument("--check", action="store_true", help="只检查配置后退出")
    parser.add_argument("--version", action="store_true", help="显示版本")
    return parser


def _check(base_dir: str, overrides: dict) -> int:
    from .engine import TriggerEngine
    from . import __version__

    engine = TriggerEngine(base_dir, overrides)
    stats = engine.reload()
    print(f"MeowTrigger {__version__}")
    print(f"插件目录: {engine.plugins_dir}")
    print(f"MTPlugins: {engine.mt_dir}")
    print(f"全局触发器: {stats['global_triggers']}  "
          f"群配置: {stats['groups']}  用户配置: {stats['users']}")
    scopes = engine.scopes()
    if scopes:
        print("会话配置目录:")
        for dir_name, kind, sid, custom in scopes:
            print(f"  - {dir_name}  ({'群' if kind == 'G' else '用户'} {sid}"
                  f"{'，' + custom if custom else ''})")
    if engine.loader.errors:
        print("\n发现问题:")
        for err in engine.loader.errors:
            print(f"  ! {err}")
        return 1
    print("\n配置检查通过喵~")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    base_dir = os.path.abspath(
        args.dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from . import __version__
    if args.version:
        print(f"MeowTrigger {__version__}")
        return 0

    overrides: dict = {}
    if args.plugins:
        overrides["plugins_dir"] = args.plugins
    if args.mt_plugins:
        overrides["mt_plugins_dir"] = args.mt_plugins
    if args.config:
        path = args.config if os.path.isabs(args.config) else os.path.join(base_dir, args.config)
        try:
            with open(path, "r", encoding="utf-8") as f:
                overrides.update(json.load(f))
        except Exception as e:
            print(f"读取配置文件失败: {e}")
            return 2

    if args.check:
        return _check(base_dir, overrides)

    from .app import MeowTriggerApp

    app = MeowTriggerApp(base_dir, overrides or None)
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        print("\n收到中断信号，退出")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
