"""TriggerEngine：可嵌入的触发器内核

这是 MeowTrigger 的「不带头」形态：不连 WebSocket、不管进程，
只做三件事——读配置、匹配触发器、跑响应。

给宿主程序（ElyBot、其他框架、脚本）用时::

    from meowtrigger import TriggerEngine, MessageContext

    engine = TriggerEngine("/path/to/MeowTrigger", config={"admin_users": ["10001"]})
    engine.reload()

    ctx = MessageContext(text="你好", umo="onebot:GroupMessage:123456789",
                         user_id="10001", user_name="小林", group_id="123456789")
    reply = await engine.handle(ctx)      # 没命中返回 None

单独运行时由 ``meowtrigger.app.MeowTriggerApp`` 包一层 OneBot 传输即可。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from .context import MessageContext
from .core.config_loader import ConfigLoader
from .core.executor import ScriptExecutor
from .core.handler import EventHandler
from .core.logger import logger
from .core.parser import MessageParser
from .core.security import RuntimeSecurityChecker
from .umo import DEFAULT_PLATFORM

DEFAULT_ENGINE_CONFIG: Dict[str, Any] = {
    "admin_users": [],
    "default_permission": "all",
    "default_cooldown": 0,
    "script_timeout": 300,
    "allow_system_cmd": False,
    "system_cmd_whitelist": [],
    "sandbox_type": "auto",
    "venv_path": "",
    "custom_python": "",
    "custom_node": "",
    "execution_mode": "local",
    "message_parse_mode": "auto",
    "plugins_dir": "plugins",
    "mt_plugins_dir": "",
    "require_umo": True,
    "platform": DEFAULT_PLATFORM,
}


class NullAPI:
    """没有传输层时的 API 桩：脚本里 send_msg 之类不会炸，结果被收集"""

    def __init__(self):
        self.outputs: List[str] = []

    async def send_msg(self, *args, **kwargs):
        if args:
            self.outputs.append(str(args[-1]))
        elif "message" in kwargs:
            self.outputs.append(str(kwargs["message"]))
        return True

    async def send_group_msg(self, *args, **kwargs):
        return await self.send_msg(*args, **kwargs)

    async def send_private_msg(self, *args, **kwargs):
        return await self.send_msg(*args, **kwargs)

    async def call_api(self, *args, **kwargs):
        return None

    def __getattr__(self, name):
        async def _noop(*args, **kwargs):
            return None
        return _noop


class TriggerEngine:
    """配置 + 匹配 + 执行，不含传输"""

    def __init__(self, base_dir: Optional[str] = None,
                 config: Optional[Dict[str, Any]] = None,
                 api: Any = None,
                 platform: Optional[str] = None):
        self.base_dir = os.path.abspath(base_dir or os.getcwd())
        self.config = dict(DEFAULT_ENGINE_CONFIG)
        self.config.update(config or {})
        self.platform = platform or self.config.get("platform") or DEFAULT_PLATFORM

        plugins_dir = self.config.get("plugins_dir") or "plugins"
        if not os.path.isabs(plugins_dir):
            plugins_dir = os.path.join(self.base_dir, plugins_dir)
        mt_dir = self.config.get("mt_plugins_dir") or ""
        if mt_dir and not os.path.isabs(mt_dir):
            mt_dir = os.path.join(self.base_dir, mt_dir)
        self.plugins_dir = plugins_dir
        self.mt_dir = mt_dir or os.path.join(plugins_dir, "MTPlugins")

        os.makedirs(self.mt_dir, exist_ok=True)

        self.api = api if api is not None else NullAPI()
        self.parser = MessageParser(self.config.get("message_parse_mode", "auto"))
        self.loader = ConfigLoader(
            self.base_dir, self.plugins_dir, self.mt_dir,
            platform=self.platform,
            require_umo=bool(self.config.get("require_umo", True)))
        self.executor = ScriptExecutor(
            plugin_dir=self.base_dir,
            timeout=self.config.get("script_timeout", 300),
            allow_system=self.config.get("allow_system_cmd", False),
            system_whitelist=self.config.get("system_cmd_whitelist", []),
            sandbox_type=self.config.get("sandbox_type", "auto"),
            venv_path=self.config.get("venv_path", ""),
            custom_python=self.config.get("custom_python", ""),
            custom_node=self.config.get("custom_node", ""),
            sandbox_policy=self.config.get("sandbox", {}),
        )
        self.security = RuntimeSecurityChecker(strict_mode=True)
        self.handler = EventHandler(
            self.loader, self.executor, self.api, self.parser, {},
            self.config.get("admin_users", []), None, self.security)
        self._loaded = False

    # ---------------- 配置 ----------------

    def reload(self) -> Dict[str, int]:
        """重新扫描插件目录；返回简要统计"""
        self.loader.load_all(self.config.get("default_permission", "all"),
                             self.config.get("default_cooldown", 0))
        self._loaded = True
        return self.stats()

    def stats(self) -> Dict[str, int]:
        return {
            "global_triggers": len(self.loader.global_triggers),
            "groups": len(self.loader.group_cache),
            "users": len(self.loader.user_cache),
            "errors": len(self.loader.errors),
        }

    def scopes(self) -> List[List[str]]:
        """MTPlugins 下的 G/U 配置目录清单"""
        return self.loader.list_scopes()

    def triggers_for(self, ctx: MessageContext) -> List[Dict]:
        return self.handler.get_effective_triggers(
            ctx, self.loader.global_triggers, self.loader.group_cache)

    # ---------------- 执行 ----------------

    async def handle(self, ctx: Any, text: Optional[str] = None,
                     umo: Optional[str] = None,
                     user_id: Optional[str] = None,
                     user_name: Optional[str] = None,
                     group_id: Optional[str] = None,
                     role: Optional[str] = None) -> Optional[str]:
        """匹配并执行触发器；命中返回文本，未命中返回 None

        既接受 ``MessageContext``，也接受任意带 content/group_id 的对象，
        还可以直接传一段文本 + umo，方便宿主程序按需调用。
        """
        if not self._loaded:
            self.reload()

        if isinstance(ctx, MessageContext):
            context = ctx
        elif isinstance(ctx, str) and text is None:
            context = MessageContext(text=ctx)
        else:
            context = MessageContext.from_any(ctx, platform=self.platform)

        if text is not None:
            context = MessageContext(
                text=text, umo=umo or context.umo,
                user_id=user_id if user_id is not None else context.user_id,
                user_name=user_name or context.user_name,
                group_id=group_id if group_id is not None else context.group_id,
                role=role or context.role, platform=self.platform)
        elif umo:
            context.umo = umo

        if not context.text:
            return None

        triggers = self.triggers_for(context)
        for trigger in triggers:
            if not trigger.get("enabled", True):
                continue
            if trigger.get("trigger_type", "") == "cron":
                continue
            matched, match_content, trigger_args = self.handler.check_trigger_match(
                trigger, context.text)
            if not matched:
                continue

            name = trigger.get("name", "")
            perm = trigger.get("permission", "all")
            if not self.handler.check_permission(context, perm):
                return f"[阻止]权限不足，触发器『{name}』需要『{perm}』权限喵。"

            cooldown = trigger.get("cooldown", 0)
            if self.handler.is_on_cooldown(context.user_id, name, cooldown):
                continue

            anti_spam = getattr(self.handler, "anti_spam", None)
            if anti_spam:
                ok, reason = await anti_spam.check(context.user_id, name)
                if not ok:
                    return reason

            try:
                is_admin = self.handler.is_ab_admin(context)
                variables = self.handler.build_variables(
                    context, trigger_args, match_content)
                variables["umo"] = context.umo
                result = await self.handler.execute_response(
                    trigger, variables, context, is_admin,
                    self.config.get("execution_mode", "local"))
            except Exception as e:  # 单条触发器炸了不该拖垮宿主
                logger.exception(f"触发器 {name} 执行异常: {e}")
                return f"[错误]触发器『{name}』执行失败喵：{e}"

            if not result or not str(result).strip():
                result = "[提示]触发器执行完成，但无输出内容喵~"
            return str(result)
        return None


__all__ = ["TriggerEngine", "NullAPI", "DEFAULT_ENGINE_CONFIG"]
