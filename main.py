"""MeowTrigger 入口

保留 ``python main.py`` 这种老用法；实际逻辑都在 ``meowtrigger`` 包里，
方便别的程序 ``import meowtrigger`` 直接复用。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from meowtrigger.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
