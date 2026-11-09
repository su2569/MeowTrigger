"""UMO（Unified Message Origin）统一消息来源标识

MeowTrigger 用 UMO 字符串唯一描述「一条消息来自哪里」：

    <platform>:<message_type>:<session_id>

例子：:

    onebot:GroupMessage:123456789      # OneBot 某群
    onebot:PrivateMessage:987654321    # OneBot 某人私聊
    aiocqhttp:FriendMessage:987654321  # AstrBot 好友私聊
    qq_official:GroupMessage:ABCDEF12  # QQ 官方机器人 OpenID

约定：

- ``message_type`` 统一为 ``GroupMessage`` / ``FriendMessage`` /
  ``PrivateMessage`` / ``TempMessage`` / ``GuildMessage`` / ``DirectMessage``
- 群聊类（GroupMessage / GuildMessage）的 session_id 是群号，
  其余是用户号
- 任意一段都可以写 ``*`` 表示通配，用于「该平台下所有群」这类配置

MTPlugins 目录中的插件必须声明 ``umo`` 字段，MeowTrigger 据此决定
「这条触发器只在哪个群 / 哪个用户那里生效」。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

WILDCARD = "*"

GROUP_TYPES = {"groupmessage", "guildmessage", "group"}
USER_TYPES = {"friendmessage", "privatemessage", "tempmessage",
              "directmessage", "private", "friend", "temp", "user"}

_TYPE_CANON = {
    "groupmessage": "GroupMessage", "group": "GroupMessage",
    "guildmessage": "GuildMessage", "guild": "GuildMessage",
    "friendmessage": "FriendMessage", "friend": "FriendMessage",
    "privatemessage": "PrivateMessage", "private": "PrivateMessage",
    "tempmessage": "TempMessage", "temp": "TempMessage",
    "directmessage": "DirectMessage", "direct": "DirectMessage",
    "user": "PrivateMessage",
}

DEFAULT_PLATFORM = "onebot"


class UMOError(ValueError):
    """UMO 格式不合法"""


def normalize_message_type(message_type: str) -> str:
    """把各种写法归一成标准 message_type"""
    key = str(message_type or "").strip().lower().replace("_", "").replace(" ", "")
    if not key:
        return "GroupMessage"
    return _TYPE_CANON.get(key, str(message_type).strip())


def normalize_platform(platform: str) -> str:
    p = str(platform or "").strip().lower().replace(" ", "_")
    return p or DEFAULT_PLATFORM


@dataclass(frozen=True)
class UMO:
    """结构化 UMO"""

    platform: str
    message_type: str
    session_id: str

    # ---------------- 基本属性 ----------------

    @property
    def is_group(self) -> bool:
        key = self.message_type.lower()
        if key in GROUP_TYPES:
            return True
        if key in USER_TYPES:
            return False
        return KEY_GROUP_GUESS.get(key, False)

    @property
    def is_user(self) -> bool:
        return not self.is_group

    @property
    def kind(self) -> str:
        """G = 群配置，U = 用户配置"""
        return "G" if self.is_group else "U"

    @property
    def scope_prefix(self) -> str:
        return self.kind

    @property
    def group_id(self) -> str:
        return self.session_id if self.is_group else ""

    @property
    def user_id(self) -> str:
        return "" if self.is_group else self.session_id

    @property
    def has_wildcard(self) -> bool:
        return WILDCARD in (self.platform, self.message_type, self.session_id)

    # ---------------- 序列化 ----------------

    def __str__(self) -> str:  # pragma: no cover - 简单转发
        return f"{self.platform}:{self.message_type}:{self.session_id}"

    def to_dict(self) -> Dict[str, str]:
        return {
            "umo": str(self),
            "platform": self.platform,
            "message_type": self.message_type,
            "session_id": self.session_id,
            "kind": self.kind,
        }

    def replace(self, **kwargs: Any) -> "UMO":
        data = {
            "platform": self.platform,
            "message_type": self.message_type,
            "session_id": self.session_id,
        }
        data.update({k: v for k, v in kwargs.items() if v is not None})
        return UMO(**data)

    # ---------------- 匹配 ----------------

    def matches(self, other: "UMO | str | None") -> bool:
        """self 作为「配置里的 umo」，other 作为「真实消息的 umo」"""
        if other is None:
            return False
        target = parse_umo(other) if not isinstance(other, UMO) else other
        return (platform_match(self.platform, target.platform)
                and message_type_match(self.message_type, target.message_type)
                and umo_segment_match(self.session_id, target.session_id))


# 兜底猜测定为「非群」，避免误判成群配置
KEY_GROUP_GUESS: Dict[str, bool] = {}


def umo_segment_match(pattern: str, value: str) -> bool:
    p = str(pattern or WILDCARD)
    v = str(value or "")
    if p == WILDCARD or p == "":
        return True
    return p.lower() == v.lower()


# 同一个语义常有好几个写法：OneBot 的 PrivateMessage / AstrBot 的 FriendMessage
# 都是「私聊」，配置里写哪个都该匹配得上，所以按族比较
_MESSAGE_FAMILY = {
    "groupmessage": "group", "group": "group",
    "guildmessage": "guild", "guild": "guild",
    "friendmessage": "private", "privatemessage": "private",
    "private": "private", "friend": "private", "user": "private",
    "tempmessage": "temp", "temp": "temp",
    "directmessage": "direct", "direct": "direct",
}


def message_family(message_type: str) -> str:
    key = str(message_type or "").strip().lower().replace("_", "").replace(" ", "")
    return _MESSAGE_FAMILY.get(key, key)


def message_type_match(pattern: str, value: str) -> bool:
    """message_type 按「族」比较：私聊/群聊/临时会话……写法不同也算同一类"""
    p = str(pattern or WILDCARD)
    if p == WILDCARD or p == "":
        return True
    if umo_segment_match(p, value):
        return True
    return message_family(p) == message_family(value)


# 同一个平台常有好几个名字（OneBot 系尤其明显），配置里写哪个都能匹配上
_PLATFORM_FAMILY = {
    "onebot": "onebot", "aiocqhttp": "onebot", "napcat": "onebot",
    "lagrange": "onebot", "go-cqhttp": "onebot", "gocqhttp": "onebot",
    "cqhttp": "onebot", "onebotv11": "onebot", "v11": "onebot",
    "qq_official": "qq_official", "qqofficial": "qq_official",
    "qqbot": "qq_official", "official": "qq_official", "qq": "qq_official",
    "telegram": "telegram", "discord": "discord", "wechat": "wechat",
}


def platform_family(platform: str) -> str:
    key = str(platform or "").strip().lower().replace("-", "").replace(" ", "")
    return _PLATFORM_FAMILY.get(key, key)


def platform_match(pattern: str, value: str) -> bool:
    """平台匹配：支持 * 通配与同族别名（onebot / aiocqhttp 视为一类）"""
    if umo_segment_match(pattern, value):
        return True
    p = str(pattern or WILDCARD)
    if p == WILDCARD:
        return True
    return platform_family(p) == platform_family(value)


def build_umo(platform: str, message_type: str, session_id: Any) -> str:
    """拼一个标准 UMO 字符串"""
    sid = str(session_id).strip()
    if not sid:
        raise UMOError("session_id 不能为空")
    return f"{normalize_platform(platform)}:{normalize_message_type(message_type)}:{sid}"


def parse_umo(umo: str | UMO | Dict[str, Any]) -> UMO:
    """解析 UMO，容忍 dict / 已解析对象 / 不带平台前缀的简写"""
    if isinstance(umo, UMO):
        return umo
    if isinstance(umo, dict):
        return parse_umo(str(umo.get("umo") or "").strip()
                         or build_umo(umo.get("platform", DEFAULT_PLATFORM),
                                      umo.get("message_type", "GroupMessage"),
                                      umo.get("session_id", "")))
    text = str(umo or "").strip()
    if not text:
        raise UMOError("umo 为空")
    parts = text.split(":")
    if len(parts) == 3 and all(parts[:2]):
        platform, mtype, sid = parts
        return UMO(normalize_platform(platform), normalize_message_type(mtype), sid.strip())
    if len(parts) == 2:
        # 简写：GroupMessage:12345
        mtype, sid = parts
        return UMO(DEFAULT_PLATFORM, normalize_message_type(mtype), sid.strip())
    raise UMOError(f"UMO 格式应为 platform:message_type:session_id，收到: {text!r}")


def try_parse_umo(umo: Any) -> Optional[UMO]:
    try:
        return parse_umo(umo)
    except (UMOError, TypeError, ValueError):
        return None


def is_valid_umo(umo: Any) -> bool:
    return try_parse_umo(umo) is not None


def umo_matches(pattern: Any, target: Any) -> bool:
    """通配匹配：pattern 里可用 *"""
    p = try_parse_umo(pattern)
    t = try_parse_umo(target)
    if p is None or t is None:
        # 解析失败时退化为纯字符串比较，至少不会误命中
        return str(pattern or "") == str(target or "")
    return p.matches(t)


def umo_of(platform: str = DEFAULT_PLATFORM, *, group_id: Any = None,
           user_id: Any = None, message_type: str = "") -> str:
    """按「给群号还是给用户号」自动挑 message_type"""
    gid = str(group_id or "").strip()
    uid = str(user_id or "").strip()
    if gid:
        return build_umo(platform, message_type or "GroupMessage", gid)
    if uid:
        return build_umo(platform, message_type or "PrivateMessage", uid)
    raise UMOError("group_id 与 user_id 至少要给一个")


def scope_prefix_of(umo: Any) -> str:
    """G/U：群配置还是用户配置"""
    parsed = try_parse_umo(umo)
    return parsed.kind if parsed else ""


__all__ = [
    "WILDCARD", "UMO", "UMOError", "DEFAULT_PLATFORM",
    "normalize_message_type", "normalize_platform",
    "build_umo", "parse_umo", "try_parse_umo", "is_valid_umo",
    "umo_matches", "umo_segment_match", "umo_of", "scope_prefix_of",
    "platform_match", "platform_family",
]
