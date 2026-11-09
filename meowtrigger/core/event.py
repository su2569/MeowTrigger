"""OneBot 事件包装"""
from typing import Dict


class Sender:
    def __init__(self, d: Dict):
        self.user_id = str(d.get("user_id", ""))
        self.nickname = d.get("nickname", "") or d.get("card", "")
        self.card = d.get("card", "")
        self.role = d.get("role", "member")
        self.title = d.get("title", "")


class MessageObj:
    def __init__(self, d: Dict):
        self.message_id = str(d.get("message_id", ""))
        self.message = d.get("message", "")
        self.raw_message = d.get("raw_message", "")
        self.group_id = str(d.get("group_id", "")) if d.get("group_id") else ""
        self.message_type = d.get("message_type", "private")
        self.sender = Sender(d.get("sender", {}))
        self.self_id = str(d.get("self_id", ""))


class OneBotEvent:
    def __init__(self, d: Dict):
        self._data = d
        self.post_type = d.get("post_type", "")
        self.message_type = d.get("message_type", "")
        self.self_id = str(d.get("self_id", ""))
        self.user_id = str(d.get("user_id", ""))
        self.group_id = str(d.get("group_id", "")) if d.get("group_id") else ""
        self.message_obj = MessageObj(d)
        self.message_str = d.get("raw_message", "") or ""
        if not self.message_str:
            m = d.get("message", "")
            if isinstance(m, list):
                self.message_str = "".join(
                    seg.get("data", {}).get("text", "")
                    for seg in m if isinstance(seg, dict) and seg.get("type") == "text")
            elif isinstance(m, str):
                self.message_str = m

    def get_group_id(self) -> str: return self.group_id
    def get_sender_id(self) -> str: return self.user_id
    def get_sender_name(self) -> str:
        s = self.message_obj.sender
        return s.card or s.nickname or self.user_id
    def get_self_id(self) -> str: return self.self_id
    def is_private_chat(self) -> bool: return self.message_type == "private"
