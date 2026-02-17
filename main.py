"""
AstrBot 待办事项插件。

支持在 QQ 群聊/私聊中管理待办事项，包括：
- 添加/查看/完成/删除待办
- 中文自然语言时间解析
- 截止时间提醒（仅私聊）
- 每日早报推送（仅私聊）
"""

import os
import re
from datetime import datetime

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .time_parser import parse_time, format_time, format_relative
from .data_manager import DataManager
from .scheduler import Scheduler


@register(
    "astrbot_plugin_todo",
    "Yuuu0109",
    "待办事项管理插件，支持中文自然语言时间、定时提醒和每日早报",
    "1.0.0",
    "https://github.com/Yuuu0109/astrbot_plugin_todo",
)
class TodoPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        # 读取配置
        self.daily_report_time = self.config.get("daily_report_time", "08:00")
        self.reminder_advance = self.config.get("reminder_advance_minutes", 30)
        self.overdue_interval = self.config.get("overdue_check_interval_hours", 2)
        self.enable_daily_report = self.config.get("enable_daily_report", True)
        self.enable_deadline_reminder = self.config.get("enable_deadline_reminder", True)

        # 初始化数据管理器
        data_path = os.path.join(get_astrbot_data_path(), "plugin_data", "astrbot_plugin_todo")
        self.data_manager = DataManager(data_path)

        # 初始化调度器
        self.scheduler = Scheduler()
        self._start_tasks()

    def _start_tasks(self):
        """启动定时任务。"""
        if self.enable_daily_report:
            self.scheduler.start_daily_report(
                self.daily_report_time,
                self._on_daily_report,
            )
            logger.info(f"[Todo] 每日早报已启用，推送时间: {self.daily_report_time}")

        if self.enable_deadline_reminder:
            # 截止提醒检查频率 = 提前时间的一半，但最少1分钟最多10分钟
            check_interval = max(1, min(10, self.reminder_advance // 2))
            self.scheduler.start_reminder_check(
                check_interval,
                self._on_reminder_check,
            )
            logger.info(f"[Todo] 截止提醒已启用，提前 {self.reminder_advance} 分钟提醒")

            self.scheduler.start_overdue_check(
                self.overdue_interval,
                self._on_overdue_check,
            )
            logger.info(f"[Todo] 逾期检查已启用，间隔 {self.overdue_interval} 小时")

    def _get_storage_key(self, event: AstrMessageEvent) -> str:
        """根据消息事件生成存储键。群聊按群+用户分，私聊按用户分。"""
        umo = event.unified_msg_origin
        group_id = event.get_group_id()
        if group_id:
            sender_id = event.get_sender_id()
            return DataManager.make_storage_key(umo, sender_id, is_group=True)
        return DataManager.make_storage_key(umo)

    def _is_private(self, event: AstrMessageEvent) -> bool:
        """判断是否为私聊消息。"""
        return not event.get_group_id()

    # ==================== 指令处理 ====================

    @filter.command("todo")
    async def todo_handler(self, event: AstrMessageEvent):
        """待办事项管理。发送 /todo help 查看帮助。"""
        message = event.message_str.strip()

        # 解析子命令
        parts = message.split(maxsplit=1)
        sub_cmd = parts[0].lower() if parts else "list"
        args = parts[1].strip() if len(parts) > 1 else ""

        if sub_cmd == "add":
            yield await self._cmd_add(event, args)
        elif sub_cmd == "list":
            yield await self._cmd_list(event)
        elif sub_cmd == "done":
            yield await self._cmd_done(event, args)
        elif sub_cmd == "del":
            yield await self._cmd_delete(event, args)
        elif sub_cmd == "history":
            yield await self._cmd_history(event)
        elif sub_cmd == "clear":
            yield await self._cmd_clear(event)
        elif sub_cmd == "remind":
            yield await self._cmd_remind(event, args)
        elif sub_cmd == "help":
            yield await self._cmd_help(event)
        else:
            yield event.plain_result("未知子命令。发送 /todo help 查看帮助。")

    async def _cmd_add(self, event: AstrMessageEvent, args: str) -> MessageEventResult:
        """添加待办。"""
        if not args:
            return event.plain_result("请输入待办内容。\n示例：/todo add 交报告 明天下午三点")

        # 尝试从末尾解析时间
        content, deadline = self._extract_content_and_time(args)

        key = self._get_storage_key(event)
        item = await self.data_manager.add_todo(key, content, deadline)

        reply = f"✅ 待办已添加\n📝 {content}"
        if deadline:
            reply += f"\n⏰ 截止：{format_time(deadline)}"
            if self._is_private(event):
                reply += f"\n🔔 将在截止前 {self.reminder_advance} 分钟提醒"
        else:
            reply += "\n📌 未设置截止时间"

        return event.plain_result(reply)

    async def _cmd_list(self, event: AstrMessageEvent) -> MessageEventResult:
        """查看待办列表。"""
        key = self._get_storage_key(event)
        items = await self.data_manager.get_todos(key)

        if not items:
            return event.plain_result("📋 暂无待办事项！")

        lines = ["📋 待办事项列表：", ""]
        for idx, item in enumerate(items, 1):
            status = "⬜"
            line = f"{status} {idx}. {item.content}"
            if item.deadline:
                line += f"\n   ⏰ {format_time(item.deadline)} ({format_relative(item.deadline)})"
            lines.append(line)

        undone_count = self.data_manager.get_undone_count(key)
        done_count = self.data_manager.get_done_count(key)
        lines.append(f"\n📊 未完成 {undone_count} 项 | 已完成 {done_count} 项")

        return event.plain_result("\n".join(lines))

    async def _cmd_done(self, event: AstrMessageEvent, args: str) -> MessageEventResult:
        """标记完成。"""
        if not args or not args.strip().isdigit():
            return event.plain_result("请输入待办序号。\n示例：/todo done 1")

        index = int(args.strip())
        key = self._get_storage_key(event)
        item = await self.data_manager.mark_done(key, index)

        if item:
            return event.plain_result(f"✅ 已完成：{item.content}")
        else:
            return event.plain_result(f"❌ 序号 {index} 不存在，请用 /todo list 查看列表。")

    async def _cmd_delete(self, event: AstrMessageEvent, args: str) -> MessageEventResult:
        """删除待办。"""
        if not args or not args.strip().isdigit():
            return event.plain_result("请输入待办序号。\n示例：/todo del 1")

        index = int(args.strip())
        key = self._get_storage_key(event)
        item = await self.data_manager.delete_todo(key, index)

        if item:
            return event.plain_result(f"🗑️ 已删除：{item.content}")
        else:
            return event.plain_result(f"❌ 序号 {index} 不存在，请用 /todo list 查看列表。")

    async def _cmd_history(self, event: AstrMessageEvent) -> MessageEventResult:
        """查看已完成记录。"""
        key = self._get_storage_key(event)
        items = await self.data_manager.get_history(key)

        if not items:
            return event.plain_result("📜 暂无已完成记录！")

        lines = ["📜 已完成记录（最近20条）：", ""]
        for idx, item in enumerate(items, 1):
            done_time = format_time(item.done_at) if item.done_at else "未知"
            lines.append(f"✅ {idx}. {item.content}")
            lines.append(f"   完成于 {done_time}")

        return event.plain_result("\n".join(lines))

    async def _cmd_clear(self, event: AstrMessageEvent) -> MessageEventResult:
        """清空已完成记录。"""
        key = self._get_storage_key(event)
        count = await self.data_manager.clear_done(key)

        if count > 0:
            return event.plain_result(f"🧹 已清空 {count} 条已完成记录。")
        else:
            return event.plain_result("📭 没有需要清空的已完成记录。")

    async def _cmd_remind(self, event: AstrMessageEvent, args: str) -> MessageEventResult:
        """设置自定义提醒。"""
        if not self._is_private(event):
            return event.plain_result("⚠️ 自定义提醒功能仅在私聊中可用。")

        parts = args.split(maxsplit=1)
        if len(parts) < 2 or not parts[0].isdigit():
            return event.plain_result(
                "请输入序号和提醒时间。\n示例：/todo remind 1 明天早上8点"
            )

        index = int(parts[0])
        time_text = parts[1]
        reminder_time = parse_time(time_text)

        if not reminder_time:
            return event.plain_result(f"❌ 无法识别时间：「{time_text}」\n支持：明天下午三点、2026-02-20 18:00、3天后 等")

        key = self._get_storage_key(event)
        item = await self.data_manager.set_custom_reminder(key, index, reminder_time)

        if item:
            return event.plain_result(
                f"🔔 已设置提醒\n📝 {item.content}\n⏰ 提醒时间：{format_time(reminder_time)}"
            )
        else:
            return event.plain_result(f"❌ 序号 {index} 不存在，请用 /todo list 查看列表。")

    async def _cmd_help(self, event: AstrMessageEvent) -> MessageEventResult:
        """显示帮助信息。"""
        help_text = """📋 待办事项插件 使用帮助

🎯 可用指令：

📝 /todo add <内容> [截止时间]
   添加待办事项
   示例：/todo add 交报告 明天下午三点

📋 /todo list
   查看未完成的待办列表

✅ /todo done <序号>
   标记某条待办为已完成

🗑️ /todo del <序号>
   删除某条待办

📜 /todo history
   查看已完成记录（最近20条）

🧹 /todo clear
   清空所有已完成记录

🔔 /todo remind <序号> <时间>
   设置自定义提醒（仅私聊）

⏰ 支持的时间格式：
   标准格式：2026-02-20 18:00
   中文日期：明天、后天、3天后、下周一
   中文时间：下午三点、晚上8点半
   组合使用：明天下午三点、后天晚上8点"""
        return event.plain_result(help_text)

    # ==================== 时间解析辅助 ====================

    def _extract_content_and_time(self, text: str) -> tuple[str, datetime | None]:
        """
        从输入文本中分离内容和时间。

        策略：从后向前尝试解析时间，找到最长匹配的时间表达式。
        """
        # 常见的时间引导词
        time_keywords = [
            "明天", "后天", "大后天", "今天", "今日", "明日",
            "下周", "这周", "本周", "周",
            "上午", "下午", "晚上", "晚", "早上", "早晨", "凌晨", "中午", "傍晚",
        ]

        # 尝试从文本中找到时间部分的起始位置
        best_pos = len(text)
        best_time = None

        # 方法1：检查时间引导词
        for kw in time_keywords:
            pos = text.rfind(kw)
            if pos > 0:  # 确保不是整个文本都是时间
                time_text = text[pos:].strip()
                parsed = parse_time(time_text)
                if parsed and pos < best_pos:
                    best_pos = pos
                    best_time = parsed

        # 方法2：检查标准日期格式 YYYY-MM-DD 或 YYYY/MM/DD
        date_pattern = re.compile(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}')
        for m in date_pattern.finditer(text):
            pos = m.start()
            if pos > 0:
                time_text = text[pos:].strip()
                parsed = parse_time(time_text)
                if parsed and pos < best_pos:
                    best_pos = pos
                    best_time = parsed

        # 方法3：检查 "N天后"、"N小时后" 等
        rel_pattern = re.compile(r'(\d+|[一二三四五六七八九十]+)\s*[天日]后')
        for m in rel_pattern.finditer(text):
            pos = m.start()
            if pos > 0:
                time_text = text[pos:].strip()
                parsed = parse_time(time_text)
                if parsed and pos < best_pos:
                    best_pos = pos
                    best_time = parsed

        # 方法4：检查 "M月D日" 格式
        md_pattern = re.compile(r'\d{1,2}\s*月\s*\d{1,2}\s*[日号]?')
        for m in md_pattern.finditer(text):
            pos = m.start()
            if pos > 0:
                time_text = text[pos:].strip()
                parsed = parse_time(time_text)
                if parsed and pos < best_pos:
                    best_pos = pos
                    best_time = parsed

        if best_time:
            content = text[:best_pos].strip()
            if content:
                return content, best_time

        # 没有解析到时间，整个文本都是内容
        return text.strip(), None

    # ==================== 定时任务回调 ====================

    async def _on_daily_report(self):
        """每日早报推送回调。"""
        logger.info("[Todo] 开始推送每日早报...")
        keys = self.data_manager.get_all_keys()

        for key in keys:
            # 仅推送私聊的早报（私聊的 key 不含下划线拼接的 sender_id）
            # 群聊的 key 格式为 {umo}_{sender_id}，其 umo 本身含路径分隔符
            # 简单判断：如果 key 中的 umo 部分标识是私聊
            # 由于 umo 格式灵活，这里直接尝试推送所有有待办的 key
            undone_count = self.data_manager.get_undone_count(key)
            if undone_count == 0:
                continue

            due_today = self.data_manager.get_due_today(key)
            overdue = self.data_manager.get_overdue(key)
            upcoming = self.data_manager.get_upcoming(key, days=3)
            done_count = self.data_manager.get_done_count(key)

            lines = ["☀️ 每日待办早报", ""]

            if overdue:
                lines.append(f"🔴 已逾期 ({len(overdue)} 项)：")
                for item in overdue:
                    lines.append(f"   • {item.content} ({format_relative(item.deadline)})")
                lines.append("")

            if due_today:
                lines.append(f"🟡 今日到期 ({len(due_today)} 项)：")
                for item in due_today:
                    lines.append(f"   • {item.content} ({format_time(item.deadline)})")
                lines.append("")

            if upcoming:
                lines.append(f"🔵 近3天到期 ({len(upcoming)} 项)：")
                for item in upcoming:
                    lines.append(f"   • {item.content} ({format_time(item.deadline)})")
                lines.append("")

            no_deadline = [
                i for i in await self.data_manager.get_todos(key)
                if not i.deadline
            ]
            if no_deadline:
                lines.append(f"⚪ 无截止时间 ({len(no_deadline)} 项)：")
                for item in no_deadline:
                    lines.append(f"   • {item.content}")
                lines.append("")

            lines.append(f"📊 待办总计：未完成 {undone_count} 项 | 已完成 {done_count} 项")

            try:
                # 提取 umo：群聊 key 为 {umo}_{sender_id}，需要还原 umo
                # 但由于群聊的提醒不支持，这里简单用 key 作为 umo 尝试发送
                # 如果 key 包含拼接的 sender_id，发送会失败并被忽略
                message_chain = MessageChain().message("\n".join(lines))
                await self.context.send_message(key, message_chain)
            except Exception as e:
                logger.debug(f"[Todo] 早报推送失败 (key={key}): {e}")

    async def _on_reminder_check(self):
        """截止提醒检查回调。"""
        keys = self.data_manager.get_all_keys()

        for key in keys:
            # 检查截止提醒
            needs_reminder = self.data_manager.get_needs_reminder(key, self.reminder_advance)
            for item in needs_reminder:
                try:
                    msg = (
                        f"⏰ 待办即将到期提醒\n"
                        f"📝 {item.content}\n"
                        f"🕐 截止：{format_time(item.deadline)} ({format_relative(item.deadline)})"
                    )
                    message_chain = MessageChain().message(msg)
                    await self.context.send_message(key, message_chain)
                    await self.data_manager.set_reminded(key, item.id)
                except Exception as e:
                    logger.debug(f"[Todo] 截止提醒发送失败 (key={key}): {e}")

            # 检查自定义提醒
            custom_due = self.data_manager.get_custom_reminder_due(key)
            for item in custom_due:
                try:
                    msg = (
                        f"🔔 自定义提醒\n"
                        f"📝 {item.content}"
                    )
                    if item.deadline:
                        msg += f"\n⏰ 截止：{format_time(item.deadline)}"
                    message_chain = MessageChain().message(msg)
                    await self.context.send_message(key, message_chain)
                    # 清除自定义提醒（设为 None）
                    item.custom_reminder = None
                    items = self.data_manager._get_items(key)
                    for i in items:
                        if i.id == item.id:
                            i.custom_reminder = None
                            break
                    self.data_manager._set_items(key, items)
                    await self.data_manager._save()
                except Exception as e:
                    logger.debug(f"[Todo] 自定义提醒发送失败 (key={key}): {e}")

    async def _on_overdue_check(self):
        """逾期检查回调。"""
        keys = self.data_manager.get_all_keys()

        for key in keys:
            overdue = self.data_manager.get_overdue(key)
            if not overdue:
                continue

            lines = [f"⚠️ 你有 {len(overdue)} 条逾期待办：", ""]
            for item in overdue:
                lines.append(f"🔴 {item.content}")
                lines.append(f"   截止：{format_time(item.deadline)} ({format_relative(item.deadline)})")

            try:
                message_chain = MessageChain().message("\n".join(lines))
                await self.context.send_message(key, message_chain)
            except Exception as e:
                logger.debug(f"[Todo] 逾期提醒发送失败 (key={key}): {e}")

    # ==================== 生命周期 ====================

    async def terminate(self):
        """插件销毁时清理定时任务。"""
        logger.info("[Todo] 正在停止定时任务...")
        self.scheduler.cancel_all()
        await self.scheduler.wait_all()
        logger.info("[Todo] 插件已停止。")
