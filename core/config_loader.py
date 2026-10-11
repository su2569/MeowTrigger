"""触发器配置加载：扫描 plugins/ 目录"""
import json
import os
from typing import Dict, List, Optional, Tuple

from .logger import logger


class ConfigLoader:
    def __init__(self, base_dir: str, plugins_dir: str):
        self.base_dir = base_dir
        self.plugins_dir = plugins_dir
        self._counter: Dict[str, int] = {}

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
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"写入失败 {path}: {e}")

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
               is_group: bool, existing: set, dp: str, dc: int) -> Dict:
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
        return merged

    def load_all(self, dp: str = "all", dc: int = 0) -> Tuple[List[Dict], Dict[str, List[Dict]]]:
        all_triggers = []
        group_cache = {}
        self._counter.clear()
        existing: set = set()

        if not os.path.isdir(self.plugins_dir):
            return all_triggers, group_cache

        for fname in os.listdir(self.plugins_dir):
            fpath = os.path.join(self.plugins_dir, fname)
            if not (os.path.isfile(fpath) and fname.endswith(".json")):
                continue
            data = self._read(fpath)
            if not data or not isinstance(data, dict):
                continue
            pname = data.get("plugin_name", fname[:-5])
            pdesc = data.get("description", "")
            for t in data.get("triggers", []):
                if isinstance(t, dict):
                    m = self._merge(t, fname, pname, pdesc, False, existing, dp, dc)
                    if pdesc and not m.get("description", ""):
                        m["description"] = pdesc
                    all_triggers.append(m)

        for entry in os.listdir(self.plugins_dir):
            coll_dir = os.path.join(self.plugins_dir, entry)
            if not os.path.isdir(coll_dir):
                continue
            is_group = entry.isdigit()
            for fname in os.listdir(coll_dir):
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(coll_dir, fname)
                if not os.path.isfile(fpath):
                    continue
                data = self._read(fpath)
                if not data or not isinstance(data, dict):
                    continue
                pname = data.get("plugin_name", entry)
                pdesc = data.get("description", "")
                for t in data.get("triggers", []):
                    if isinstance(t, dict):
                        m = self._merge(t, fname, pname, pdesc, is_group, existing, dp, dc)
                        if pdesc and not m.get("description", ""):
                            m["description"] = pdesc
                        m["_base_dir"] = coll_dir
                        if is_group:
                            m["_group_id"] = entry
                            group_cache.setdefault(entry, []).append(m)
                        else:
                            all_triggers.append(m)

        logger.info(f"加载完成: {len(all_triggers)} 全局触发器, {len(group_cache)} 群配置")
        return all_triggers, group_cache

    def load_group(self, group_id: str, dp: str, dc: int) -> List[Dict]:
        if not group_id:
            return []
        gdir = os.path.join(self.plugins_dir, group_id)
        gpath = os.path.join(gdir, "group_triggers.json")
        if not os.path.exists(gpath):
            return []
        data = self._read(gpath)
        if not data:
            return []
        existing: set = set()
        result = []
        for t in data.get("triggers", []):
            if isinstance(t, dict):
                m = self._merge(t, "group_triggers.json", f"group_{group_id}", "",
                                True, existing, dp, dc)
                m["_group_id"] = group_id
                m["_base_dir"] = gdir
                result.append(m)
        return result

    def save_group(self, group_id: str, triggers: List[Dict]):
        gdir = os.path.join(self.plugins_dir, group_id)
        os.makedirs(gdir, exist_ok=True)
        path = os.path.join(gdir, "group_triggers.json")
        clean = [{k: v for k, v in t.items() if not k.startswith("_")} for t in triggers]
        self._write(path, {
            "plugin_name": f"group_{group_id}",
            "author": "group_admin",
            "version": "1.0.0",
            "description": f"Group triggers for {group_id}",
            "triggers": clean,
        })
