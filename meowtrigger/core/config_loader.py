"""触发器配置加载：扫描 plugins/ 与 plugins/MTPlugins/

两套目录并存，互不干扰：

``plugins/``（旧版，全局触发器）::

    plugins/
    ├── 通用.json              # plugin 文件，对所有会话生效
    └── 123456/                # 纯数字 = 群配置（旧写法）
        └── group_triggers.json

``plugins/MTPlugins/``（新版，群 / 用户配置）::

    plugins/MTPlugins/
    ├── G123456789_夜猫子群/
    │   └── plugin.json        # 必须带 "umo": "onebot:GroupMessage:123456789"
    ├── U10001_小林/
    │   └── plugin.json        # 必须带 "umo": "onebot:PrivateMessage:10001"
    └── 每周播报.json          # 单文件插件，同样必须带 umo

MTPlugins 下 ``umo`` 是硬性字段：缺了就跳过并记一条错误，避免「以为生效了
其实没生效」这种更难查的问题。
"""
import json
import os
from typing import Dict, List, Optional, Tuple

from .. import scope as scope_mod
from ..umo import try_parse_umo, umo_matches
from .logger import logger


class ConfigLoader:
    def __init__(self, base_dir: str, plugins_dir: str,
                 mt_dir: Optional[str] = None, platform: str = "onebot",
                 require_umo: bool = True):
        self.base_dir = base_dir
        self.plugins_dir = plugins_dir
        self.platform = platform or "onebot"
        self.require_umo = require_umo
        self.mt_dir = mt_dir or os.path.join(plugins_dir, "MTPlugins")

        self.global_triggers: List[Dict] = []
        self.group_cache: Dict[str, List[Dict]] = {}
        self.user_cache: Dict[str, List[Dict]] = {}
        self.errors: List[str] = []
        self._counter: Dict[str, int] = {}

    # ---------------- 基础 IO ----------------

    def _read(self, path: str) -> Optional[Dict]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except UnicodeDecodeError:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    return json.loads(f.read())
            except Exception as e:
                logger.error(f"读取失败 {path}: {e}")
                return None
        except json.JSONDecodeError as e:
            logger.error(f"JSON错误 {path}: {e}")
            return None
        except Exception as e:
            logger.error(f"读取失败 {path}: {e}")
            return None

    def _write(self, path: str, data: Dict):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"写入失败 {path}: {e}")

    def _error(self, msg: str):
        self.errors.append(msg)
        logger.error(f"[配置] {msg}")

    # ---------------- 合并 ----------------

    def _resolve(self, name: str, existing: set) -> str:
        if name not in existing:
            return name
        c = self._counter.get(name, 1)
        while True:
            new = f"{name}_{c}"
            if new not in existing:
                self._counter[name] = c + 1
                return new
            c += 1

    def _merge(self, trigger: Dict, source: str, pname: str, pdesc: str,
               is_group: bool, existing: set, dp: str, dc: int,
               umo: str = "", scope=None) -> Dict:
        raw = trigger.get("name", "unnamed")
        rn = self._resolve(raw, existing)
        existing.add(rn)
        merged = {
            "source_file": source, "plugin_name": pname, "_plugin_desc": pdesc,
            "name": rn,
            "trigger_type": trigger.get("trigger_type", "keyword"),
            "trigger_pattern": trigger.get("trigger_pattern", ""),
            "response_type": trigger.get("response_type", "text"),
            "response_content": trigger.get("response_content", ""),
            "permission": trigger.get("permission", dp),
            "cooldown": trigger.get("cooldown", dc),
            "enabled": trigger.get("enabled", True),
            "description": trigger.get("description", ""),
            "authorized_groups": trigger.get("authorized_groups", []),
            "authorize_all": trigger.get("authorize_all", False),
        }
        for k, v in trigger.items():
            if k not in merged:
                merged[k] = v
        if is_group:
            merged["group_only"] = True
        # 触发器自身可以覆盖插件级 umo，用于「一个插件多条不同会话的触发器」
        trigger_umo = str(trigger.get("umo") or umo or "")
        if trigger_umo:
            merged["_umo"] = trigger_umo
        if scope is not None:
            merged["_scope"] = scope.to_dict()
            if scope.is_user:
                merged["_user_id"] = scope.session_id
            if scope.is_group:
                merged["_group_id"] = scope.session_id
        return merged

    # ---------------- 单文件插件 ----------------

    def _load_plugin_file(self, path: str, dp: str, dc: int, existing: set,
                          default_umo: str = "", scope=None,
                          require_umo: bool = False) -> int:
        """读一个 plugin json，把它的触发器塞进对应容器，返回条数"""
        data = self._read(path)
        if not data or not isinstance(data, dict):
            return 0

        fname = os.path.basename(path)
        pname = data.get("plugin_name") or (scope.custom_name if scope
                                            and scope.custom_name else fname[:-5])
        pdesc = data.get("description", "")
        raw_umo = str(data.get("umo") or "").strip()
        plugin_umo = raw_umo or str(default_umo or "").strip()

        if require_umo and not raw_umo:
            where = os.path.basename(os.path.dirname(path))
            hint = (f"（目录 {where} 可推出 {default_umo}，但 plugin.json 里仍要写明）"
                    if default_umo else "")
            self._error(f"{path} 缺少 umo 字段，MTPlugins 下为必填{hint}，已跳过")
            return 0

        if require_umo or plugin_umo:
            if not plugin_umo:
                self._error(f"{path} 缺少 umo 字段（MTPlugins 下为必填），已跳过")
                return 0
            parsed = try_parse_umo(plugin_umo)
            if parsed is None:
                self._error(f"{path} 的 umo 无法解析: {plugin_umo!r}，已跳过")
                return 0
            if scope is not None and not parsed.has_wildcard:
                reason = scope_mod.scope_dirs_mismatch(scope, plugin_umo)
                if reason:
                    self._error(f"{path} {reason}，已跳过")
                    return 0

        count = 0
        for t in data.get("triggers") or []:
            if not isinstance(t, dict):
                continue
            t_umo = str(t.get("umo") or plugin_umo)
            if require_umo and not t_umo:
                self._error(f"{path} 的触发器 {t.get('name')!r} 缺少 umo，已跳过")
                continue
            is_group = bool(scope and scope.is_group)
            if not scope and t_umo:
                parsed = try_parse_umo(t_umo)
                is_group = bool(parsed and parsed.is_group)
            m = self._merge(t, fname, pname, pdesc, is_group, existing, dp, dc,
                            umo=t_umo, scope=scope)
            if pdesc and not m.get("description", ""):
                m["description"] = pdesc
            m["_base_dir"] = os.path.dirname(path)
            m["_source_path"] = path

            target = self.global_triggers
            if t_umo:
                parsed = try_parse_umo(t_umo)
                if parsed is not None and not parsed.has_wildcard:
                    if parsed.is_group:
                        target = self.group_cache.setdefault(parsed.session_id, [])
                    else:
                        target = self.user_cache.setdefault(parsed.session_id, [])
                    if scope is not None:
                        m["_base_dir"] = os.path.dirname(path)
            target.append(m)
            count += 1
        return count

    # ---------------- 总加载 ----------------

    def load_all(self, dp: str = "all", dc: int = 0,
                 umo: Optional[str] = None) -> Tuple[List[Dict], Dict[str, List[Dict]]]:
        self.global_triggers.clear()
        self.group_cache.clear()
        self.user_cache.clear()
        self.errors.clear()
        self._counter.clear()
        existing: set = set()

        # 1) 旧版全局插件：plugins/*.json
        if os.path.isdir(self.plugins_dir):
            for fname in sorted(os.listdir(self.plugins_dir)):
                fpath = os.path.join(self.plugins_dir, fname)
                if os.path.isfile(fpath) and fname.endswith(".json"):
                    self._load_plugin_file(fpath, dp, dc, existing)

        # 2) 旧版群目录：plugins/<群号>/
        if os.path.isdir(self.plugins_dir):
            for entry in sorted(os.listdir(self.plugins_dir)):
                coll_dir = os.path.join(self.plugins_dir, entry)
                if not os.path.isdir(coll_dir):
                    continue
                scope = scope_mod.parse_scope(entry)
                if scope is None:
                    continue  # MTPlugins 之类的普通目录交给下一步
                is_group = scope.is_group
                for fname in sorted(os.listdir(coll_dir)):
                    if not fname.endswith(".json"):
                        continue
                    fpath = os.path.join(coll_dir, fname)
                    if not os.path.isfile(fpath):
                        continue
                    self._load_plugin_file(
                        fpath, dp, dc, existing,
                        default_umo=scope.umo(self.platform),
                        scope=scope, require_umo=False)

        # 3) 新版 MTPlugins：单文件 + G/U 目录
        self._load_mt_plugins(dp, dc, existing)

        # 4) 按当前会话过滤（可选）
        if umo:
            self.global_triggers = [t for t in self.global_triggers
                                    if self._trigger_hits(t, umo)]
            for key in list(self.group_cache):
                self.group_cache[key] = [t for t in self.group_cache[key]
                                         if self._trigger_hits(t, umo)]
            for key in list(self.user_cache):
                self.user_cache[key] = [t for t in self.user_cache[key]
                                        if self._trigger_hits(t, umo)]

        logger.info(
            f"加载完成: {len(self.global_triggers)} 全局触发器, "
            f"{len(self.group_cache)} 群配置, {len(self.user_cache)} 用户配置"
            + (f", {len(self.errors)} 条错误" if self.errors else ""))
        return self.global_triggers, self.group_cache

    def _load_mt_plugins(self, dp: str, dc: int, existing: set) -> int:
        mt = self.mt_dir
        total = 0
        if not os.path.isdir(mt):
            return 0

        # 3.1) MTPlugins/*.json 单文件插件
        for fname in sorted(os.listdir(mt)):
            fpath = os.path.join(mt, fname)
            if os.path.isfile(fpath) and fname.endswith(".json"):
                total += self._load_plugin_file(
                    fpath, dp, dc, existing, require_umo=self.require_umo)

        # 3.2) MTPlugins/G...|U.../plugin.json
        for path, scope in scope_mod.iter_scope_dirs(mt):
            files = [f for f in sorted(os.listdir(path)) if f.endswith(".json")]
            if not files:
                continue
            for fname in files:
                total += self._load_plugin_file(
                    os.path.join(path, fname), dp, dc, existing,
                    default_umo=scope.umo(self.platform), scope=scope,
                    require_umo=self.require_umo)
        if total:
            logger.info(f"MTPlugins 载入 {total} 条会话级触发器")
        return total

    # ---------------- 查询 ----------------

    @staticmethod
    def _trigger_hits(trigger: Dict, umo: str) -> bool:
        t_umo = trigger.get("_umo")
        if not t_umo:
            return True
        return umo_matches(t_umo, umo)

    def trigger_hits(self, trigger: Dict, umo: str) -> bool:
        """公开版本：触发器是否命中当前会话"""
        return self._trigger_hits(trigger, umo)

    def get_scoped(self, group_id: str = "", user_id: str = "",
                   umo: str = "") -> List[Dict]:
        """取某个会话的群配置 + 用户配置"""
        out: List[Dict] = []
        if group_id:
            out.extend(self.group_cache.get(str(group_id), []))
        if user_id:
            out.extend(self.user_cache.get(str(user_id), []))
        if umo:
            out = [t for t in out if self._trigger_hits(t, umo)]
        return out

    def for_context(self, ctx) -> List[Dict]:
        """按 MessageContext 组装可用触发器（全局 + 会话级）"""
        umo = getattr(ctx, "umo", "") or ""
        gid = str(getattr(ctx, "group_id", "") or "")
        uid = str(getattr(ctx, "user_id", "") or "")
        scoped = self.get_scoped(gid, uid, umo)
        glob = [t for t in self.global_triggers if self._trigger_hits(t, umo)]
        return scoped + glob

    def list_scopes(self) -> List[List[str]]:
        return scope_mod.list_scope_dirs(self.mt_dir)

    # ---------------- 群 / 用户配置读写 ----------------

    def _scope_dir_for(self, kind: str, session_id: str,
                       custom_name: str = "", create: bool = False) -> Optional[str]:
        found = scope_mod.find_scope_dir(self.mt_dir, kind, session_id)
        if found:
            return found
        if create:
            return scope_mod.ensure_scope_dir(self.mt_dir, kind, session_id, custom_name)
        # 旧版位置兜底
        legacy = os.path.join(self.plugins_dir, str(session_id))
        return legacy if os.path.isdir(legacy) else None

    def load_group(self, group_id: str, dp: str, dc: int) -> List[Dict]:
        if not group_id:
            return []
        gid = str(group_id)
        if gid in self.group_cache:
            return self.group_cache[gid]
        result: List[Dict] = []
        gdir = self._scope_dir_for(scope_mod.GROUP, gid)
        if gdir:
            existing: set = set()
            scope = scope_mod.parse_scope(os.path.basename(gdir))
            for fname in sorted(os.listdir(gdir)):
                if not fname.endswith(".json"):
                    continue
                path = os.path.join(gdir, fname)
                if not os.path.isfile(path):
                    continue
                self._load_plugin_file(
                    path, dp, dc, existing,
                    default_umo=scope.umo(self.platform) if scope else "",
                    scope=scope, require_umo=self.require_umo)
            result = [t for t in self.group_cache.get(gid, [])]
            self.group_cache[gid] = result
        return result

    def save_group(self, group_id: str, triggers: List[Dict],
                   custom_name: str = ""):
        self._save_scoped(scope_mod.GROUP, group_id, triggers, custom_name)

    def load_user(self, user_id: str, dp: str = "all", dc: int = 0) -> List[Dict]:
        uid = str(user_id or "")
        if not uid:
            return []
        if uid in self.user_cache:
            return self.user_cache[uid]
        udir = self._scope_dir_for(scope_mod.USER, uid)
        if udir:
            existing: set = set()
            scope = scope_mod.parse_scope(os.path.basename(udir))
            for fname in sorted(os.listdir(udir)):
                path = os.path.join(udir, fname)
                if not os.path.isfile(path) or not fname.endswith(".json"):
                    continue
                self._load_plugin_file(
                    path, dp, dc, existing,
                    default_umo=scope.umo(self.platform) if scope else "",
                    scope=scope, require_umo=self.require_umo)
        return self.user_cache.setdefault(uid, [])

    def save_user(self, user_id: str, triggers: List[Dict],
                  custom_name: str = ""):
        self._save_scoped(scope_mod.USER, user_id, triggers, custom_name)

    def _save_scoped(self, kind: str, session_id: str, triggers: List[Dict],
                     custom_name: str = ""):
        target_dir = self._scope_dir_for(kind, str(session_id), custom_name, create=True)
        if not target_dir:
            self._error(f"无法定位 {kind}{session_id} 的配置目录")
            return
        scope = scope_mod.parse_scope(os.path.basename(target_dir))
        umo = scope.umo(self.platform) if scope else ""
        name = "group_triggers.json" if scope_mod.normalize_kind(kind) == scope_mod.GROUP \
            else "user_triggers.json"
        clean = []
        for t in triggers:
            item = {k: v for k, v in t.items() if not k.startswith("_")}
            if umo and not item.get("umo"):
                item["umo"] = umo
            clean.append(item)
        self._write(os.path.join(target_dir, name), {
            "plugin_name": (scope.dir_name if scope else f"{kind}{session_id}"),
            "author": "scope_admin",
            "version": "1.0.0",
            "umo": umo,
            "description": f"{'群' if scope_mod.normalize_kind(kind) == scope_mod.GROUP else '用户'} "
                           f"{session_id} 专属触发器",
            "triggers": clean,
        })
        cache = self.group_cache if scope_mod.normalize_kind(kind) == scope_mod.GROUP \
            else self.user_cache
        cache[str(session_id)] = triggers
