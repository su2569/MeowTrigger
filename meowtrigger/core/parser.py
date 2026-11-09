"""消息解析器：支持 CQ 码 / 数组 / 纯文本"""
import re
from typing import Any, Dict, List


class MessageParser:
    def __init__(self, mode: str = "auto"):
        self.mode = mode

    def parse(self, raw: Any) -> Dict:
        if raw is None:
            return {"text": "", "segments": [], "at_targets": []}
        if isinstance(raw, str):
            return self._parse_string(raw)
        if isinstance(raw, list):
            return self._parse_list(raw)
        if isinstance(raw, dict):
            return self._parse_dict(raw)
        return {"text": str(raw), "segments": [], "at_targets": []}

    def _parse_string(self, msg: str) -> Dict:
        if "[CQ:" in msg:
            return self._parse_cqcode(msg)
        if re.search(r"\[At:\d+\]", msg):
            return self._parse_at(msg)
        return {"text": msg, "segments": [{"type": "text", "data": {"text": msg}}], "at_targets": []}

    def _parse_cqcode(self, msg: str) -> Dict:
        segs, ats, texts = [], [], []
        last = 0
        for m in re.finditer(r"\[CQ:([^,\]]+)(?:,([^\]]*))?\]", msg):
            if m.start() > last:
                t = msg[last:m.start()]
                if t:
                    segs.append({"type": "text", "data": {"text": t}})
                    texts.append(t)
            ct = m.group(1)
            params = {}
            for p in (m.group(2) or "").split(","):
                if "=" in p:
                    k, v = p.split("=", 1)
                    params[k.strip()] = v.strip()
            if ct == "at" and params.get("qq", "").isdigit():
                ats.append(int(params["qq"]))
            segs.append({"type": ct, "data": params})
            last = m.end()
        if last < len(msg):
            t = msg[last:]
            segs.append({"type": "text", "data": {"text": t}})
            texts.append(t)
        return {"text": "".join(texts), "segments": segs, "at_targets": ats}

    def _parse_at(self, msg: str) -> Dict:
        segs, ats, texts = [], [], []
        last = 0
        for m in re.finditer(r"\[At:(\d+)\]", msg):
            if m.start() > last:
                t = msg[last:m.start()]
                if t:
                    segs.append({"type": "text", "data": {"text": t}})
                    texts.append(t)
            qq = int(m.group(1))
            ats.append(qq)
            segs.append({"type": "at", "data": {"qq": str(qq)}})
            last = m.end()
        if last < len(msg):
            t = msg[last:]
            segs.append({"type": "text", "data": {"text": t}})
            texts.append(t)
        return {"text": "".join(texts), "segments": segs, "at_targets": ats}

    def _parse_list(self, msg: List) -> Dict:
        segs, ats, texts = [], [], []
        for seg in msg:
            if not isinstance(seg, dict):
                continue
            st = seg.get("type", "")
            data = seg.get("data", {})
            if st == "text":
                texts.append(data.get("text", ""))
            elif st == "at" and str(data.get("qq", "")).isdigit():
                ats.append(int(data["qq"]))
            segs.append({"type": st, "data": data})
        return {"text": "".join(texts), "segments": segs, "at_targets": ats}

    def _parse_dict(self, msg: Dict) -> Dict:
        if "message" in msg:
            return self.parse(msg["message"])
        if "type" in msg:
            return self._parse_list([msg])
        return {"text": str(msg), "segments": [], "at_targets": []}
