"""脚本执行器：内联 / 脚本文件 / 系统命令（接入沙箱策略 + 变量注入）"""
import asyncio
import concurrent.futures
import math
import os
import random
import re
import time
from datetime import datetime
from typing import Dict, List, Optional

from .logger import logger
from .sandbox import SandboxExecutor
from .sandbox_policy import SandboxPolicy


class ScriptExecutor:
    def __init__(self, plugin_dir: str, timeout: int = 300, allow_system: bool = False,
                 system_whitelist: List[str] = None, sandbox_type: str = "auto",
                 venv_path: str = "", custom_python: str = "", custom_node: str = "",
                 default_env: Dict = None, sandbox_policy: Dict = None):
        self.timeout = timeout
        self.allow_system = allow_system
        self.system_whitelist = system_whitelist or []
        self.sandbox = SandboxExecutor(plugin_dir, sandbox_type, venv_path,
                                        custom_python, custom_node, default_env)
        self.policy = SandboxPolicy(sandbox_policy or {})

        self.safe_builtins = {
            "abs": abs, "all": all, "any": any, "bin": bin, "bool": bool,
            "chr": chr, "divmod": divmod, "enumerate": enumerate, "filter": filter,
            "float": float, "format": format, "hex": hex, "int": int,
            "isinstance": isinstance, "len": len, "list": list, "map": map,
            "max": max, "min": min, "oct": oct, "ord": ord, "pow": pow,
            "range": range, "reversed": reversed, "round": round, "set": set,
            "slice": slice, "sorted": sorted, "str": str, "sum": sum,
            "tuple": tuple, "zip": zip, "print": lambda *a, **k: None,
            "frozenset": frozenset, "hash": hash, "repr": repr,
            "Exception": Exception, "ValueError": ValueError,
            "TypeError": TypeError, "KeyError": KeyError,
            "IndexError": IndexError, "ZeroDivisionError": ZeroDivisionError,
            "ArithmeticError": ArithmeticError, "RuntimeError": RuntimeError,
            "StopIteration": StopIteration, "AttributeError": AttributeError,
            "NameError": NameError, "ImportError": ImportError,
        }
        self.safe_modules = {
            "math": math, "random": random, "datetime": datetime,
            "time": time, "re": re, "json": __import__("json"),
        }

    # ==================== 脚本解析 ====================

    def _resolve(self, path: str, trigger_dir: Optional[str],
                 script_paths: List[str]) -> Optional[str]:
        script_paths = script_paths or []
        candidates = []
        if os.path.isabs(path) and os.path.isfile(path):
            candidates.append(path)
        if trigger_dir:
            candidates.append(os.path.join(trigger_dir, path))
            candidates.append(os.path.join(trigger_dir, "scripts", path))
        for sp in script_paths:
            candidates.append(os.path.join(sp, path))
        for c in candidates:
            if os.path.isfile(c):
                return c
        return None

    def _load(self, path: str, trigger_dir: Optional[str], script_paths: List[str]) -> str:
        r = self._resolve(path, trigger_dir, script_paths)
        if not r:
            raise FileNotFoundError(f"Script not found: {path}")
        try:
            with open(r, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            with open(r, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()

    # ==================== Python 子进程包装 ====================

    def _wrap_python(self, code: str, variables: Dict) -> str:
        """
        为 script_file（python）模式生成最终源码：
          1. 沙箱前导（import hook）
          2. 注入 variables（args / user_id / message / ...）
          3. 用户代码
          4. 自动输出 output / result
        """
        parts: List[str] = []

        # 1) 沙箱前导
        if self.policy.enabled:
            parts.append(self.policy.make_preamble())

        # 2) 变量注入（只接受合法标识符 + repr 可控的值）
        var_lines = []
        for k, v in (variables or {}).items():
            if not isinstance(k, str) or not k.isidentifier():
                continue
            if k.startswith("_"):
                continue
            try:
                r = repr(v)
            except Exception:
                continue
            if len(r) > 20000:
                continue
            var_lines.append(f"{k} = {r}")
        if var_lines:
            parts.append("# ===== 注入变量 =====")
            parts.extend(var_lines)

        # 3) 用户代码
        parts.append("")
        parts.append("# ===== 用户代码 =====")
        parts.append(code)

        # 4) 自动输出
        parts.append("")
        parts.append("# ===== 自动输出 =====")
        parts.append(
            "try:\n"
            "    _mt_out = None\n"
            "    if 'output' in globals() and output:\n"
            "        _mt_out = output\n"
            "    elif 'result' in globals() and result is not None and result != '':\n"
            "        _mt_out = result\n"
            "    if _mt_out is not None and str(_mt_out).strip():\n"
            "        print(str(_mt_out))\n"
            "except Exception:\n"
            "    pass\n"
        )

        return "\n".join(parts)

    # ==================== 内联环境 ====================

    def _build_env(self, variables: Dict, api_obj, event=None, components=None):
        env = {
            "__builtins__": self.policy.make_builtins(self.safe_builtins),
            **self.safe_modules,
            **variables,
            "output": "",
            "result": "",
        }
        if api_obj:
            for k in dir(api_obj):
                if not k.startswith("_") and callable(getattr(api_obj, k, None)):
                    env[k] = getattr(api_obj, k)
        if event:
            env["event"] = event
        if components:
            env.update(components)
        return env

    # ==================== 执行 ====================

    async def execute_script(self, code: str, variables: Dict, api_obj, event=None,
                             components=None, script_type: str = "python",
                             mode: str = "local", is_admin: bool = False) -> str:
        if script_type == "node":
            return await self.sandbox.execute_node(code, variables, self.timeout, mode, is_admin)
        if script_type == "python":
            if mode != "none":
                code = self._wrap_python(code, variables)
            return await self.sandbox.execute_python(code, variables, self.timeout, mode, is_admin)
        if script_type == "inline":
            return await self._inline(code, variables, api_obj, event, components)
        return "[错误]不支持的脚本类型喵"

    async def _inline(self, code, variables, api_obj, event, components) -> str:
        env = self._build_env(variables, api_obj, event, components)
        main_loop = asyncio.get_event_loop()

        def run():
            scope = {"__name__": "__main__"}
            exec(code, env, scope)
            if scope.get("output", ""):
                return str(scope["output"])
            if env.get("output", ""):
                return str(env["output"])
            if "main" in scope and callable(scope["main"]):
                if asyncio.iscoroutinefunction(scope["main"]):
                    try:
                        fut = asyncio.run_coroutine_threadsafe(
                            asyncio.wait_for(scope["main"](), timeout=self.timeout),
                            main_loop)
                        r = fut.result(timeout=self.timeout)
                        if r is not None:
                            return str(r)
                    except Exception as e:
                        logger.debug(f"协程执行异常: {e}")
                else:
                    r = scope["main"]()
                    if r is not None:
                        return str(r)
            if scope.get("result", "") is not None:
                return str(scope["result"])
            if env.get("result", "") is not None:
                return str(env["result"])
            return "[成功]脚本执行成功喵（无输出）"

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(run)
            try:
                return fut.result(timeout=self.timeout)
            except concurrent.futures.TimeoutError:
                return "[超时]脚本执行超时了喵"
            except Exception as e:
                return f"[错误]脚本错误喵：{type(e).__name__}：{str(e)[:300]}"

    async def execute_script_file(self, path: str, variables: Dict, api_obj, event=None,
                                  components=None, trigger_dir: Optional[str] = None,
                                  is_group: bool = False, script_paths: List[str] = None,
                                  script_type: str = "python", mode: str = "local",
                                  is_admin: bool = False) -> str:
        try:
            code = self._load(path, trigger_dir, script_paths)
            return await self.execute_script(code, variables, api_obj, event, components,
                                             script_type=script_type, mode=mode, is_admin=is_admin)
        except FileNotFoundError:
            if is_group:
                return f"[阻止]群配置只能执行群配置文件夹内的脚本喵：{path}"
            return f"[错误]脚本文件未找到喵：{path}"
        except Exception as e:
            return f"[错误]加载脚本失败喵：{str(e)[:300]}"

    async def execute_system(self, cmd: str, variables: Dict, is_admin: bool = False,
                             mode: str = "local") -> str:
        return await self.sandbox.execute_system(
            cmd, variables, self.timeout, self.allow_system,
            self.system_whitelist, is_admin, mode)