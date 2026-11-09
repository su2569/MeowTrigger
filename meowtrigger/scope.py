"""MTPlugins 目录命名规范

群里一堆 ``123456`` 这样的纯数字目录，久了谁也认不出是谁。
所以 MTPlugins 下的群配置 / 用户配置统一加前缀：

====================  ==========================  ==========================
目录名                含义                        说明
====================  ==========================  ==========================
``G123456789``        群 123456789 的配置          最简形式
``G123456789_夜猫子`` 群 123456789 的配置          ``_`` 后面是自定义名称
``U10001_小林``       用户 10001 的配置             ``_`` 后面是自定义名称
``123456789``         群 123456789（旧版兼容）      没有前缀时按群处理
====================  ==========================  ==========================

自定义名称只影响可读性，不参与匹配；真正的身份是 ``G/U`` + 数字 ID。
目录里放 ``plugin.json``，其中 ``umo`` 字段必须与目录前缀一致：

- ``G123456789_夜猫子/plugin.json`` → ``"umo": "onebot:GroupMessage:123456789"``
- ``U10001_小林/plugin.json``       → ``"umo": "onebot:PrivateMessage:10001"``
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

from .umo import DEFAULT_PLATFORM, UMOError, build_umo, normalize_platform

GROUP = "G"
USER = "U"

_SCOPE_RE = re.compile(
    r"^(?P<prefix>[GU])(?:[-_])?(?P<sid>[0-9A-Za-z]+)(?:[-_\s]+(?P<name>.*))?$",
    re.IGNORECASE,
)
_LEGACY_GROUP_RE = re.compile(r"^\d+$")
_WORD_PREFIX_RE = re.compile(r"^(group|user|group_|user_)[-_]?(?P<sid>[0-9A-Za-z]+)$",
                             re.IGNORECASE)


@dataclass(frozen=True)
class Scope:
    """一个 MTPlugins 子目录代表的会话范围"""

    kind: str            # 'G' 群 / 'U' 用户
    session_id: str
    custom_name: str = ""
    raw: str = ""

    @property
    def is_group(self) -> bool:
        return self.kind == GROUP

    @property
    def is_user(self) -> bool:
        return self.kind == USER

    @property
    def prefix(self) -> str:
        return self.kind

    @property
    def display_name(self) -> str:
        """人类可读：夜猫子(G123456789)"""
        core = f"{self.kind}{self.session_id}"
        return f"{self.custom_name}({core})" if self.custom_name else core

    @property
    def dir_name(self) -> str:
        return build_scope_name(self.kind, self.session_id, self.custom_name)

    def umo(self, platform: str = DEFAULT_PLATFORM) -> str:
        mtype = "GroupMessage" if self.is_group else "PrivateMessage"
        return build_umo(platform, mtype, self.session_id)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "session_id": self.session_id,
            "custom_name": self.custom_name,
            "dir_name": self.dir_name,
            "umo": self.umo(),
        }


def normalize_kind(kind: str) -> str:
    """G / U / group / user / g / u → 'G' / 'U'；无法识别返回空串"""
    k = str(kind or "").strip().upper()
    if k in ("G", "GROUP", "群", "群聊"):
        return GROUP
    if k in ("U", "USER", "私聊", "用户", "FRIEND"):
        return USER
    return ""


def build_scope_name(kind: str, session_id: str, custom_name: str = "") -> str:
    """拼目录名：G123456789_自定义名称"""
    k = normalize_kind(kind)
    if not k:
        raise ValueError(f"未知的 scope 类型: {kind!r}")
    sid = str(session_id or "").strip()
    if not sid:
        raise ValueError("session_id 不能为空")
    name = str(custom_name or "").strip()
    if name:
        name = re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("_")
        return f"{k}{sid}_{name}" if name else f"{k}{sid}"
    return f"{k}{sid}"


def parse_scope(name: str) -> Optional[Scope]:
    """解析目录名；不认识的返回 None"""
    text = str(name or "").strip()
    if not text:
        return None

    m = _SCOPE_RE.match(text)
    if m:
        return Scope(
            kind=m.group("prefix").upper(),
            session_id=m.group("sid"),
            custom_name=(m.group("name") or "").strip(),
            raw=text,
        )

    m = _WORD_PREFIX_RE.match(text)
    if m:
        kind = GROUP if text.lower().startswith("group") else USER
        return Scope(kind=kind, session_id=m.group("sid"), custom_name="", raw=text)

    if _LEGACY_GROUP_RE.match(text):
        # 旧版纯数字目录 = 群配置
        return Scope(kind=GROUP, session_id=text, custom_name="", raw=text)
    return None


def iter_scope_dirs(root: str) -> Iterator[Tuple[str, Scope]]:
    """遍历 root 下所有合法的 G/U 目录"""
    if not os.path.isdir(root):
        return
    for entry in sorted(os.listdir(root)):
        path = os.path.join(root, entry)
        if not os.path.isdir(path):
            continue
        scope = parse_scope(entry)
        if scope is not None:
            yield path, scope


def find_scope_dir(root: str, kind: str, session_id: str) -> Optional[str]:
    """找一个已存在的 scope 目录（忽略自定义名称部分）"""
    k = normalize_kind(kind)
    sid = str(session_id or "").strip()
    if not k or not sid:
        return None
    for path, scope in iter_scope_dirs(root):
        if scope.kind == k and scope.session_id == sid:
            return path
    return None


def ensure_scope_dir(root: str, kind: str, session_id: str,
                     custom_name: str = "") -> str:
    """确保 scope 目录存在并返回路径；已存在则复用（保留原自定义名）"""
    existing = find_scope_dir(root, kind, session_id)
    if existing:
        return existing
    path = os.path.join(root, build_scope_name(kind, session_id, custom_name))
    os.makedirs(path, exist_ok=True)
    return path


def scope_from_umo(umo, platform: str = DEFAULT_PLATFORM) -> Optional[Scope]:
    """从 UMO 反推 scope（用于「按会话建目录」）"""
    from .umo import try_parse_umo

    parsed = try_parse_umo(umo)
    if parsed is None or parsed.has_wildcard:
        return None
    return Scope(kind=parsed.kind, session_id=parsed.session_id,
                 custom_name="", raw=str(parsed))


def scope_dirs_mismatch(scope: Scope, umo: str) -> Optional[str]:
    """校验目录前缀与 umo 是否一致；一致返回 None，否则返回原因"""
    from .umo import try_parse_umo

    parsed = try_parse_umo(umo)
    if parsed is None:
        return f"umo 无法解析: {umo!r}"
    if parsed.has_wildcard:
        return None
    if parsed.session_id != scope.session_id:
        return (f"目录 {scope.raw} 的会话号 {scope.session_id} "
                f"与 umo 的 {parsed.session_id} 不一致")
    if parsed.kind != scope.kind:
        return (f"目录前缀 {scope.kind} 与 umo 类型 {parsed.message_type} 不匹配")
    return None


def list_scope_dirs(root: str) -> List[List[str]]:
    """给命令 / 日志用的轻量清单：[[目录名, 类型, 会话号, 自定义名], ...]"""
    out: List[List[str]] = []
    for _, scope in iter_scope_dirs(root):
        out.append([scope.dir_name, scope.kind, scope.session_id, scope.custom_name])
    return out


__all__ = [
    "GROUP", "USER", "Scope", "normalize_kind", "build_scope_name", "parse_scope",
    "iter_scope_dirs", "find_scope_dir", "ensure_scope_dir", "scope_from_umo",
    "scope_dirs_mismatch", "list_scope_dirs", "UMOError", "normalize_platform",
]
