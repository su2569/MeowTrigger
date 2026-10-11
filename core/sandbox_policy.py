"""沙箱策略：模块白/黑名单 + 属性级 Hook + 审计日志

防御分层：
  1. 模块级     —— module_blacklist 拦危险模块（subprocess/socket/...）
  2. 属性级     —— ModuleProxy 拦危险属性（os.system / sys.exit）
  3. 内置函数级 —— forbidden_builtins 屏蔽 eval/exec/open

设计原则（嵌入式 Python 关键）：
  - sys / io / builtins / os 等基础设施 **不在黑名单**（标准库离不开）
  - 它们的危险属性改由 forbidden_attrs 精确拦截
  - forbidden_attrs 支持 fnmatch 通配符（exec* / spawn*）
"""
import fnmatch
from typing import Any, Dict, List, Optional, Set, Tuple


class SandboxPolicy:
    # 隐式放行（下划线开头的 C 扩展等）
    IMPLICIT_ALLOW_PREFIXES = ("_",)
    IMPLICIT_ALLOW_EXTRA = {
        # Python 启动基础设施
        "encodings", "codecs", "builtins", "__builtin__",
        "warnings", "abc", "types", "weakref",
        "copyreg", "operator", "keyword", "linecache",
        "token", "tokenize", "traceback",
        # zipimport 解压依赖（嵌入式 Python 必须）
        "zlib", "bz2", "lzma", "struct",
        "site", "posixpath", "ntpath", "genericpath",
    }

    def __init__(self, config: Optional[Dict] = None):
        config = config or {}
        self.enabled = bool(config.get("enabled", True))
        self.hook_enabled = bool(config.get("hook_enabled", True))
        self.block_private_attrs = bool(config.get("block_private_attrs", True))
        self.whitelist: Set[str] = set(config.get("module_whitelist", []) or [])
        self.blacklist: Set[str] = set(config.get("module_blacklist", []) or [])
        self.forbidden_builtins: Set[str] = set(config.get("forbidden_builtins", []) or [])
        self.forbidden_attrs: Dict[str, List[str]] = dict(config.get("forbidden_attrs", {}) or {})
        self.max_audit_log = int(config.get("max_audit_log", 200))
        self.audit_log: List[Dict[str, Any]] = []

    # ==================== 检查 ====================

    def _is_implicit_allow(self, root: str) -> bool:
        if root in self.IMPLICIT_ALLOW_EXTRA:
            return True
        for prefix in self.IMPLICIT_ALLOW_PREFIXES:
            if root.startswith(prefix):
                return True
        return False

    def check_module(self, name: str) -> Tuple[bool, str]:
        if not self.enabled:
            return True, ""
        root = name.split(".")[0]

        # 1) 黑名单优先
        if root in self.blacklist:
            return False, f"模块 '{name}' 在黑名单中"

        # 2) 隐式放行（下划线开头的 C 扩展等）
        if self._is_implicit_allow(root):
            return True, ""

        # 3) 白名单（空则全部放行）
        if self.whitelist and root not in self.whitelist:
            return False, f"模块 '{name}' 不在白名单中"
        return True, ""

    def _match_attr(self, attr: str, rules: List[str]) -> bool:
        for pat in rules:
            if pat == "*":
                return True
            if fnmatch.fnmatchcase(attr, pat):
                return True
        return False

    def check_attr(self, module_name: str, attr: str) -> Tuple[bool, str]:
        if not self.enabled or not self.hook_enabled:
            return True, ""
        root = module_name.split(".")[0]
        rules = self.forbidden_attrs.get(root, [])
        if self._match_attr(attr, rules):
            return False, f"禁止访问 {root}.{attr}"
        # dunder 拦截
        if self.block_private_attrs and attr.startswith("__") and attr.endswith("__"):
            dangerous = {
                "__dict__", "__globals__", "__builtins__", "__import__",
                "__subclasses__", "__code__", "__reduce__", "__reduce_ex__",
                "__getattribute__", "__class__", "__bases__", "__mro__",
                "__closure__", "__func__", "__self__", "__loader__",
                "__spec__", "__path__",
            }
            if attr in dangerous:
                return False, f"禁止访问危险魔术属性 {root}.{attr}"
        return True, ""

    # ==================== 审计 ====================

    def record(self, kind: str, target: str, reason: str):
        self.audit_log.append({"kind": kind, "target": target, "reason": reason})
        if len(self.audit_log) > self.max_audit_log:
            self.audit_log = self.audit_log[-self.max_audit_log:]

    def get_audit_log(self) -> List[Dict]:
        return list(self.audit_log)

    def clear_audit(self):
        self.audit_log.clear()

    # ==================== 构造器 ====================

    def make_import(self):
        policy = self

        def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
            ok, reason = policy.check_module(name)
            if not ok:
                policy.record("import_blocked", name, reason)
                raise ImportError(f"[安全阻止] {reason}")
            real = __import__(name, globals, locals, fromlist, level)
            if not policy.enabled or not policy.hook_enabled:
                return real
            root = name.split(".")[0]
            if root in policy.forbidden_attrs:
                return ModuleProxy(real, root, policy)
            return real

        return _safe_import

    def make_builtins(self, base_builtins: Dict) -> Dict:
        safe = dict(base_builtins)
        for name in self.forbidden_builtins:
            safe.pop(name, None)
        safe["__import__"] = self.make_import()
        return safe

    def make_preamble(self) -> str:
        wl = sorted(self.whitelist)
        bl = sorted(self.blacklist)
        fa = {k: list(v) for k, v in self.forbidden_attrs.items()}
        extra = sorted(self.IMPLICIT_ALLOW_EXTRA)
        prefixes = list(self.IMPLICIT_ALLOW_PREFIXES)
        return (
            "# ==== MeowTrigger Sandbox Preamble ====\n"
            "import builtins as _mt_builtins\n"
            "import fnmatch as _mt_fnmatch\n"
            f"_MT_WL = {wl!r}\n"
            f"_MT_BL = {bl!r}\n"
            f"_MT_FA = {fa!r}\n"
            f"_MT_EXTRA = {extra!r}\n"
            f"_MT_PREFIX = {prefixes!r}\n"
            "_mt_real_import = _mt_builtins.__import__\n"
            "def _mt_implicit_allow(root):\n"
            "    if root in _MT_EXTRA:\n"
            "        return True\n"
            "    for p in _MT_PREFIX:\n"
            "        if root.startswith(p):\n"
            "            return True\n"
            "    return False\n"
            "class _MtProxy:\n"
            "    __slots__ = ('_m', '_n')\n"
            "    def __init__(self, m, n):\n"
            "        object.__setattr__(self, '_m', m)\n"
            "        object.__setattr__(self, '_n', n)\n"
            "    def __getattr__(self, a):\n"
            "        n = object.__getattribute__(self, '_n')\n"
            "        rules = _MT_FA.get(n, [])\n"
            "        for p in rules:\n"
            "            if p == '*' or _mt_fnmatch.fnmatchcase(a, p):\n"
            "                raise AttributeError(f\"[安全阻止] 禁止访问 {n}.{a}\")\n"
            "        if a.startswith('__') and a.endswith('__') and a in (\n"
            "            '__dict__','__globals__','__builtins__','__import__',\n"
            "            '__subclasses__','__code__','__reduce__','__class__',\n"
            "            '__bases__','__mro__','__closure__','__loader__','__spec__',\n"
            "        ):\n"
            "            raise AttributeError(f\"[安全阻止] 禁止访问魔术属性 {n}.{a}\")\n"
            "        return getattr(object.__getattribute__(self, '_m'), a)\n"
            "    def __setattr__(self, a, v):\n"
            "        raise AttributeError('[安全阻止] 禁止修改模块属性')\n"
            "    def __delattr__(self, a):\n"
            "        raise AttributeError('[安全阻止] 禁止删除模块属性')\n"
            "    def __dir__(self):\n"
            "        return dir(object.__getattribute__(self, '_m'))\n"
            "    def __repr__(self):\n"
            "        return f\"<sandboxed module '{object.__getattribute__(self, '_n')}'>\"\n"
            "def _mt_safe_import(name, *a, **kw):\n"
            "    root = name.split('.')[0]\n"
            "    if root in _MT_BL:\n"
            "        raise ImportError(f\"[安全阻止] 模块 '{name}' 在黑名单中\")\n"
            "    if _mt_implicit_allow(root):\n"
            "        return _mt_real_import(name, *a, **kw)\n"
            "    if _MT_WL and root not in _MT_WL:\n"
            "        raise ImportError(f\"[安全阻止] 模块 '{name}' 不在白名单中\")\n"
            "    m = _mt_real_import(name, *a, **kw)\n"
            "    if root in _MT_FA:\n"
            "        return _MtProxy(m, root)\n"
            "    return m\n"
            "_mt_builtins.__import__ = _mt_safe_import\n"
            "# ========================================\n"
        )


class ModuleProxy:
    __slots__ = ("_module", "_name", "_policy")

    def __init__(self, module, name: str, policy: SandboxPolicy):
        object.__setattr__(self, "_module", module)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_policy", policy)

    def __getattr__(self, attr):
        policy = object.__getattribute__(self, "_policy")
        name = object.__getattribute__(self, "_name")
        module = object.__getattribute__(self, "_module")
        ok, reason = policy.check_attr(name, attr)
        if not ok:
            policy.record("attr_blocked", f"{name}.{attr}", reason)
            raise AttributeError(f"[安全阻止] {reason}")
        return getattr(module, attr)

    def __setattr__(self, attr, value):
        raise AttributeError(f"[安全阻止] 禁止修改模块属性 {attr}")

    def __delattr__(self, attr):
        raise AttributeError(f"[安全阻止] 禁止删除模块属性 {attr}")

    def __dir__(self):
        return dir(object.__getattribute__(self, "_module"))

    def __repr__(self):
        name = object.__getattribute__(self, "_name")
        return f"<sandboxed module '{name}'>"