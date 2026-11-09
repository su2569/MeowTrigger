# MTPlugins — 群配置 / 用户配置

这里放**只对某个群或某个人生效**的触发器。目录名用前缀直接说明归属：

| 目录名 | 含义 | umo |
|---|---|---|
| `G123456789_夜猫子群` | 群 123456789 | `onebot:GroupMessage:123456789` |
| `U10001_小林` | 用户 10001 | `onebot:PrivateMessage:10001` |
| `G123456789` | 群（不带自定义名也行） | `onebot:GroupMessage:123456789` |
| `123456789` | 群（旧写法，兼容） | 自动补 |

- `G` = group 群聊，`U` = user 用户
- `_` 后面的自定义名称随便起，只为了方便认人；真正生效的是 `G/U` + 数字 ID
- 目录里的 `plugin.json` **必须**有 `umo` 字段，并且要和目录前缀对得上

```json
{
  "plugin_name": "夜猫子群专属",
  "umo": "onebot:GroupMessage:123456789",
  "triggers": [
    {
      "name": "晚安",
      "trigger_type": "fullmatch",
      "trigger_pattern": "晚安",
      "response_type": "text",
      "response_content": "晚安 {user_name}，做个好梦♪"
    }
  ]
}
```

也可以直接把 `plugin.json` 写在 `MTPlugins/` 根目录（单文件插件），
只要 `umo` 写清楚就行；`umo` 里用 `*` 可以表示整个平台 / 全部会话：

- `onebot:GroupMessage:*` → 所有群
- `*:*:*` → 全部（等价于不限制）
