"""运行时安全检查：拦截危险脚本 / 命令注入"""
import re
from typing import Dict, Tuple


class RuntimeSecurityChecker:
    PY_DANGEROUS = [
        r"os\.system", r"subprocess\.", r"eval\s*\(", r"exec\s*\(",
        r"compile\s*\(", "__import__", "importlib", r"ctypes\.",
        r"pickle\.loads", r"yaml\.load", r"marshal\.loads",
        r"socket\.", r"urllib\.", r"http\.client", r"requests\.",
        r"ftplib\.", r"smtplib\.", r"telnetlib\.", r"open\s*\(",
    ]
    NODE_DANGEROUS = [
        "child_process", r"eval\s*\(", r"Function\s*\(", r"require\s*\(",
        r"process\.exit", r"process\.env", r"fs\.unlink", r"fs\.rmdir",
        r"fs\.writeFile", r"http\.request", r"https\.request",
    ]
    INJECTION = [";", "|", "&", "$", "`", "\n", "\r", "\x00"]

    def __init__(self, strict_mode: bool = True):
        self.strict = strict_mode
        self._py = [re.compile(p, re.I) for p in self.PY_DANGEROUS]
        self._node = [re.compile(p, re.I) for p in self.NODE_DANGEROUS]

    def check_script(self, code: str, script_type: str = "python",
                     variables: Dict = None, is_admin: bool = False) -> Tuple[bool, str]:
        if is_admin:
            return True, ""
        if script_type in ("python", "inline"):
            for p in self._py:
                if p.search(code):
                    return False, "[安全阻止]检测到危险模式，Python脚本已被拦截喵~"
        elif script_type == "node":
            for p in self._node:
                if p.search(code):
                    return False, "[安全阻止]检测到危险模式，Node脚本已被拦截喵~"
        return True, ""

    def check_system_cmd(self, cmd: str, variables: Dict = None) -> Tuple[bool, str]:
        if variables:
            for k, v in variables.items():
                if not isinstance(v, str):
                    continue
                for c in self.INJECTION:
                    if c in v:
                        return False, f"[安全阻止]参数 '{k}' 包含危险字符 '{c}'，命令注入风险喵~"
        return True, ""
