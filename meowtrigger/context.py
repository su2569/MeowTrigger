"""统一的「一条消息」表示

MeowTrigger 原本只吃 OneBot V11 的原始事件字典。要作为包塞进 ElyBot
这类框架时，再强求 OneBot 结构就太别扭了，于是这里定义一个最小上下文：

- 内部字段足够描述「谁 / 在哪 / 说了什么 / 是什么身份」
- 同时**模仿** OneBotEvent 的接口（``get_group_id`` / ``message_obj.sender`` 等），
  这样 ``EventHandler``、``CommandHandler``、``EmergencyController``
  一行都不用改就能继续工作
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .umo import DEFAULT_PLATFORM, UMOError, normalize_platform, try_parse_umo, umo_of

GROUP_ROLES = {"owner", "admin", "administrator"}


class _CtxSender:
    """模仿 OneBot 的 sender 结构"""

    def __init__(self, user_id: str = "", nickname: str = "", card: str = "",
                 role: str = "member", title: str = ""):
        self.user_id = str(user_id or "")
        self.nickname = nickname or ""
        self.card = card or ""
        self.role = role or "member"
        self.title = title or ""


class _CtxMessageObj:
    """模仿 OneBot 的 message_obj 结构"""

    def __init__(self, message_id: str = "", group_id: str = "", user_id: str = "",
                 message_type: str = "private", sender: Optional[_CtxSender] = None,
                 self_id: str = ""):
        self.message_id = str(message_id or "")
        self.message = ""
        self.raw_message = ""
        self.group_id = str(group_id or "")
        self.message_type = message_type
        self.sender = sender or _CtxSender(user_id)
        self.self_id = str(self_id or "")


@dataclass
class MessageContext:
    """框架无关的消息上下文"""

    text: str = ""
    umo: str = ""
    user_id: str = ""
    user_name: str = ""
    group_id: str = ""
    message_id: str = ""
    role: str = "member"
    platform: str = DEFAULT_PLATFORM
    message_type: str = ""
    is_admin: bool = False
    raw: Any = None
    extra: Dict[str, Any] = field(default_factory=dict)

    # ---------------- 构造 ----------------

    def __post_init__(self) -> None:
        self.text = str(self.text or "")
        self.user_id = str(self.user_id or "")
        self.group_id = str(self.group_id or "")
        self.user_name = str(self.user_name or self.user_id)
        self.platform = normalize_platform(self.platform)
        self.message_type = (
            self.message_type
            or ("GroupMessage" if self.group_id else "PrivateMessage")
        )
        if not self.umo:
            try:
                self.umo = umo_of(self.platform, group_id=self.group_id or None,
                                  user_id=self.user_id or None,
                                  message_type=self.message_type)
            except UMOError:
                self.umo = ""
        else:
            parsed = try_parse_umo(self.umo)
            if parsed is not None:
                self.platform = parsed.platform
                self.message_type = parsed.message_type
                if parsed.is_group and not self.group_id:
                    self.group_id = parsed.session_id
                if parsed.is_user and not self.user_id:
                    self.user_id = parsed.session_id
        self._message_obj = _CtxMessageObj(
            message_id=self.message_id, group_id=self.group_id,
            user_id=self.user_id, message_type=self.message_type,
            sender=_CtxSender(self.user_id, self.user_name,
                              self.user_name, self.role))

    # ---------------- OneBotEvent 兼容接口 ----------------

    @property
    def message_obj(self) -> _CtxMessageObj:
        return self._message_obj

    @property
    def message_str(self) -> str:
        return self.text

    @property
    def self_id(self) -> str:
        return str(self.extra.get("self_id", ""))

    @property
    def post_type(self) -> str:
        return "message"

    def get_group_id(self) -> str:
        return self.group_id

    def get_sender_id(self) -> str:
        return self.user_id

    def get_sender_name(self) -> str:
        return self.user_name or self.user_id

    def get_self_id(self) -> str:
        return self.self_id

    def is_private_chat(self) -> bool:
        return not self.group_id

    def is_group_admin(self) -> bool:
        return self.is_admin or str(self.role or "").lower() in GROUP_ROLES

    # ---------------- 转换 ----------------

    @classmethod
    def from_onebot(cls, raw: Dict[str, Any], platform: str = DEFAULT_PLATFORM,
                    text: str = "") -> "MessageContext":
        """把 OneBot V11 原始事件包成 MessageContext"""
        group_id = str(raw.get("group_id") or "")
        sender = raw.get("sender") or {}
        message_type = raw.get("message_type") or ""
        content = text
        if not content:
            content = raw.get("raw_message") or ""
            if not content:
                message = raw.get("message")
                if isinstance(message, list):
                    content = "".join(
                        seg.get("data", {}).get("text", "")
                        for seg in message
                        if isinstance(seg, dict) and seg.get("type") == "text")
                elif isinstance(message, str):
                    content = message
        return cls(
            text=content or "",
            user_id=str(raw.get("user_id") or ""),
            user_name=str(sender.get("card") or sender.get("nickname")
                          or raw.get("user_id") or ""),
            group_id=group_id,
            message_id=str(raw.get("message_id") or ""),
            role=str(sender.get("role") or "member"),
            platform=platform,
            message_type=("GroupMessage" if message_type in ("group", "guild")
                          else "PrivateMessage" if message_type else ""),
            raw=raw,
            extra={"self_id": raw.get("self_id", "")},
        )

    @classmethod
    def from_any(cls, obj: Any, platform: str = DEFAULT_PLATFORM) -> "MessageContext":
        """尽力从任意框架的消息对象里抠出需要的信息"""
        if isinstance(obj, MessageContext):
            return obj
        if isinstance(obj, dict):
            return cls.from_onebot(obj, platform)

        text = (getattr(obj, "content", None)
                or getattr(obj, "text", None)
                or getattr(obj, "message_str", None) or "")
        group_id = getattr(obj, "group_id", None) or getattr(obj, "gid", None) or ""
        user_id = (getattr(obj, "user_id", None) or getattr(obj, "uid", None) or "")
        sender = getattr(obj, "sender_name", None)
        if not sender:
            msg_obj = getattr(obj, "message_obj", None)
            s = getattr(msg_obj, "sender", None) if msg_obj else None
            sender = getattr(s, "card", "") or getattr(s, "nickname", "") if s else ""
        role = "member"
        msg_obj = getattr(obj, "message_obj", None)
        s = getattr(msg_obj, "sender", None) if msg_obj else None
        if s is not None:
            role = getattr(s, "role", "member") or "member"
        umo = getattr(obj, "umo", "") or ""
        return cls(text=str(text), umo=str(umo), user_id=str(user_id),
                   user_name=str(sender or user_id), group_id=str(group_id),
                   message_id=str(getattr(obj, "message_id", "") or ""),
                   role=str(role), platform=platform, raw=obj)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text, "umo": self.umo, "user_id": self.user_id,
            "user_name": self.user_name, "group_id": self.group_id,
            "message_id": self.message_id, "role": self.role,
            "platform": self.platform, "message_type": self.message_type,
        }


__all__ = ["MessageContext", "GROUP_ROLES"]
