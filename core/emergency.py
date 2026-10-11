"""紧急控制：全局/群级锁定 + 投票"""
import asyncio
import time
from typing import Dict, Optional, Tuple

from .logger import logger


class EmergencyController:
    VOTE_TIMEOUT = 300
    VOTE_THRESHOLD = 3
    LOCK_DURATION = 3600

    def __init__(self, config_loader, api, handler,
                 on_global_disable=None, on_group_clear=None):
        self.config_loader = config_loader
        self.api = api
        self.handler = handler
        self._on_global_disable = on_global_disable
        self._on_group_clear = on_group_clear
        self._group_locks: Dict[str, float] = {}
        self._global_lock = 0
        self._global_comm_disabled = False
        self._votes: Dict[str, Dict] = {}
        self._group_vote_map: Dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._task = None

    async def start(self):
        self._task = asyncio.create_task(self._cleanup_loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _cleanup_loop(self):
        while True:
            try:
                await asyncio.sleep(60)
                self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"清理循环异常: {e}")

    def _cleanup_expired(self):
        now = time.time()
        expired = [v for v, d in self._votes.items()
                   if now - d["start_time"] > self.VOTE_TIMEOUT + 10]
        for v in expired:
            vote = self._votes.pop(v, None)
            if vote:
                self._group_vote_map.pop(vote.get("group_id", ""), None)
        if len(self._votes) > 50:
            sv = sorted(self._votes.items(), key=lambda x: x[1]["start_time"])
            for v, d in sv[:len(sv) - 50]:
                self._votes.pop(v, None)
                self._group_vote_map.pop(d.get("group_id", ""), None)
        for gid in [g for g, ts in self._group_locks.items() if ts <= now]:
            self._group_locks.pop(gid, None)
        if 0 < self._global_lock <= now:
            self._global_lock = 0
            self._global_comm_disabled = False

    def is_group_locked(self, group_id: str) -> bool:
        if not group_id:
            return self.is_globally_locked()
        exp = self._group_locks.get(group_id, 0)
        if exp > time.time():
            return True
        if exp > 0:
            self._group_locks.pop(group_id, None)
        return self.is_globally_locked()

    def is_globally_locked(self) -> bool:
        if self._global_lock > time.time():
            return True
        if self._global_lock > 0:
            self._global_lock = 0
            self._global_comm_disabled = False
        return False

    def get_lock_remaining(self, group_id: str) -> int:
        if self.is_globally_locked():
            return max(0, int(self._global_lock - time.time()))
        exp = self._group_locks.get(group_id, 0)
        return max(0, int(exp - time.time())) if exp > time.time() else 0

    def force_unlock_group(self, gid: str):
        self._group_locks.pop(gid, None)

    def force_unlock_global(self):
        self._global_lock = 0
        self._global_comm_disabled = False

    def clear_all(self):
        self._global_lock = 0
        self._global_comm_disabled = False
        self._group_locks.clear()
        self._votes.clear()
        self._group_vote_map.clear()

    async def start_stop(self, event, group_id: str, user_id: str) -> Tuple[bool, str]:
        if self.is_globally_locked():
            return False, "[错误]全局紧急锁定中喵~"
        if group_id and self.is_group_locked(group_id):
            return False, "[错误]该群已被紧急锁定喵~"
        if self.handler.is_ab_admin(event):
            self._global_lock = time.time() + self.LOCK_DURATION
            self._global_comm_disabled = True
            if self._on_global_disable:
                try:
                    await self._on_global_disable()
                except Exception:
                    pass
            t = time.strftime("%H:%M", time.localtime(self._global_lock))
            return True, f"[警告]触发器已失效，通讯将被关闭，并在{t}重新开启喵~"
        if self.handler.is_group_admin(event):
            if not group_id:
                return False, "[错误]紧急停止需要在群聊中使用喵~"
            self._group_locks[group_id] = time.time() + self.LOCK_DURATION
            return True, "[警告]紧急停止生效，该群在一小时内无法使用触发器喵~"
        if not group_id:
            return False, "[错误]紧急停止需要在群聊中使用喵~"
        ev = self._group_vote_map.get(group_id)
        if ev and ev in self._votes:
            return False, "[错误]该群已有进行中的投票喵~"
        vid = f"stop_{group_id}_{int(time.time())}"
        self._votes[vid] = {"type": "stop", "group_id": group_id,
                            "start_time": time.time(), "support": 0, "oppose": 0,
                            "voters": set(), "status": "active", "initiator": user_id}
        self._group_vote_map[group_id] = vid
        asyncio.create_task(self._vote_timer(vid))
        return False, "[通知]投票开始了喵~可以通过「/mt 支持」和「/mt 反对」进行投票。\n5分钟后自动结束，赞成-反对≥3时生效。"

    async def start_clear(self, event, group_id: str, user_id: str,
                          target_group: str = None) -> Tuple[bool, str]:
        if self.handler.is_ab_admin(event):
            gid = target_group or group_id
            if not gid:
                return False, "[错误]请指定群号或在群聊中使用喵~"
            return await self._do_clear_group(gid, by_admin=True)
        if self.handler.is_group_admin(event) and group_id:
            return await self._do_clear_group(group_id, by_admin=True)
        if not group_id:
            return False, "[错误]紧急清除需要在群聊中使用喵~"
        ev = self._group_vote_map.get(group_id)
        if ev and ev in self._votes:
            return False, "[错误]该群已有进行中的投票喵~"
        vid = f"clear_{group_id}_{int(time.time())}"
        self._votes[vid] = {"type": "clear", "group_id": group_id,
                            "start_time": time.time(), "support": 0, "oppose": 0,
                            "voters": set(), "status": "active", "initiator": user_id}
        self._group_vote_map[group_id] = vid
        asyncio.create_task(self._vote_timer(vid))
        return False, "[通知]投票开始了喵~可以通过「/mt 支持」和「/mt 反对」进行投票。\n5分钟后自动结束，赞成-反对≥3时生效。"

    async def vote(self, event, group_id: str, user_id: str, support: bool) -> str:
        if not group_id:
            return "[错误]投票需要在群聊中进行喵~"
        vid = self._group_vote_map.get(group_id)
        if not vid or vid not in self._votes:
            return "[错误]当前群没有进行中的投票喵~"
        async with self._lock:
            v = self._votes.get(vid)
            if not v or v["status"] != "active":
                return "[错误]该投票已结束喵~"
            if user_id in v["voters"]:
                return "[错误]你已经投过票了喵~"
            v["voters"].add(user_id)
            if support:
                v["support"] += 1
            else:
                v["oppose"] += 1
        diff = v["support"] - v["oppose"]
        if diff >= self.VOTE_THRESHOLD:
            v["status"] = "passed"
            asyncio.create_task(self._process_passed_vote(vid))
            return f"[通知]你已{'支持' if support else '反对'}，投票已达到阈值，正在处理..."
        return f"[通知]你已{'支持' if support else '反对'}，当前赞成{v['support']}票，反对{v['oppose']}票。还需{self.VOTE_THRESHOLD - diff}票生效喵~"

    async def _vote_timer(self, vid: str):
        await asyncio.sleep(self.VOTE_TIMEOUT)
        await self._end_vote(vid)

    async def _process_passed_vote(self, vid: str):
        v = self._votes.pop(vid, None)
        if not v:
            return
        self._group_vote_map.pop(v.get("group_id", ""), None)
        gid = v["group_id"]
        msg = f"[通知]投票结束了喵~\n支持：{v['support']}票\n反对：{v['oppose']}票\n"
        if v["type"] == "stop":
            self._group_locks[gid] = time.time() + self.LOCK_DURATION
            msg += "停止生效喵~"
        else:
            await self._do_clear_group(gid, by_admin=False)
            msg += "清除生效喵~"
        try:
            await self.api.send_group_msg(int(gid), msg)
        except Exception:
            pass

    async def _end_vote(self, vid: str):
        v = self._votes.get(vid)
        if not v:
            return
        if v["status"] in ("passed", "ended"):
            self._votes.pop(vid, None)
            self._group_vote_map.pop(v.get("group_id", ""), None)
            return
        v = self._votes.pop(vid, None)
        self._group_vote_map.pop(v.get("group_id", ""), None)
        v["status"] = "ended"
        diff = v["support"] - v["oppose"]
        gid = v["group_id"]
        msg = f"[通知]投票结束了喵~\n支持：{v['support']}票\n反对：{v['oppose']}票\n"
        if diff >= self.VOTE_THRESHOLD:
            if v["type"] == "stop":
                self._group_locks[gid] = time.time() + self.LOCK_DURATION
                msg += "停止生效喵~"
            else:
                await self._do_clear_group(gid, by_admin=False)
                msg += "清除生效喵~"
        else:
            msg += f"{'停止' if v['type'] == 'stop' else '清除'}无效喵~"
        try:
            await self.api.send_group_msg(int(gid), msg)
        except Exception:
            pass

    async def _do_clear_group(self, gid: str, by_admin: bool = True) -> Tuple[bool, str]:
        try:
            self.config_loader.save_group(gid, [])
            self._group_locks[gid] = time.time() + self.LOCK_DURATION
            if self._on_group_clear:
                self._on_group_clear(gid)
            if by_admin:
                return True, "[警告]紧急清除生效，该群在一小时内无法使用、上传触发器喵~"
            return True, ""
        except Exception as e:
            return False, f"[错误]清除失败喵：{e}"

    def get_status(self, group_id: str) -> str:
        lines = ["=== 紧急状态 ==="]
        if self.is_globally_locked():
            rem = max(0, int(self._global_lock - time.time()))
            lines.append(f"🚨 全局锁定中，剩余{rem // 60}分钟")
            if self._global_comm_disabled:
                lines.append("📡 通讯已关闭")
        elif group_id and self.is_group_locked(group_id):
            rem = self.get_lock_remaining(group_id)
            lines.append(f"⚠️ 该群锁定中，剩余{rem // 60}分钟")
        else:
            lines.append("✅ 当前无紧急锁定")
        av = []
        for _, v in self._votes.items():
            if v["status"] == "active":
                gid = v.get("group_id", "")
                if not group_id or gid == group_id:
                    vt = "停止" if v["type"] == "stop" else "清除"
                    el = int(time.time() - v["start_time"])
                    av.append(f"  {gid}: {vt}投票进行中，剩余{max(0, self.VOTE_TIMEOUT - el) // 60}分钟，"
                              f"赞成{v['support']}反对{v['oppose']}")
        if av:
            lines.append("📊 活跃投票：")
            lines.extend(av)
        return "\n".join(lines)
