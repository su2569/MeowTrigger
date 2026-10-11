"""
MeowTrigger - 独立自定义触发器机器人 v1.0.0
OneBot V11 协议 / 仅依赖 websockets (+ 可选 croniter)
"""
import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from typing import Dict, List

# 确保能 import core
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import (
    logger, MessageParser, AntiSpam, MessageDeduplicator,
    RuntimeSecurityChecker, ScriptExecutor, OneBotClient, OneBotAPI,
    OneBotEvent, ConfigLoader, EventHandler, CommandHandler,
    EmergencyController,
)

try:
    from croniter import croniter
    HAS_CRONITER = True
except ImportError:
    HAS_CRONITER = False


DEFAULT_CONFIG = {
    "ws_url": "ws://127.0.0.1:3001",
    "access_token": "",
    "reconnect_interval": 5,
    "reload_interval": 60,
    "command_prefix": "/mt",
    "default_permission": "all",
    "default_cooldown": 0,
    "script_timeout": 300,
    "allow_system_cmd": False,
    "system_cmd_whitelist": [],
    "admin_users": [],
    "script_paths": [],
    "log_level": "info",
    "log_forward_level": "error",
    "log_target_group": "",
    "send_log_to_group": False,
    "anti_spam_enabled": True,
    "anti_spam_window": 30,
    "anti_spam_count": 3,
    "plugins_dir": "plugins",
    "sandbox_type": "auto",
    "venv_path": "",
    "custom_python": "",
    "custom_node": "",
    "execution_mode": "local",
    "message_parse_mode": "auto",
}


class MeowTrigger:
    def __init__(self):
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(self.base_dir, "config", "config.json")
        self.config = self._load_config()
        self.plugins_dir = os.path.join(
            self.base_dir, self.config.get("plugins_dir", "plugins"))
        os.makedirs(self.plugins_dir, exist_ok=True)

        # OneBot 客户端
        self.client = OneBotClient(
            ws_url=self.config.get("ws_url", "ws://127.0.0.1:3001"),
            access_token=self.config.get("access_token", ""),
            reconnect_interval=self.config.get("reconnect_interval", 5),
        )
        self.api = OneBotAPI(self.client)

        # 日志
        logger.configure(
            min_level=self.config.get("log_level", "info"),
            forward_level=self.config.get("log_forward_level", "error"),
            send_to_group=self.config.get("send_log_to_group", False),
            target_group=self.config.get("log_target_group", ""),
            forward_cb=self.api.send_group_msg,
        )

        # 组件
        self.parser = MessageParser(self.config.get("message_parse_mode", "auto"))
        self.config_loader = ConfigLoader(self.base_dir, self.plugins_dir)
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
        self.anti_spam = AntiSpam(
            self.config.get("anti_spam_window", 30),
            self.config.get("anti_spam_count", 3),
        ) if self.config.get("anti_spam_enabled", True) else None
        self.security = RuntimeSecurityChecker(strict_mode=True)
        self.dedup = MessageDeduplicator(max_size=2000, ttl=300)

        self.handler = EventHandler(
            self.config_loader, self.executor, self.api, self.parser,
            {}, self.config.get("admin_users", []), self.anti_spam, self.security)

        self._main_triggers: List[Dict] = []
        self._group_cache: Dict[str, List[Dict]] = {}
        self.main_map: Dict[str, Dict] = {}

        self.emergency = EmergencyController(
            self.config_loader, self.api, self.handler,
            on_global_disable=self._on_global_disable,
            on_group_clear=self._on_group_clear)

        self.cmd_handler = CommandHandler(
            self.config_loader, self.handler, self.api,
            self.main_map, self._group_cache,
            emergency=self.emergency, bot=self,
            prefix=self.config.get("command_prefix", "/mt"))

        self._running = True
        self._reload_task = None
        self._cron_tasks: Dict[str, asyncio.Task] = {}

    def _load_config(self) -> Dict:
        default = dict(DEFAULT_CONFIG)
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    default.update(json.load(f))
            except Exception as e:
                print(f"[启动] 配置解析失败，使用默认值: {e}")
        else:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(default, f, ensure_ascii=False, indent=2)
            print(f"[启动] 已生成默认配置: {self.config_path}")
        return default

    async def _on_global_disable(self):
        pass

    def _on_group_clear(self, gid: str):
        self._group_cache.pop(gid, None)

    async def _reload_config(self):
        try:
            mt, gc = self.config_loader.load_all(
                self.config.get("default_permission", "all"),
                self.config.get("default_cooldown", 0))
            self._main_triggers = mt
            self._group_cache = gc
            self.main_map = {t.get("name", ""): t for t in mt}
            self.cmd_handler.main_triggers = self.main_map
            self.cmd_handler.group_cache = self._group_cache
        except Exception as e:
            logger.error(f"配置加载失败: {e}")

    async def _reload_loop(self):
        iv = self.config.get("reload_interval", 60)
        if iv <= 0:
            return
        while self._running:
            try:
                await asyncio.sleep(iv)
                await self._reload_config()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"定时重载异常: {e}")

    async def _schedule_cron(self):
        for t in self._cron_tasks.values():
            if not t.done():
                t.cancel()
        self._cron_tasks.clear()
        if not HAS_CRONITER:
            return
        all_t = list(self._main_triggers)
        for g in self._group_cache.values():
            all_t.extend(g)
        for trigger in all_t:
            if trigger.get("trigger_type", "") == "cron":
                p = trigger.get("trigger_pattern", "")
                if not p or not croniter.is_valid(p):
                    continue
                t = asyncio.create_task(self._cron_worker(trigger))
                self._cron_tasks[trigger.get("name", "unknown")] = t

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
                nt = cron.get_next(datetime)
                w = (nt - datetime.now()).total_seconds()
                if w > 0:
                    await asyncio.sleep(w)
                v = self.handler.build_variables(None, "", None)
                r = await self.handler.execute_response(trigger, v, None)
                target = trigger.get("target", "")
                if target and target.isdigit():
                    if len(target) >= 6:
                        await self.api.send_group_msg(int(target), r)
                    else:
                        await self.api.send_private_msg(int(target), r)
                else:
                    logger.info(f"Cron {name} 执行: {str(r)[:100]}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Cron {name} 异常: {e}")
                await asyncio.sleep(60)

    async def on_event(self, raw: Dict):
        try:
            if raw.get("post_type") != "message":
                return
            if raw.get("message_type") == "message_sent":
                return

            event = OneBotEvent(raw)
            message = event.message_str or ""

            prefix = self.config.get("command_prefix", "/mt")
            stripped = message.strip()
            if stripped == prefix or stripped.startswith(prefix + " "):
                args = stripped[len(prefix):].strip()
                await self._handle_cmd(event, args)
                return

            msg_id = event.message_obj.message_id
            if msg_id:
                if not await self.dedup.check(msg_id=msg_id):
                    return
            else:
                ch = hashlib.md5(
                    f"{event.group_id}:{event.user_id}:{message}".encode()).hexdigest()
                if not await self.dedup.check(content_hash=ch):
                    return

            if self.emergency.is_globally_locked():
                return
            if event.group_id and self.emergency.is_group_locked(event.group_id):
                return

            triggers = self.handler.get_effective_triggers(
                event, self._main_triggers, self._group_cache)

            for trigger in triggers:
                if not trigger.get("enabled", True):
                    continue
                if trigger.get("trigger_type", "") == "cron":
                    continue
                matched, match_content, trigger_args = self.handler.check_trigger_match(
                    trigger, message)
                if not matched:
                    continue
                tname = trigger.get("name", "")
                perm = trigger.get("permission", "all")
                if not self.handler.check_permission(event, perm):
                    await self._reply(event, f"[阻止]权限不足，触发器『{tname}』需要『{perm}』权限喵。")
                    return
                cd = trigger.get("cooldown", 0)
                if self.handler.is_on_cooldown(event.user_id, tname, cd):
                    continue
                if self.anti_spam:
                    ok, reason = await self.anti_spam.check(event.user_id, tname)
                    if not ok:
                        await self._reply(event, reason)
                        return
                try:
                    is_admin = self.handler.is_ab_admin(event)
                    v = self.handler.build_variables(event, trigger_args, match_content)
                    r = await self.handler.execute_response(
                        trigger, v, event, is_admin,
                        self.config.get("execution_mode", "local"))
                except Exception as e:
                    logger.exception(f"触发器 {tname} 执行异常: {e}")
                    await self._reply(event, f"[错误]触发器『{tname}』执行失败喵：{e}")
                    return
                if not r or not str(r).strip():
                    r = "[提示]触发器执行完成，但无输出内容喵~"
                if msg_id:
                    self.dedup.mark(msg_id=msg_id)
                await self._reply(event, str(r))
                return
        except Exception as e:
            logger.exception(f"on_event 异常: {e}")

    async def _reply(self, event: OneBotEvent, text: str):
        try:
            if event.group_id:
                await self.api.send_group_msg(int(event.group_id), text)
            else:
                await self.api.send_private_msg(int(event.user_id), text)
        except Exception as e:
            logger.debug(f"发送消息失败: {e}")

    async def _handle_cmd(self, event: OneBotEvent, args: str):
        stripped = args.strip().split()
        sub = stripped[0] if stripped else ""
        if self.emergency.is_globally_locked() and sub != "状态":
            await self._reply(event, "[错误]全局紧急锁定中，所有操作已暂停喵~")
            return
        if event.group_id and self.emergency.is_group_locked(event.group_id):
            if sub not in ("紧急停止", "紧急清除", "状态", "支持", "反对"):
                rem = self.emergency.get_lock_remaining(event.group_id)
                await self._reply(event, f"[错误]该群已被紧急锁定，剩余{rem // 60}分钟喵~")
                return
        try:
            result = await self.cmd_handler.handle(event, args)
            await self._reply(event, str(result))
        except Exception as e:
            logger.exception(f"命令异常: {e}")
            await self._reply(event, f"[错误]命令执行失败喵：{e}")

    async def run(self):
        logger.info("=" * 52)
        logger.info("  MeowTrigger v1.0.0 - OneBot V11 独立版")
        logger.info("=" * 52)
        logger.info(f"WebSocket: {self.config.get('ws_url')}")
        logger.info(f"配置文件: {self.config_path}")
        logger.info(f"插件目录: {self.plugins_dir}")
        logger.info(f"命令前缀: {self.config.get('command_prefix', '/mt')}")

        await self._reload_config()
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
            for t in self._cron_tasks.values():
                t.cancel()
            await self.emergency.stop()
            await self.client.close()
            logger.info("机器人已停止")


def main():
    try:
        asyncio.run(MeowTrigger().run())
    except KeyboardInterrupt:
        logger.info("收到中断信号，退出")


if __name__ == "__main__":
    main()
