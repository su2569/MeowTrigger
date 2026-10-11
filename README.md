# MeowTrigger

独立的自定义触发器机器人，基于 **OneBot V11** 协议，完全脱离 AstrBot。
仅依赖 `websockets`（必需）和 `croniter`（可选，用于定时任务）。

## 特性

- 5 种触发类型：`keyword` / `fullmatch` / `regex` / `command` / `cron`
- 4 种响应类型：`text` / `script` / `script_file` / `system`
- 插件式分散配置（`plugins/*.json`）+ 群专属配置（`plugins/<群号>/*.json`）
- 反重复触发、消息去重、冷却、权限、群隔离
- 沙箱执行（`none` / `sandbox` / `local`）
- 紧急锁定 + 投票机制
- 分级日志，可转发到群

## 安装

```bash
pip install websockets croniter
```

## 启动

1. 编辑 `config/config.json`，把 `ws_url` 改成你的 OneBot 反向 WS 地址（默认 `ws://127.0.0.1:3001`），填写 `access_token`（如需要），把管理员 QQ 加入 `admin_users`。
2. 运行 `python main.py`

## 目录

```
MeowTrigger/
├── main.py                  # 入口
├── config/config.json       # 主配置（首次运行自动生成）
├── plugins/*.json           # 触发器
├── plugins/<群号>/*.json    # 群专属触发器
└── core/                    # 核心模块
```

## 触发器示例

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
      "response_content": "你好 {user_name}！",
      "permission": "all",
      "cooldown": 3
    }
  ]
}
```

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
- `args`, `match`, `message`, `output`, `result`
- OneBot V11 API 函数（如 `send_group_msg`, `set_group_ban` 等）

## 授权许可

MIT License
