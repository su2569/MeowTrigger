# fix_import.py - 给 core/executor.py 加白名单 __import__
import os
import sys

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "core", "executor.py")

INJECT_BLOCK = '''
# ===== 沙箱 import 白名单 =====
_ALLOWED_IMPORTS = {
    "math", "random", "datetime", "time", "re", "json",
    "string", "collections", "itertools", "functools",
    "decimal", "fractions", "statistics",
    "uuid", "base64", "hashlib", "hmac",
    "textwrap", "unicodedata",
    "operator", "copy",
    "enum", "dataclasses", "typing",
    "calendar", "zoneinfo",
}


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split(".")[0]
    if root not in _ALLOWED_IMPORTS:
        raise ImportError(
            f"[安全阻止]模块 '{name}' 不在白名单中，"
            f"可用模块: {', '.join(sorted(_ALLOWED_IMPORTS))}"
        )
    return __import__(name, globals, locals, fromlist, level)
# ===============================

'''


def main():
    if not os.path.isfile(PATH):
        print(f"[!] 找不到文件: {PATH}")
        print("    请在 MeowTrigger 根目录下运行本脚本")
        sys.exit(1)

    with open(PATH, "r", encoding="utf-8") as f:
        src = f.read()

    changed = False

    # 1. 注入 _safe_import 定义（放在 from .sandbox import 之后）
    marker = "from .sandbox import SandboxExecutor\n"
    if "_ALLOWED_IMPORTS" not in src:
        if marker not in src:
            print("[!] 未找到 'from .sandbox import SandboxExecutor'，"
                  "请确认 core/executor.py 未被大改")
            sys.exit(1)
        src = src.replace(marker, marker + INJECT_BLOCK, 1)
        changed = True
        print("[OK] 已注入 _safe_import 定义")
    else:
        print("[SKIP] _safe_import 定义已存在")

    # 2. 在 safe_builtins 里加 __import__
    if '"__import__": _safe_import' not in src:
        old = '"print": lambda *a, **k: None,\n        }'
        new = '"print": lambda *a, **k: None,\n            "__import__": _safe_import,\n        }'
        if old not in src:
            print("[!] 未找到 safe_builtins 的结尾标记，"
                  "请手动在 safe_builtins 里加一行:")
            print('    "__import__": _safe_import,')
            sys.exit(1)
        src = src.replace(old, new, 1)
        changed = True
        print("[OK] 已在 safe_builtins 里加入 __import__")
    else:
        print("[SKIP] safe_builtins 里已有 __import__")

    if changed:
        with open(PATH, "w", encoding="utf-8", newline="\n") as f:
            f.write(src)
        print(f"[DONE] 已更新: {PATH}")
    else:
        print("[DONE] 无需修改")

    # 语法校验
    try:
        compile(src, PATH, "exec")
        print("[OK] 语法校验通过")
    except SyntaxError as e:
        print(f"[!] 语法错误: {e}")
        sys.exit(1)

    print()
    print("现在可以重新启动 MeowTrigger，签到触发器应该能正常工作了。")


if __name__ == "__main__":
    main()