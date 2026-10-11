"""/mt 命令处理器"""
from typing import Dict, List, Optional

from .logger import logger


class CommandHandler:
    def __init__(self, config_loader, handler, api, main_triggers, group_cache,
                 emergency=None, bot=None, prefix="/mt"):
        self.config_loader = config_loader
        self.handler = handler
        self.api = api
        self.main_triggers = main_triggers
        self.group_cache = group_cache
        self.emergency = emergency
        self.bot = bot
        self.prefix = prefix

    async def handle(self, event, args: str) -> str:
        arg = args.strip()
        if not arg:
            return "→↗↘↗↘↑↓←→……↑.↓.→（一阵强劲的音乐）"
        parts = arg.split()
        sub = parts[0]
        gid = self.handler.get_group_id(event)

        if sub == "帮助": return self._help()
        if sub == "列表": return self._list()
        if sub == "查询":
            if len(parts) < 2:
                return f"[错误]请指定触发器名称喵。{self.prefix} 查询 <名称>"
            return self._query(event, parts[1])
        if sub == "触发":
            if len(parts) < 2:
                return f"[错误]请指定触发器名称喵。{self.prefix} 触发 <名称> [参数...]"
            return await self._manual(event, parts[1],
                                      " ".join(parts[2:]) if len(parts) > 2 else "")
        if sub == "重载": return await self._reload(event)
        if sub == "群添加":
            if not gid: return "[错误]群管理命令只能在群聊中使用喵。"
            if not self.handler.check_permission(event, "admin"):
                return "[错误]只有群主/管理员才能添加群触发器喵。"
            if len(parts) < 6:
                return f"[错误]参数不足：{self.prefix} 群添加 <名称> <类型> <触发词> <响应类型> <响应内容> [描述]"
            name, ttype, pattern, rtype, content = parts[1:6]
            desc = " ".join(parts[6:]) if len(parts) > 6 else ""
            return self._add_group(gid, {
                "name": name, "trigger_type": ttype, "trigger_pattern": pattern,
                "response_type": rtype, "response_content": content,
                "description": desc, "permission": "all", "cooldown": 0, "enabled": True})
        if sub == "群删除":
            if not gid: return "[错误]群管理命令只能在群聊中使用喵。"
            if not self.handler.check_permission(event, "admin"):
                return "[错误]只有群主/管理员才能删除群触发器喵。"
            if len(parts) < 2: return "[错误]请指定触发器名称喵。"
            return self._del_group(gid, parts[1])
        if sub == "群列表":
            if not gid: return "[错误]群管理命令只能在群聊中使用喵。"
            ts = self.config_loader.load_group(gid, "all", 0)
            if not ts: return "[信息]本群暂无专属触发器"
            lines = [f"本群专属触发器（共{len(ts)}个）："]
            for t in ts:
                lines.append(f"  {t.get('name')} ({t.get('trigger_type')}: {t.get('trigger_pattern')})")
            return "\n".join(lines)
        if sub == "强制解锁群":
            if not self.handler.is_ab_admin(event):
                return "[错误]只有管理员才能强制解锁喵。"
            tg = parts[1] if len(parts) > 1 else gid
            if not tg: return "[错误]请指定群号喵。"
            self.emergency.force_unlock_group(tg)
            return f"[成功]群 {tg} 已强制解锁喵~"
        if sub == "强制解锁全局":
            if not self.handler.is_ab_admin(event):
                return "[错误]只有管理员才能强制解锁喵。"
            self.emergency.force_unlock_global()
            return "[成功]全局锁定已强制解除喵~"
        if sub == "紧急停止":
            if not self.emergency: return "[错误]紧急控制模块未启用喵~"
            uid = self.handler.get_sender_id(event)
            _, msg = await self.emergency.start_stop(event, gid, uid)
            return msg
        if sub == "紧急清除":
            if not self.emergency: return "[错误]紧急控制模块未启用喵~"
            uid = self.handler.get_sender_id(event)
            tg = parts[1] if len(parts) > 1 else None
            _, msg = await self.emergency.start_clear(event, gid, uid, tg)
            return msg
        if sub == "支持":
            if not self.emergency: return "[错误]紧急控制模块未启用喵~"
            return await self.emergency.vote(event, gid, self.handler.get_sender_id(event), True)
        if sub == "反对":
            if not self.emergency: return "[错误]紧急控制模块未启用喵~"
            return await self.emergency.vote(event, gid, self.handler.get_sender_id(event), False)
        if sub == "状态":
            if not self.emergency: return "[错误]紧急控制模块未启用喵~"
            s = self.emergency.get_status(gid)
            if self.bot and hasattr(self.bot, "dedup"):
                st = self.bot.dedup.get_stats()
                s += f"\n\n📊 去重统计：总检查 {st['total_checked']} | 重复 {st['duplicate']} | 缓存 {st['cache_size']}"
            return s
        return "喵喵喵？"

    def _help(self) -> str:
        p = self.prefix
        return "\n".join([
            "=== MeowTrigger 帮助 ===", "",
            f"{p} 帮助 - 显示此帮助",
            f"{p} 列表 - 查看所有可用触发器",
            f"{p} 查询 <名称> - 查询触发器详情",
            f"{p} 触发 <名称> [参数...] - 手动触发",
            f"{p} 重载 - 重载配置（管理员）",
            f"{p} 群添加 <名称> <类型> <触发词> <响应类型> <内容> [描述]",
            f"{p} 群删除 <名称>",
            f"{p} 群列表 - 查看本群专属触发器",
            f"{p} 强制解锁群 [群号] - 管理员",
            f"{p} 强制解锁全局 - 管理员",
            f"{p} 紧急停止 - 投票/管理员",
            f"{p} 紧急清除 [群号] - 管理员",
            f"{p} 支持 / {p} 反对 - 投票",
            f"{p} 状态 - 查看紧急状态",
        ])

    def _list(self) -> str:
        plugins = {}
        for t in self.main_triggers.values():
            pname = t.get("plugin_name", "全局触发器")
            pdesc = t.get("_plugin_desc", "")
            tname = t.get("name", "unnamed")
            plugins.setdefault(pname, {"desc": pdesc, "triggers": []})
            if tname not in plugins[pname]["triggers"]:
                plugins[pname]["triggers"].append(tname)
        for gid, gts in self.group_cache.items():
            for t in gts:
                pname = f"群 {gid} 触发器"
                pdesc = t.get("_plugin_desc", "")
                tname = t.get("name", "unnamed")
                plugins.setdefault(pname, {"desc": pdesc, "triggers": []})
                if tname not in plugins[pname]["triggers"]:
                    plugins[pname]["triggers"].append(tname)
        if not plugins:
            return "[信息]暂无可用的触发器喵~"
        lines = ["=== 触发器列表 ==="]
        for pname, pdata in sorted(plugins.items()):
            lines.append(f"\n📦 {pname}")
            lines.append(f"📝 {pdata['desc'] or '暂无简介'}")
            lines.append(f"🔔 触发器（共{len(pdata['triggers'])}个）：")
            lines.extend(f"  • {n}" for n in pdata["triggers"])
        return "\n".join(lines)

    def _query(self, event, name: str) -> str:
        ts = self.handler.get_effective_triggers(
            event, list(self.main_triggers.values()), self.group_cache)
        for t in ts:
            if t.get("name", "") == name:
                lines = [f"=== {name} ==="]
                for k, v in t.items():
                    if not k.startswith("_"):
                        lines.append(f"{k}: {v}")
                return "\n".join(lines)
        return f"[错误]未找到名为『{name}』的触发器喵。"

    async def _manual(self, event, name: str, args: str) -> str:
        ts = self.handler.get_effective_triggers(
            event, list(self.main_triggers.values()), self.group_cache)
        target = None
        for t in ts:
            if t.get("name", "") == name:
                target = t
                break
        if not target:
            return f"[错误]未找到名为『{name}』的触发器喵。"
        if not target.get("enabled", True):
            return f"[错误]触发器『{name}』当前已禁用喵。"
        perm = target.get("permission", "all")
        if not self.handler.check_permission(event, perm):
            return f"[阻止]权限不足，触发器『{name}』需要『{perm}』权限喵。"
        uid = self.handler.get_sender_id(event)
        cd = target.get("cooldown", 0)
        if self.handler.is_on_cooldown(uid, name, cd):
            return f"[阻止]触发器『{name}』正在冷却中喵~"
        try:
            is_admin = self.handler.is_ab_admin(event)
            v = self.handler.build_variables(event, args, args)
            return await self.handler.execute_response(target, v, event, is_admin)
        except Exception as e:
            return f"[错误]手动触发失败喵：{e}"

    async def _reload(self, event) -> str:
        if not self.handler.is_ab_admin(event):
            return "[错误]只有管理员才能重载配置喵。"
        try:
            mt, gc = self.config_loader.load_all("all", 0)
            self.main_triggers.clear()
            self.main_triggers.update({t["name"]: t for t in mt})
            self.group_cache.clear()
            self.group_cache.update(gc)
            return "[成功]配置已重载喵！"
        except Exception as e:
            return f"[错误]配置重载失败喵：{e}"

    def _add_group(self, gid: str, trigger: Dict) -> str:
        ts = self.config_loader.load_group(gid, "all", 0)
        for t in ts:
            if t.get("name", "") == trigger.get("name", ""):
                return f"[错误]该群已存在名为『{trigger.get('name')}』的触发器喵。"
        ts.append(trigger)
        self.config_loader.save_group(gid, ts)
        self.group_cache[gid] = ts
        return f"[成功]群触发器『{trigger.get('name')}』已添加喵！"

    def _del_group(self, gid: str, name: str) -> str:
        ts = self.config_loader.load_group(gid, "all", 0)
        new = [t for t in ts if t.get("name", "") != name]
        if len(new) == len(ts):
            return f"[错误]该群不存在名为『{name}』的触发器喵。"
        self.config_loader.save_group(gid, new)
        self.group_cache[gid] = new
        return f"[成功]群触发器『{name}』已删除喵！"
