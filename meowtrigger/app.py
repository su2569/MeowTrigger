"""MeowTriggerApp：独立运行形态

把 ``TriggerEngine`` 接上 OneBot V11 的反向 WebSocket，就得到了一个完整
的独立机器人：

- 收消息 → 去重 → 紧急锁定检查 → 命令拦截 → 触发器匹配 → 回消息
- 定时重载配置 / Cron 触发器 / 日志转发到群

如果你只是想把触发器塞进别的程序，用 ``TriggerEngine`` 就够了，不用碰这里。
"""
import asyncio
import hashlib
import json
import os
from datetime import datetime
from typing import Dict, List, Optional

from .context import MessageContext
from .core.commands import CommandHandler
from .core.dedup import MessageDeduplicator
from .core.emergency import EmergencyController
from .core.anti_spam import AntiSpam
from .core.logger import logger
from .core.onebot import OneBotAPI, OneBotClient
from .engine import DEFAULT_ENGINE_CONFIG, TriggerEngine
from .umo import DEFAULT_PLATFORM, umo_of

try:
    from croniter import croniter
    HAS_CRONITER = True
except ImportError:  # pragma: no cover - 可选依赖
    HAS_CRONITER = False


DEFAULT_CONFIG: Dict = {
    # —— 传输 ——
    "ws_url": "ws://127.0.0.1:3001",
    "access_token": "",
    "reconnect_interval": 5,
    # —— 运行 ——
    "reload_interval": 60,
    "command_prefix": "/mt",
    "platform": DEFAULT_PLATFORM,
    "log_level": "info",
    "log_forward_level": "error",
    "log_target_group": "",
    "send_log_to_group": False,
    "anti_spam_enabled": True,
    "anti_spam_window": 30,
    "anti_spam_count": 3,
    # —— 配置目录 ——
    "plugins_dir": "plugins",
    "mt_plugins_dir": "",
    "require_umo": True,
}
DEFAULT_CONFIG.update(DEFAULT_ENGINE_CONFIG)
DEFAULT_CONFIG.update({"plugins_dir": "plugins", "mt_plugins_dir": "",
                       "require_umo": True})


class MeowTriggerApp:
    """独立版：引擎 + OneBot 传输 + 命令 + 紧急控制"""

    def __init__(self, base_dir: Optional[str] = None,
                 config: Optional[Dict] = None):
        self.base_dir = os.path.abspath(
            base_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.config_path = os.path.join(self.base_dir, "config", "config.json")
        self.config = self._load_config(config)

        # 传输
        self.client = OneBotClient(
            ws_url=self.config.get("ws_url", "ws://127.0.0.1:3001"),
            access_token=self.config.get("access_token", ""),
            reconnect_interval=self.config.get("reconnect_interval", 5),
        )
        self.api = OneBotAPI(self.client)

        logger.configure(
            min_level=self.config.get("log_level", "info"),
            forward_level=self.config.get("log_forward_level", "error"),
            send_to_group=self.config.get("send_log_to_group", False),
            target_group=self.config.get("log_target_group", ""),
            forward_cb=self.api.send_group_msg,
        )

        # 引擎
        self.platform = self.config.get("platform") or DEFAULT_PLATFORM
        self.engine = TriggerEngine(self.base_dir, self.config,
                                    api=self.api, platform=self.platform)

        # 反刷屏 / 去重
        self.anti_spam = AntiSpam(
            self.config.get("anti_spam_window", 30),
            self.config.get("anti_spam_count", 3),
        ) if self.config.get("anti_spam_enabled", True) else None
        self.engine.handler.anti_spam = self.anti_spam
        self.dedup = MessageDeduplicator(max_size=2000, ttl=300)

        self.main_map: Dict[str, Dict] = {}
        self.emergency = EmergencyController(
            self.engine.loader, self.api, self.engine.handler,
            on_global_disable=self._on_global_disable,
            on_group_clear=self._on_group_clear)

        self.cmd_handler = CommandHandler(
            self.engine.loader, self.engine.handler, self.api,
            self.main_map, self.engine.loader.group_cache,
            emergency=self.emergency, bot=self,
            prefix=self.config.get("command_prefix", "/mt"))

        self._running = True
        self._reload_task: Optional[asyncio.Task] = None
        self._cron_tasks: Dict[str, asyncio.Task] = {}

    # ---------------- 配置 ----------------

    def _load_config(self, override: Optional[Dict] = None) -> Dict:
        config = dict(DEFAULT_CONFIG)
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    config.update(json.load(f))
            except Exception as e:
                print(f"[启动] 配置解析失败，使用默认值: {e}")
        elif override is None:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            print(f"[启动] 已生成默认配置: {self.config_path}")
        if override:
            config.update(override)
        if not config.get("mt_plugins_dir"):
            config["mt_plugins_dir"] = os.path.join(
                config.get("plugins_dir", "plugins"), "MTPlugins")
        return config

    # ---------------- 加载 / 重载 ----------------

    def reload(self) -> Dict[str, int]:
        stats = self.engine.reload()
        self.main_map.clear()
        self.main_map.update({t.get("name", ""): t
                              for t in self.engine.loader.global_triggers})
        self.cmd_handler.main_triggers = self.main_map
        self.cmd_handler.group_cache = self.engine.loader.group_cache
        return stats

    async def _reload_loop(self):
        interval = self.config.get("reload_interval", 60)
        if interval <= 0:
            return
        while self._running:
            try:
                await asyncio.sleep(interval)
                self.reload()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"定时重载异常: {e}")

    # ---------------- Cron ----------------

    def _all_triggers(self) -> List[Dict]:
        loader = self.engine.loader
        out = list(loader.global_triggers)
        for group in loader.group_cache.values():
            out.extend(group)
        for user in loader.user_cache.values():
            out.extend(user)
        return out

    async def _schedule_cron(self):
        for task in self._cron_tasks.values():
            if not task.done():
                task.cancel()
        self._cron_tasks.clear()
        if not HAS_CRONITER:
            return
        for trigger in self._all_triggers():
            if trigger.get("trigger_type", "") == "cron":
                pattern = trigger.get("trigger_pattern", "")
                if not pattern or not croniter.is_valid(pattern):
                    continue
                task = asyncio.create_task(self._cron_worker(trigger))
                self._cron_tasks[trigger.get("name", "unknown")] = task

    async def _cron_scheduler(self):
        while self._running:
            try:
                await asyncio.sleep(60)
                await self._schedule_cron()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Cron 调度异常: {e}")

    async def _cron_worker(self, trigger: Dict):
        name = trigger.get("name", "unknown")
        pattern = trigger.get("trigger_pattern", "")
        try:
            cron = croniter(pattern, datetime.now())
        except Exception:
            return
        while self._running:
            try:
                next_time = cron.get_next(datetime)
                wait = (next_time - datetime.now()).total_seconds()
                if wait > 0:
                    await asyncio.sleep(wait)
                variables = self.engine.handler.build_variables(None, "", None)
                variables["umo"] = trigger.get("_umo", "")
                result = await self.engine.handler.execute_response(
                    trigger, variables, None)
                target = trigger.get("target", "")
                umo = str(trigger.get("_umo") or "")
                if umo and umo.count(":") >= 2:
                    _, _, sid = umo.split(":", 2)
                    if sid.isdigit() and "GroupMessage" in umo:
                        await self.api.send_group_msg(int(sid), result)
                    elif sid.isdigit():
                        await self.api.send_private_msg(int(sid), result)
                elif target and target.isdigit():
                    if len(target) >= 6:
                        await self.api.send_group_msg(int(target), result)
                    else:
                        await self.api.send_private_msg(int(target), result)
                else:
                    logger.info(f"Cron {name} 执行: {str(result)[:100]}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Cron {name} 异常: {e}")
                await asyncio.sleep(60)

    # ---------------- 事件 ----------------

    async def on_event(self, raw: Dict):
        try:
            if raw.get("post_type") != "message":
                return
            if raw.get("message_type") == "message_sent":
                return

            ctx = MessageContext.from_onebot(raw, platform=self.platform)
            message = ctx.text or ""
            if not message.strip():
                return

            prefix = self.config.get("command_prefix", "/mt")
            stripped = message.strip()
            if stripped == prefix or stripped.startswith(prefix + " "):
                await self._handle_cmd(ctx, stripped[len(prefix):].strip())
                return

            if ctx.message_id:
                if not await self.dedup.check(msg_id=ctx.message_id):
                    return
            else:
                ch = hashlib.md5(
                    f"{ctx.group_id}:{ctx.user_id}:{message}".encode()).hexdigest()
                if not await self.dedup.check(content_hash=ch):
                    return

            if self.emergency.is_globally_locked():
                return
            if ctx.group_id and self.emergency.is_group_locked(ctx.group_id):
                return

            reply = await self.engine.handle(ctx)
            if reply is None:
                return
            if ctx.message_id:
                self.dedup.mark(msg_id=ctx.message_id)
            await self._reply(ctx, reply)
        except Exception as e:
            logger.exception(f"on_event 异常: {e}")

    async def _reply(self, ctx: MessageContext, text: str):
        try:
            if ctx.group_id:
                await self.api.send_group_msg(int(ctx.group_id), text)
            else:
                await self.api.send_private_msg(int(ctx.user_id), text)
        except Exception as e:
            logger.debug(f"发送消息失败: {e}")

    async def _handle_cmd(self, ctx: MessageContext, args: str):
        parts = args.strip().split()
        sub = parts[0] if parts else ""
        if self.emergency.is_globally_locked() and sub != "状态":
            await self._reply(ctx, "[错误]全局紧急锁定中，所有操作已暂停喵~")
            return
        if ctx.group_id and self.emergency.is_group_locked(ctx.group_id):
            if sub not in ("紧急停止", "紧急清除", "状态", "支持", "反对"):
                remaining = self.emergency.get_lock_remaining(ctx.group_id)
                await self._reply(ctx, f"[错误]该群已被紧急锁定，剩余{remaining // 60}分钟喵~")
                return
        try:
            result = await self.cmd_handler.handle(ctx, args)
            await self._reply(ctx, str(result))
        except Exception as e:
            logger.exception(f"命令异常: {e}")
            await self._reply(ctx, f"[错误]命令执行失败喵：{e}")

    def _on_group_clear(self, gid: str):
        self.engine.loader.group_cache.pop(gid, None)

    async def _on_global_disable(self):
        pass

    # ---------------- 生命周期 ----------------

    async def run(self):
        version = _read_version()
        logger.info("=" * 52)
        logger.info(f"  MeowTrigger {version} - OneBot V11 独立版")
        logger.info("=" * 52)
        logger.info(f"WebSocket: {self.config.get('ws_url')}")
        logger.info(f"配置文件: {self.config_path}")
        logger.info(f"插件目录: {self.engine.plugins_dir}")
        logger.info(f"MTPlugins: {self.engine.mt_dir}")
        logger.info(f"命令前缀: {self.config.get('command_prefix', '/mt')}")

        stats = self.reload()
        logger.info(f"触发器统计: {stats}")
        await self.emergency.start()
        self.client.on_event(self.on_event)

        self._reload_task = asyncio.create_task(self._reload_loop())
        cron_task = asyncio.create_task(self._cron_scheduler())

        try:
            await self.client.connect()
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            if self._reload_task:
                self._reload_task.cancel()
            cron_task.cancel()
            for task in self._cron_tasks.values():
                task.cancel()
            await self.emergency.stop()
            await self.client.close()
            logger.info("机器人已停止")


def _read_version() -> str:
    try:
        from . import __version__
        return __version__
    except Exception:  # pragma: no cover
        return "v1.1.0"


__all__ = ["MeowTriggerApp", "DEFAULT_CONFIG"]
