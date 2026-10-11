"""
stdin.py - 模拟 snowluma OneBot V11 服务器（stdin 驱动测试）

用途：不用真实的 QQ 后端，就能测试 MeowTrigger 的触发和响应。

工作方式：
  1. 监听 ws://127.0.0.1:3001（MeowTrigger 默认配置就是这个地址）
  2. MeowTrigger 作为客户端连进来
  3. 你在终端输入命令，本脚本把它们包装成 OneBot V11 事件推送给 MeowTrigger
  4. MeowTrigger 调用 send_group_msg / send_private_msg 等 API 时，本脚本
     会把调用内容打印到终端，并回一个成功响应

命令：
  group <群号> <用户ID> <消息>    发送群消息事件
  private <用户ID> <消息>          发送私聊消息事件
  raw <json>                       直接发送原始事件 JSON
  help / h / ?                     显示帮助
  quit / exit / q                  退出

示例：
  group 123456 10001 你好
  group 123456 10001 /签到
  private 10001 你好
  raw {"post_type":"message","message_type":"group","group_id":123456,"user_id":10001,"raw_message":"你好","self_id":10000,"sender":{"user_id":10001,"nickname":"测试"},"message_id":1}

依赖：pip install websockets
"""
import asyncio
import json
import sys
import threading
import time
from typing import Optional

try:
    import websockets
except ImportError:
    print("[stdin] 缺少依赖，请先运行: pip install websockets")
    sys.exit(1)


HOST = "127.0.0.1"
PORT = 3001
SELF_ID = 10000                     # 假机器人 QQ
DEFAULT_USER_ID = 10001             # 默认测试用户 QQ
DEFAULT_GROUP_ID = 123456           # 默认测试群号
DEFAULT_NICK = "测试用户"

_connections = set()                # 已连接的 MeowTrigger ws
_input_queue: Optional[asyncio.Queue] = None


# ------------------------------------------------------------
# 1. 构造事件
# ------------------------------------------------------------
def make_event(**kw) -> dict:
    """构造一条最小化的 OneBot V11 message 事件"""
    e = {
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "message_id": int(time.time() * 1000) % 1000000000,
        "user_id": DEFAULT_USER_ID,
        "group_id": DEFAULT_GROUP_ID,
        "self_id": SELF_ID,
        "raw_message": "",
        "font": 0,
        "time": int(time.time()),
        "sender": {
            "user_id": DEFAULT_USER_ID,
            "nickname": DEFAULT_NICK,
            "card": "",
            "role": "member",
        },
    }
    # 先应用用户的键（除了 message / sender 这些要特殊处理的）
    msg_text = kw.pop("message", None)
    sender_override = kw.pop("sender", None)
    e.update(kw)
    # 同步 sender.user_id 与顶层 user_id
    if "user_id" in kw:
        e["sender"]["user_id"] = kw["user_id"]
    # 私聊没有 group_id
    if e.get("message_type") == "private":
        e.pop("group_id", None)
    # 处理 message
    if msg_text is not None:
        e["raw_message"] = msg_text
        e["message"] = [{"type": "text", "data": {"text": msg_text}}]
    # 合并用户给的 sender
    if sender_override:
        e["sender"].update(sender_override)
    return e


# ------------------------------------------------------------
# 2. WebSocket 服务端
# ------------------------------------------------------------
async def ws_handler(ws):
    """处理 MeowTrigger 的连接"""
    _connections.add(ws)
    remote = getattr(ws, "remote_address", ("?", 0))
    print(f"\n[连接] MeowTrigger 已连接 {remote}")
    print("[连接] 等待输入命令...\n")

    try:
        async for raw in ws:
            try:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                data = json.loads(raw)
            except Exception as e:
                print(f"[API ] 无法解析消息: {e}")
                continue

            action = data.get("action", "")
            params = data.get("params", {}) or {}
            echo = data.get("echo")

            # 打印 MeowTrigger 发过来的 API 调用
            if action in ("send_group_msg", "send_private_msg", "send_msg"):
                target = params.get("group_id") or params.get("user_id") or "?"
                msg = params.get("message", "")
                kind = "群" if "group" in action else "私"
                print(f"\n>>> [{kind}消息 -> {target}] {msg}\n")
            else:
                # 其它 API 只打印一行
                print(f"\n>>> [API] {action}({json.dumps(params, ensure_ascii=False)[:120]})")

            # 回响应
            if echo is not None:
                resp = {"status": "ok", "retcode": 0, "data": None, "echo": echo}
                if action == "get_login_info":
                    resp["data"] = {"user_id": SELF_ID, "nickname": "TestBot"}
                elif action == "get_group_list":
                    resp["data"] = [{"group_id": DEFAULT_GROUP_ID,
                                     "group_name": "测试群"}]
                elif action == "get_group_member_info":
                    resp["data"] = {
                        "user_id": params.get("user_id"),
                        "nickname": DEFAULT_NICK,
                        "role": "member",
                    }
                try:
                    await ws.send(json.dumps(resp, ensure_ascii=False))
                except Exception as e:
                    print(f"[API ] 发送响应失败: {e}")
    except websockets.ConnectionClosed:
        pass
    except Exception as e:
        print(f"[连接] 异常: {e}")
    finally:
        _connections.discard(ws)
        print("[连接] MeowTrigger 已断开")


async def broadcast(event: dict):
    """把一个事件广播给所有已连接的 MeowTrigger"""
    if not _connections:
        print("[发送] 没有客户端连接，请先启动 MeowTrigger")
        return
    payload = json.dumps(event, ensure_ascii=False)
    dead = []
    for ws in list(_connections):
        try:
            await ws.send(payload)
        except Exception as e:
            print(f"[发送] 失败: {e}")
            dead.append(ws)
    for ws in dead:
        _connections.discard(ws)


# ------------------------------------------------------------
# 3. 命令分发
# ------------------------------------------------------------
def print_help():
    print("""
命令列表
  group <群号> <用户ID> <消息>    发送群消息事件
  private <用户ID> <消息>          发送私聊消息事件
  raw <json>                       直接发送原始事件 JSON
  help / h / ?                     显示帮助
  quit / exit / q                  退出

示例
  group 123456 10001 你好
  group 123456 10001 /签到
  private 10001 你好
""")


async def dispatch(line: str) -> bool:
    """处理一行输入。返回 False 表示要求退出"""
    parts = line.split(None, 3)
    cmd = parts[0].lower()

    if cmd in ("quit", "exit", "q"):
        print("[stdin] 正在退出...")
        return False

    if cmd in ("help", "h", "?"):
        print_help()
        return True

    if cmd == "group":
        if len(parts) < 4:
            print("[stdin] 用法: group <群号> <用户ID> <消息>")
            return True
        try:
            gid = int(parts[1])
            uid = int(parts[2])
        except ValueError:
            print("[stdin] 群号或用户ID 必须是数字")
            return True
        event = make_event(
            message_type="group",
            group_id=gid,
            user_id=uid,
            message=parts[3],
        )
        await broadcast(event)
        return True

    if cmd == "private":
        if len(parts) < 3:
            print("[stdin] 用法: private <用户ID> <消息>")
            return True
        try:
            uid = int(parts[1])
        except ValueError:
            print("[stdin] 用户ID 必须是数字")
            return True
        event = make_event(
            message_type="private",
            user_id=uid,
            message=parts[2] if len(parts) == 3 else parts[2] + " " + parts[3],
        )
        # parts[2] 已经含了后面内容（split(None, 2)），所以上面这行有点冗余
        # 修正：
        text = line.split(None, 2)[2] if len(line.split(None, 2)) > 2 else ""
        event = make_event(
            message_type="private",
            user_id=uid,
            message=text,
        )
        await broadcast(event)
        return True

    if cmd == "raw":
        raw_json = line[3:].strip() if line.lower().startswith("raw") else line[4:].strip()
        try:
            event = json.loads(raw_json)
        except Exception as e:
            print(f"[stdin] JSON 解析失败: {e}")
            return True
        await broadcast(event)
        return True

    print(f"[stdin] 未知命令: {cmd}")
    print_help()
    return True


# ------------------------------------------------------------
# 4. stdin 读取线程
# ------------------------------------------------------------
def _stdin_reader(loop, queue):
    """在线程里阻塞读 stdin，把行推给 asyncio 队列"""
    while True:
        try:
            line = sys.stdin.readline()
        except (EOFError, KeyboardInterrupt):
            break
        except Exception:
            break
        if not line:
            # EOF
            break
        loop.call_soon_threadsafe(queue.put_nowait, line.rstrip("\r\n"))


# ------------------------------------------------------------
# 5. 主入口
# ------------------------------------------------------------
async def main():
    global _input_queue
    _input_queue = asyncio.Queue()

    loop = asyncio.get_event_loop()
    t = threading.Thread(target=_stdin_reader, args=(loop, _input_queue), daemon=True)
    t.start()

    print("=" * 56)
    print("  stdin.py - OneBot V11 假服务器")
    print("=" * 56)
    print(f"监听: ws://{HOST}:{PORT}")
    print(f"假机器人 QQ: {SELF_ID}")
    print(f"默认测试群: {DEFAULT_GROUP_ID}    默认用户: {DEFAULT_USER_ID}")
    print()
    print("请确保 MeowTrigger 的 config/config.json 里")
    print(f'  "ws_url": "ws://{HOST}:{PORT}"')
    print()
    print_help()

    async with websockets.serve(ws_handler, HOST, PORT,
                                ping_interval=30, ping_timeout=10,
                                max_size=16 * 1024 * 1024):
        print(f"[stdin] 已启动，等待 MeowTrigger 连接...\n")
        running = True
        while running:
            try:
                line = await _input_queue.get()
            except asyncio.CancelledError:
                break
            line = line.strip()
            if not line:
                continue
            try:
                running = await dispatch(line)
            except Exception as e:
                print(f"[stdin] 处理异常: {e}")

    print("[stdin] 已退出")


def run():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[stdin] 收到中断信号")


if __name__ == "__main__":
    run()