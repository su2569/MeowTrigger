"""事件处理器：匹配、权限、响应执行"""
import re
import time
from typing import Dict, List, Optional, Tuple

from .logger import logger


class EventHandler:
    def __init__(self, config_loader, executor, api, parser, components,
                 admin_users=None, anti_spam=None, security_checker=None):
        self.config_loader = config_loader
        self.executor = executor
        self.api = api
        self.parser = parser
        self.components = components
        self.admin_users = admin_users or []
        self.anti_spam = anti_spam
        self.security = security_checker
        self.cooldown_records: Dict[str, float] = {}

    def get_group_id(self, event) -> str:
        return event.get_group_id() if event else ""

    def get_sender_id(self, event) -> str:
        return event.get_sender_id() if event else ""

    def get_sender_name(self, event) -> str:
        return event.get_sender_name() if event else "未知用户"

    def is_ab_admin(self, event) -> bool:
        uid = self.get_sender_id(event)
        return bool(uid) and uid in [str(u) for u in self.admin_users]

    def is_group_admin(self, event) -> bool:
        if not event:
            return False
        s = event.message_obj.sender
        if str(s.role or "").lower() in ("admin", "owner", "administrator"):
            return True
        return self.is_ab_admin(event)

    def check_permission(self, event, required: str) -> bool:
        uid = self.get_sender_id(event)
        if uid in [str(u) for u in self.admin_users]:
            return True
        if required in ("all", "member"):
            return True
        if required == "whitelist":
            t = getattr(event, "trigger_config", None)
            if t:
                wl = t.get("whitelist", [])
                if wl:
                    return str(uid) in [str(w) for w in wl]
            return True
        if required == "admin":
            return self.is_group_admin(event)
        if required == "owner":
            s = event.message_obj.sender
            return str(s.role or "").lower() in ("owner", "administrator") or self.is_ab_admin(event)
        return False

    def is_on_cooldown(self, user_id: str, trigger_name: str, cooldown: int) -> bool:
        if cooldown <= 0:
            return False
        key = f"{user_id}_{trigger_name}"
        now = time.time()
        if len(self.cooldown_records) > 500:
            expired = [k for k, v in self.cooldown_records.items() if now - v > 3600]
            for k in expired:
                self.cooldown_records.pop(k, None)
        last = self.cooldown_records.get(key, 0)
        if now - last < cooldown:
            return True
        self.cooldown_records[key] = now
        return False

    def build_variables(self, event, args: str = "", match: str = None,
                        extra: Dict = None) -> Dict:
        v = {
            "args": args or "",
            "user_id": self.get_sender_id(event) if event else "",
            "user_name": self.get_sender_name(event) if event else "",
            "group_id": self.get_group_id(event) if event else "",
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "date": time.strftime("%Y-%m-%d"),
            "match": match or "",
            "message": event.message_str if event else "",
        }
        if extra:
            v.update(extra)
        return v

    def interpolate(self, template: str, variables: Dict) -> str:
        for k, v in variables.items():
            template = template.replace(f"{{{k}}}", str(v))
        return template

    def check_group_access(self, trigger: Dict, group_id: str) -> bool:
        if trigger.get("group_only", False):
            return True
        if trigger.get("authorize_all", False):
            return True
        auth = trigger.get("authorized_groups", [])
        if auth:
            return group_id in [str(g) for g in auth]
        return True

    def get_effective_triggers(self, event, main_triggers, group_cache) -> List[Dict]:
        gid = self.get_group_id(event)
        gt = group_cache.get(gid, [])
        if not gt and gid:
            gt = self.config_loader.load_group(gid, "all", 0)
            group_cache[gid] = gt
        filtered = [t for t in main_triggers if self.check_group_access(t, gid)]
        return (gt + filtered) if gt else filtered

    def check_trigger_match(self, trigger: Dict, message: str) -> Tuple[bool, Optional[str], str]:
        ttype = trigger.get("trigger_type", "keyword")
        pattern = trigger.get("trigger_pattern", "")
        if ttype == "keyword":
            if pattern.lower() in message.lower():
                return True, pattern, message
            return False, None, message
        if ttype == "fullmatch":
            m = message.strip()
            if m == pattern:
                return True, pattern, ""
            if m.startswith(pattern + " "):
                return True, pattern, m[len(pattern) + 1:]
            return False, None, message
        if ttype == "regex":
            try:
                m = re.search(pattern, message)
                if m:
                    return True, m.group(0), message
            except re.error as e:
                logger.error(f"正则错误 [{trigger.get('name', '?')}]: {e}")
            return False, None, message
        if ttype == "command":
            m = message.strip()
            if m.startswith("/"):
                parts = m[1:].split(None, 1)
                cn = parts[0] if parts else ""
                if cn == pattern:
                    return True, cn, parts[1] if len(parts) > 1 else ""
            return False, None, message
        return False, None, message

    async def execute_response(self, trigger: Dict, variables: Dict, event=None,
                               is_admin: bool = False, mode: str = "local") -> str:
        rtype = trigger.get("response_type", "text")
        content = trigger.get("response_content", "")
        tdir = trigger.get("_base_dir", "")
        is_group = trigger.get("group_only", False) or bool(trigger.get("_group_id", ""))
        stype = trigger.get("script_type", "python")
        emode = trigger.get("execution_mode", mode)

        if rtype == "text":
            return self.interpolate(content, variables)
        if rtype == "script":
            if self.security:
                ok, r = self.security.check_script(content, stype, variables, is_admin)
                if not ok:
                    return r
            return await self.executor.execute_script(
                content, variables, self.api, event, self.components, stype, emode, is_admin)
        if rtype == "script_file":
            if self.security:
                ok, r = self.security.check_script(content, stype, variables, is_admin)
                if not ok:
                    return r
            return await self.executor.execute_script_file(
                content, variables, self.api, event, self.components,
                tdir, is_group, None, stype, emode, is_admin)
        if rtype == "system":
            if self.security:
                ok, r = self.security.check_system_cmd(content, variables)
                if not ok:
                    return r
            return await self.executor.execute_system(content, variables, is_admin, emode)
        return "[错误]未知的响应类型喵"
