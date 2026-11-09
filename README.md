# MeowTrigger

自定义触发器引擎。既能**独立运行**成一个 OneBot V11 机器人，
也能**作为一个包**塞进别的程序（比如 ElyBot）里当触发器内核。

只依赖 `websockets`（独立运行必需）和 `croniter`（可选，定时触发器）。

```bash
pip install websockets croniter
python main.py --check     # 先看看配置对不对
python main.py             # 连上 OneBot 跑起来
```

## 两种用法

### 一、独立运行

```bash
python main.py
# 或者
python -m meowtrigger
# 指定配置
python main.py --config config/config.json --check
```

`main.py` 只做一件事：调用 `meowtrigger.cli.main()`，逻辑全在包里。

### 二、作为包嵌入

```python
from meowtrigger import TriggerEngine, MessageContext

engine = TriggerEngine("/path/to/MeowTrigger")
engine.reload()

ctx = MessageContext(
    text="晚安",
    umo="onebot:GroupMessage:123456789",
    user_id="20002", user_name="阿七", group_id="123456789",
)
reply = await engine.handle(ctx)     # 没命中返回 None
```

嵌入形态不需要 WebSocket、不需要进程，只要你把「一条消息」描述清楚。
`engine.handle()` 同时接受 `MessageContext`、任意带 `content` / `group_id`
的对象，也可以直接 `await engine.handle("晚安", umo="...", user_id="...")`。

## 文件夹结构

```
MeowTrigger/
├── main.py                     # 入口（薄壳）
├── pyproject.toml              # 可 pip install
├── meowtrigger/                # 包本体
│   ├── __init__.py             # 对外 API
│   ├── cli.py                  # 命令行
│   ├── app.py                  # 独立运行形态（引擎 + OneBot）
│   ├── engine.py               # TriggerEngine：可嵌入内核
│   ├── context.py              # MessageContext：框架无关的消息
│   ├── umo.py                  # UMO 解析 / 生成 / 匹配
│   ├── scope.py                # MTPlugins 的 G/U 目录命名
│   └── core/                   # 匹配、执行、沙箱、命令、紧急控制…
├── config/config.json          # 主配置（首次运行自动生成）
├── plugins/
│   ├── *.json                  # 全局触发器
│   └── MTPlugins/              # 群配置 / 用户配置
│       ├── G123456789_夜猫子群/plugin.json
│       ├── U10001_小林/plugin.json
│       └── 全群播报.json
└── core/                       # 兼容层（旧 import 路径）
```

## MTPlugins：群配置与用户配置

`plugins/MTPlugins/` 专门放「只对某个群 / 某个人生效」的配置。
目录名前面加一个字母就能看出来是谁的：

| 目录名 | 含义 |
|---|---|
| `G123456789_夜猫子群` | 群 123456789，自定义名称「夜猫子群」 |
| `U10001_小林` | 用户 10001，自定义名称「小林」 |
| `G123456789` | 群 123456789（不写自定义名也行） |
| `123456789` | 旧写法，按群处理 |

- `G` = group 群聊，`U` = user 用户
- `_` 后面随便起名，只影响可读性，不参与匹配
- 目录里的 `plugin.json` **必须**有 `umo` 字段，且要和目录前缀对得上，
  否则启动时会报错并跳过（宁可报错，也不要「以为生效了其实没有」）

```json
{
  "plugin_name": "夜猫子群专属",
  "umo": "onebot:GroupMessage:123456789",
  "triggers": [
    {
      "name": "群晚安",
      "trigger_type": "fullmatch",
      "trigger_pattern": "晚安",
      "response_type": "text",
      "response_content": "晚安 {user_name}♪"
    }
  ]
}
```

## UMO 是什么

UMO（Unified Message Origin）用三段话把「消息从哪来」说清楚：

```
platform:message_type:session_id
onebot:GroupMessage:123456789
aiocqhttp:FriendMessage:987654321
```

- `platform`：`onebot` / `aiocqhttp` / `qq_official` ……
- `message_type`：`GroupMessage` / `FriendMessage` / `PrivateMessage` / `TempMessage`
- `session_id`：群号或用户号
- 任意一段可写 `*` 通配：`onebot:GroupMessage:*` = 所有群

一条触发器带 `umo` 时，只在匹配的会话里生效；不带就照旧全局生效。
触发器自己的 `umo` 会覆盖插件级 `umo`，所以一个插件里可以写多条
分属不同群的触发器。

## 触发器示例（全局）

```json
{
  "plugin_name": "我的插件",
  "description": "示例",
  "triggers": [
    {
      "name": "问候",
      "trigger_type": "keyword",
      "trigger_pattern": "你好",
      "response_type": "text",
      "response_content": "你好 {user_name}！"
    }
  ]
}
```

触发类型：`keyword` / `fullmatch` / `regex` / `command` / `cron`
响应类型：`text` / `script` / `script_file` / `system`

## 命令（默认前缀 `/mt`）

| 命令 | 权限 | 说明 |
|---|---|---|
| `/mt 帮助` | 所有人 | 显示帮助 |
| `/mt 列表` | 所有人 | 列出所有触发器 |
| `/mt 查询 <名称>` | 所有人 | 查看触发器详情 |
| `/mt 触发 <名称> [参数]` | 所有人 | 手动触发 |
| `/mt 重载` | 管理员 | 重载配置 |
| `/mt 群添加 ...` | 群管 | 添加群触发器 |
| `/mt 群删除 <名称>` | 群管 | 删除群触发器 |
| `/mt 群列表` | 所有人 | 列出群触发器 |
| `/mt 强制解锁群 [群号]` | 管理员 | 解锁群 |
| `/mt 强制解锁全局` | 管理员 | 解锁全局 |
| `/mt 紧急停止` | 群管/投票 | 停止触发器 |
| `/mt 紧急清除 [群号]` | 管理员 | 清除群触发器 |
| `/mt 支持 / 反对` | 所有人 | 投票 |
| `/mt 状态` | 所有人 | 查看状态 |

## 脚本变量

- `user_id`, `user_name`, `group_id`, `time`, `date`
- `args`, `match`, `message`, `umo`
- OneBot V11 API 函数（`send_group_msg`、`set_group_ban` ……）

## 在 ElyBot 里用

ElyBot 的插件目录里放一个 `MTPlugins/`：

```
ElyBot/plugins/MTPlugins/
├── G123456789_夜猫子群/plugin.json
└── U10001_小林/plugin.json
```

ElyBot 的 `meowtrigger` 加载引擎会扫这个目录，按 UMO 只把
「当前会话该生效」的触发器挂上去，脚本执行交给本包的 `ScriptExecutor`。

## 授权许可

MIT License
