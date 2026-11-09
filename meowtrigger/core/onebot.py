"""OneBot V11 WebSocket 客户端 + API 封装"""
import asyncio
import json
from typing import Any, Callable, Dict, List

import websockets

from .logger import logger


class OneBotClient:
    def __init__(self, ws_url: str, access_token: str = "", reconnect_interval: int = 5):
        self.ws_url = ws_url
        self.access_token = access_token
        self.reconnect_interval = reconnect_interval
        self.ws = None
        self.self_id = ""
        self._handlers: List[Callable] = []
        self._pending: Dict[str, asyncio.Future] = {}
        self._echo = 0
        self._running = False

    def on_event(self, handler: Callable):
        self._handlers.append(handler)

    async def connect(self):
        self._running = True
        while self._running:
            try:
                headers = {}
                if self.access_token:
                    headers["Authorization"] = f"Bearer {self.access_token}"
                logger.info(f"连接中: {self.ws_url}")
                async with websockets.connect(
                        self.ws_url, additional_headers=headers,
                        ping_interval=30, ping_timeout=10,
                        max_size=16 * 1024 * 1024) as ws:
                    self.ws = ws
                    logger.success(f"已连接: {self.ws_url}")
                    await self._listen(ws)
            except Exception as e:
                logger.warning(f"连接断开: {e}，{self.reconnect_interval}秒后重连")
                self.ws = None
                await asyncio.sleep(self.reconnect_interval)

    async def _listen(self, ws):
        async for raw in ws:
            try:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                data = json.loads(raw)
            except Exception as e:
                logger.debug(f"消息解析失败: {e}")
                continue

            if "echo" in data and data["echo"] in self._pending:
                fut = self._pending.pop(data["echo"], None)
                if fut and not fut.done():
                    fut.set_result(data)
                continue

            pt = data.get("post_type", "")
            if pt == "meta_event" and data.get("meta_event_type") == "lifecycle":
                self.self_id = str(data.get("self_id", ""))
                logger.info(f"机器人 QQ: {self.self_id}")
            if pt in ("message", "notice", "request", "meta_event"):
                for h in self._handlers:
                    try:
                        if asyncio.iscoroutinefunction(h):
                            asyncio.create_task(h(data))
                        else:
                            h(data)
                    except Exception as e:
                        logger.exception(f"事件处理异常: {e}")

    async def call_action(self, action: str, **kwargs) -> Dict:
        if self.ws is None:
            return {"status": "failed", "retcode": -1, "msg": "未连接"}
        self._echo += 1
        echo = f"c_{self._echo}"
        payload = {"action": action, "params": kwargs, "echo": echo}
        fut = asyncio.get_event_loop().create_future()
        self._pending[echo] = fut
        try:
            await self.ws.send(json.dumps(payload, ensure_ascii=False))
            return await asyncio.wait_for(fut, timeout=30)
        except asyncio.TimeoutError:
            self._pending.pop(echo, None)
            return {"status": "failed", "retcode": -1, "msg": "API 超时"}
        except Exception as e:
            self._pending.pop(echo, None)
            return {"status": "failed", "retcode": -1, "msg": str(e)}

    async def close(self):
        self._running = False
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass


class OneBotAPI:
    def __init__(self, client: OneBotClient):
        self.client = client

    async def call(self, action: str, **kwargs) -> Dict:
        return await self.client.call_action(action, **kwargs)

    async def send_private_msg(self, user_id: int, message: Any):
        return await self.call("send_private_msg", user_id=user_id, message=message)

    async def send_group_msg(self, group_id: int, message: Any):
        return await self.call("send_group_msg", group_id=group_id, message=message)

    async def send_msg(self, message_type: str = "", user_id: int = 0,
                       group_id: int = 0, message: Any = ""):
        if message_type == "private" or (user_id and not group_id):
            return await self.send_private_msg(user_id, message)
        if message_type == "group" or group_id:
            return await self.send_group_msg(group_id, message)
        return {"status": "failed", "msg": "参数错误"}

    async def delete_msg(self, message_id: int):
        return await self.call("delete_msg", message_id=message_id)

    async def get_msg(self, message_id: int):
        return await self.call("get_msg", message_id=message_id)

    async def get_forward_msg(self, message_id: str):
        return await self.call("get_forward_msg", message_id=message_id)

    async def send_group_forward_msg(self, group_id: int, messages: List[Dict]):
        return await self.call("send_group_forward_msg", group_id=group_id, messages=messages)

    async def send_private_forward_msg(self, user_id: int, messages: List[Dict]):
        return await self.call("send_private_forward_msg", user_id=user_id, messages=messages)

    async def send_like(self, user_id: int, times: int = 1):
        return await self.call("send_like", user_id=user_id, times=times)

    async def get_login_info(self):
        return await self.call("get_login_info")

    async def get_stranger_info(self, user_id: int, no_cache: bool = True):
        return await self.call("get_stranger_info", user_id=user_id, no_cache=no_cache)

    async def get_friend_list(self):
        return await self.call("get_friend_list")

    async def set_friend_add_request(self, flag: str, approve: bool = True, remark: str = ""):
        return await self.call("set_friend_add_request", flag=flag, approve=approve, remark=remark)

    async def delete_friend(self, user_id: int):
        return await self.call("delete_friend", user_id=user_id)

    async def set_group_kick(self, group_id: int, user_id: int, reject_add_request: bool = False):
        return await self.call("set_group_kick", group_id=group_id, user_id=user_id,
                               reject_add_request=reject_add_request)

    async def set_group_ban(self, group_id: int, user_id: int, duration: int = 1800):
        return await self.call("set_group_ban", group_id=group_id, user_id=user_id, duration=duration)

    async def set_group_whole_ban(self, group_id: int, enable: bool = True):
        return await self.call("set_group_whole_ban", group_id=group_id, enable=enable)

    async def set_group_admin(self, group_id: int, user_id: int, enable: bool = True):
        return await self.call("set_group_admin", group_id=group_id, user_id=user_id, enable=enable)

    async def set_group_card(self, group_id: int, user_id: int, card: str = ""):
        return await self.call("set_group_card", group_id=group_id, user_id=user_id, card=card)

    async def set_group_name(self, group_id: int, group_name: str):
        return await self.call("set_group_name", group_id=group_id, group_name=group_name)

    async def set_group_leave(self, group_id: int, is_dismiss: bool = False):
        return await self.call("set_group_leave", group_id=group_id, is_dismiss=is_dismiss)

    async def set_group_special_title(self, group_id: int, user_id: int,
                                      special_title: str = "", duration: int = -1):
        return await self.call("set_group_special_title", group_id=group_id,
                               user_id=user_id, special_title=special_title,
                               duration=duration)

    async def get_group_info(self, group_id: int, no_cache: bool = True):
        return await self.call("get_group_info", group_id=group_id, no_cache=no_cache)

    async def get_group_list(self):
        return await self.call("get_group_list")

    async def get_group_member_info(self, group_id: int, user_id: int, no_cache: bool = True):
        return await self.call("get_group_member_info", group_id=group_id,
                               user_id=user_id, no_cache=no_cache)

    async def get_group_member_list(self, group_id: int, no_cache: bool = True):
        return await self.call("get_group_member_list", group_id=group_id, no_cache=no_cache)

    async def get_group_honor_info(self, group_id: int, type_: str = "all"):
        return await self.call("get_group_honor_info", group_id=group_id, type=type_)

    async def send_group_notice(self, group_id: int, content: str, **kw):
        return await self.call("_send_group_notice", group_id=group_id, content=content, **kw)

    async def get_group_notice(self, group_id: int):
        return await self.call("_get_group_notice", group_id=group_id)

    async def del_group_notice(self, group_id: int, notice_id: str):
        return await self.call("_del_group_notice", group_id=group_id, notice_id=notice_id)

    async def group_poke(self, group_id: int, user_id: int):
        return await self.call("group_poke", group_id=group_id, user_id=user_id)

    async def friend_poke(self, user_id: int):
        return await self.call("friend_poke", user_id=user_id)

    async def upload_group_file(self, group_id: int, file: str, name: str, folder: str = ""):
        kw = {"group_id": group_id, "file": file, "name": name}
        if folder:
            kw["folder"] = folder
        return await self.call("upload_group_file", **kw)

    async def get_group_root_files(self, group_id: int):
        return await self.call("get_group_root_files", group_id=group_id)

    async def get_version_info(self):
        return await self.call("get_version_info")

    async def get_status(self):
        return await self.call("get_status")

    async def clean_cache(self):
        return await self.call("clean_cache")

    async def translate_en2zh(self, words: str):
        return await self.call("translate_en2zh", words=words)

    async def ocr_image(self, image: str):
        return await self.call("ocr_image", image=image)

    async def napcat_api(self, action: str, **kwargs):
        return await self.call(action, **kwargs)
