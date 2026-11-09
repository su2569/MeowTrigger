"""沙箱执行：none / sandbox(venv) / local"""
import asyncio
import os
import subprocess
import sys
import tempfile
import venv
from typing import Dict, List, Optional

from .logger import logger


class SandboxExecutor:
    DEFAULT_ENV = {"LANG": "zh_CN.UTF-8", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

    def __init__(self, plugin_dir: str, sandbox_type: str = "auto", venv_path: str = "",
                 custom_python: str = "", custom_node: str = "", default_env: Dict = None):
        self.plugin_dir = plugin_dir
        self.sandbox_type = sandbox_type
        self.venv_path = venv_path or os.path.join(plugin_dir, "venv")
        self.custom_python = custom_python
        self.custom_node = custom_node
        self.default_env = default_env or dict(self.DEFAULT_ENV)
        self._venv_ready = False

    def _build_env(self, extra: Optional[Dict] = None) -> Dict[str, str]:
        env = dict(os.environ)
        for k, v in self.default_env.items():
            if v:
                env[k] = v
        if extra:
            for k, v in extra.items():
                env[f"CT_{k}"] = str(v)
        return env

    def _get_python(self, mode: str, is_admin: bool) -> str:
        if self.custom_python and os.path.exists(self.custom_python):
            return self.custom_python
        if mode == "sandbox" or (not is_admin and mode == "local"):
            self._ensure_venv()
            py = os.path.join(self.venv_path,
                              "Scripts" if sys.platform == "win32" else "bin", "python")
            if sys.platform == "win32":
                py += ".exe"
            if os.path.exists(py):
                return py
        return sys.executable

    def _get_node(self, mode: str, is_admin: bool) -> Optional[str]:
        if self.custom_node and os.path.exists(self.custom_node):
            return self.custom_node
        if mode == "sandbox" or (not is_admin and mode == "local"):
            self._ensure_venv()
            n = os.path.join(self.venv_path,
                             "Scripts" if sys.platform == "win32" else "bin", "node")
            if sys.platform == "win32":
                n += ".exe"
            if os.path.exists(n):
                return n
        for p in os.environ.get("PATH", "").split(os.pathsep):
            n = os.path.join(p, "node.exe" if sys.platform == "win32" else "node")
            if os.path.exists(n):
                return n
        return None

    def _ensure_venv(self) -> bool:
        if self._venv_ready:
            return True
        p = os.path.join(self.venv_path,
                         "Scripts" if sys.platform == "win32" else "bin",
                         "python.exe" if sys.platform == "win32" else "python")
        if os.path.exists(p):
            self._venv_ready = True
            return True
        try:
            os.makedirs(self.venv_path, exist_ok=True)
            venv.create(self.venv_path, with_pip=True)
            self._venv_ready = True
            logger.info(f"venv 创建成功: {self.venv_path}")
            return True
        except Exception as e:
            logger.warning(f"venv 创建失败: {e}")
            return False

    async def execute_python(self, code: str, env_vars: Dict, timeout: int = 300,
                             mode: str = "local", is_admin: bool = False) -> str:
        if mode == "none":
            return "[阻止]脚本执行已禁用喵"
        py = self._get_python(mode, is_admin)
        env = self._build_env(env_vars)
        fd, tmp = tempfile.mkstemp(suffix=".py", dir=self.plugin_dir)
        os.close(fd)
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(code)
        except Exception as e:
            return f"[错误]写入临时文件失败: {e}"
        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    py, tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    env=env, cwd=self.plugin_dir),
                timeout=timeout)
            out, err = await proc.communicate()
            out = out.decode("utf-8", errors="replace").strip()
            err = err.decode("utf-8", errors="replace").strip()
            try:
                os.remove(tmp)
            except Exception:
                pass
            if err and proc.returncode != 0:
                return f"[警告]退出码 {proc.returncode}\n{err[:500]}"
            return out[:2000] or "[成功]脚本执行成功喵（无输出）"
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                os.remove(tmp)
            except Exception:
                pass
            return "[超时]脚本执行超时了喵"
        except Exception as e:
            try:
                os.remove(tmp)
            except Exception:
                pass
            return f"[错误]脚本执行异常: {e}"

    async def execute_node(self, code: str, env_vars: Dict, timeout: int = 300,
                           mode: str = "local", is_admin: bool = False) -> str:
        if mode == "none":
            return "[阻止]脚本执行已禁用喵"
        node = self._get_node(mode, is_admin)
        if not node:
            return "[错误]未找到 Node.js，请安装或配置 custom_node"
        env = self._build_env(env_vars)
        fd, tmp = tempfile.mkstemp(suffix=".js", dir=self.plugin_dir)
        os.close(fd)
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(code)
        except Exception as e:
            return f"[错误]写入临时文件失败: {e}"
        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    node, tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    env=env, cwd=self.plugin_dir),
                timeout=timeout)
            out, err = await proc.communicate()
            out = out.decode("utf-8", errors="replace").strip()
            err = err.decode("utf-8", errors="replace").strip()
            try:
                os.remove(tmp)
            except Exception:
                pass
            if err and proc.returncode != 0:
                return f"[警告]退出码 {proc.returncode}\n{err[:500]}"
            return out[:2000] or "[成功]Node脚本执行成功喵（无输出）"
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                os.remove(tmp)
            except Exception:
                pass
            return "[超时]Node脚本执行超时了喵"
        except Exception as e:
            try:
                os.remove(tmp)
            except Exception:
                pass
            return f"[错误]Node脚本执行异常: {e}"

    async def execute_system(self, cmd: str, env_vars: Dict, timeout: int = 300,
                             allow: bool = False, whitelist: List[str] = None,
                             is_admin: bool = False, mode: str = "local") -> str:
        if not allow:
            return "[阻止]系统命令已禁用喵"
        if not is_admin:
            return "[阻止]系统命令仅限管理员调用喵"
        whitelist = whitelist or []
        parts = cmd.strip().split()
        if not parts:
            return "[错误]空命令喵"
        if parts[0] not in whitelist:
            return f"[阻止]命令'{parts[0]}'不在白名单中喵"
        for k, v in env_vars.items():
            cmd = cmd.replace(f"{{{k}}}", str(v))
        env = self._build_env(env_vars)
        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_shell(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    env=env, cwd=self.plugin_dir),
                timeout=timeout)
            out, err = await proc.communicate()
            out = out.decode("utf-8", errors="replace").strip()
            err = err.decode("utf-8", errors="replace").strip()
            if err and proc.returncode != 0:
                return f"[警告]退出码 {proc.returncode}\n{err[:500]}"
            return out[:2000] or "[成功]命令执行成功喵（无输出）"
        except asyncio.TimeoutError:
            return "[超时]系统命令执行超时了喵"
        except Exception as e:
            return f"[错误]系统命令执行异常: {e}"
