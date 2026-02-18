<p align="center">
  <img src="logo.png" alt="Todo Plugin Logo" width="200">
</p>

<h2 align="center">astrbot_plugin_todo</h1>

AstrBot 待办事项管理插件，支持在 QQ 群聊/私聊中管理待办事项。

## 功能特性

- 待办事项的添加、查看、完成、删除
- 中文自然语言时间解析（明天下午三点、后天、3天后、下周一等）
- 截止时间提醒（私聊直接推送，群聊可选@全体成员）
- 每日早报推送（私聊直接推送，群聊可选@全体成员）
- 群聊中全群共享待办列表

## 指令列表

| 指令 | 说明 | 示例 |
|------|------|------|
| `/todo add [时间] <内容>` | 添加待办 | `/todo add 明天下午三点 交报告` |
| `/todo list` | 查看未完成待办 | `/todo list` |
| `/todo done <序号>` | 标记完成 | `/todo done 1` |
| `/todo del <序号>` | 删除待办 | `/todo del 2` |
| `/todo del_all` | 删除所有未完成待办 | `/todo del_all` |
| `/todo history` | 查看已完成 | `/todo history` |
| `/todo clear` | 清空已完成 | `/todo clear` |
| `/todo remind <序号> <时间>` | 设置提醒（仅私聊） | `/todo remind 1 明天早上8点` |
| `/todo test_report` | 测试早报推送 | `/todo test_report` |
| `/todo new` | 查看更新日志 | `/todo new` |
| `/todo at_all y/n` | 群聊提醒@全体成员开关 | `/todo at_all y` |
| `/todo help` | 查看帮助 | `/todo help` |

## 支持的时间格式

- **标准格式**：`2026-02-20 18:00`
- **中文日期**：明天、后天、大后天、3天后、下周一
- **中文时间**：下午三点、晚上8点半、上午十点三十分
- **组合使用**：明天下午三点、后天晚上8点

## 配置项

在 AstrBot WebUI 中可配置以下参数：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| 每日早报推送时间 | 格式 HH:MM | 08:00 |
| 截止前提前提醒（分钟） | 截止前多少分钟提醒 | 30 |
| 逾期检查间隔（小时） | 多久检查一次逾期 | 2 |
| 启用每日早报 | 是否启用 | 开启 |
| 启用截止时间提醒 | 是否启用 | 开启 |

## 更新日志

查看 [CHANGELOG.md](CHANGELOG.md) 了解版本更新详情。
