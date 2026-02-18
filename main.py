"""
AstrBot 待办事项插件。

支持在 QQ 群聊/私聊中管理待办事项，包括：
- 添加/查看/完成/删除待办
- 中文自然语言时间解析
- 截止时间提醒（仅私聊）
- 每日早报推送（仅私聊）
"""

import os
from datetime import datetime

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.command import GreedyStr
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .data_manager import DataManager
from .scheduler import Scheduler
from .time_parser import format_relative, format_time, parse_time


@register(
    "astrbot_plugin_todo",
    "Yuuu0109",
    "待办事项管理插件，支持中文自然语言时间、定时提醒和每日早报",
    "1.0.3",
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
        self.enable_deadline_reminder = self.config.get(
            "enable_deadline_reminder", True
        )

        # 初始化数据管理器
        data_path = os.path.join(
            get_astrbot_data_path(), "plugin_data", "astrbot_plugin_todo"
        )
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
        """根据消息事件生成存储键。群聊全群共享。"""
        return event.unified_msg_origin

    def _is_private(self, event: AstrMessageEvent) -> bool:
        """判断是否为私聊消息。"""
        return not event.get_group_id()

    # ==================== 指令组 ====================

    @filter.command_group("todo")
    def todo(self):
        """待办事项管理"""
        pass

    @todo.command("add")
    async def todo_add(self, event: AstrMessageEvent, content: GreedyStr):
        """添加待办事项。用法: /todo add [截止时间] <内容>"""
        if not content:
            yield event.plain_result(
                "请输入待办内容。\n示例：/todo add 明天下午三点 交报告"
            )
            return

        # 分离内容和时间
        text, deadline = self._extract_content_and_time(content)

        key = self._get_storage_key(event)
        await self.data_manager.add_todo(key, text, deadline)

        # 获取当前所有未完成待办，确定新添加的序号
        items = await self.data_manager.get_todos(key)
        new_index = len(items)  # 新添加的在末尾

        reply = f"待办已添加 (序号 {new_index})\n{text}"
        if deadline:
            reply += f"\n截止：{format_time(deadline)}"
            if self._is_private(event):
                reply += f"\n将在截止前 {self.reminder_advance} 分钟提醒"
        else:
            reply += "\n未设置截止时间"

        # 附带当前全部待办列表
        reply += "\n\n当前待办列表："
        for idx, item in enumerate(items, 1):
            marker = " <-- 新增" if idx == new_index else ""
            line = f"\n{idx}. {item.content}"
            if item.deadline:
                line += f" ({format_time(item.deadline)})"
            line += marker
            reply += line

        yield event.plain_result(reply)

    @todo.command("list")
    async def todo_list(self, event: AstrMessageEvent):
        """查看未完成的待办列表"""
        key = self._get_storage_key(event)
        items = await self.data_manager.get_todos(key)

        if not items:
            yield event.plain_result("暂无待办事项！")
            return

        lines = ["待办事项列表：", ""]
        for idx, item in enumerate(items, 1):
            line = f"{idx}. {item.content}"
            if item.deadline:
                line += f"\n   {format_time(item.deadline)} ({format_relative(item.deadline)})"
            lines.append(line)

        undone_count = self.data_manager.get_undone_count(key)
        done_count = self.data_manager.get_done_count(key)
        lines.append(f"\n未完成 {undone_count} 项 | 已完成 {done_count} 项")

        yield event.plain_result("\n".join(lines))

    @todo.command("done")
    async def todo_done(self, event: AstrMessageEvent, index: int):
        """标记待办为已完成。用法: /todo done <序号>"""
        key = self._get_storage_key(event)
        item = await self.data_manager.mark_done(key, index)

        if item:
            yield event.plain_result(f"已完成：{item.content}")
        else:
            yield event.plain_result(f"序号 {index} 不存在，请用 /todo list 查看列表。")

    @todo.command("del")
    async def todo_del(self, event: AstrMessageEvent, index: int):
        """删除待办。用法: /todo del <序号>"""
        key = self._get_storage_key(event)
        item = await self.data_manager.delete_todo(key, index)

        if item:
            yield event.plain_result(f"已删除：{item.content}")
        else:
            yield event.plain_result(f"序号 {index} 不存在，请用 /todo list 查看列表。")

    @todo.command("del_all")
    async def todo_del_all(self, event: AstrMessageEvent):
        """删除所有未完成的待办事项"""
        key = self._get_storage_key(event)
        count = await self.data_manager.delete_all_todos(key)

        if count > 0:
            yield event.plain_result(f"已删除全部 {count} 条待办事项。")
        else:
            yield event.plain_result("暂无待办事项可删除。")

    @todo.command("history")
    async def todo_history(self, event: AstrMessageEvent):
        """查看已完成记录（最近20条）"""
        key = self._get_storage_key(event)
        items = await self.data_manager.get_history(key)

        if not items:
            yield event.plain_result("暂无已完成记录！")
            return

        lines = ["已完成记录（最近20条）：", ""]
        for idx, item in enumerate(items, 1):
            done_time = format_time(item.done_at) if item.done_at else "未知"
            lines.append(f"{idx}. {item.content}")
            lines.append(f"   完成于 {done_time}")

        yield event.plain_result("\n".join(lines))

    @todo.command("history_clear")
    async def todo_clear(self, event: AstrMessageEvent):
        """清空所有已完成记录"""
        key = self._get_storage_key(event)
        count = await self.data_manager.clear_done(key)

        if count > 0:
            yield event.plain_result(f"已清空 {count} 条已完成记录。")
        else:
            yield event.plain_result("没有需要清空的已完成记录。")

    @todo.command("remind")
    async def todo_remind(
        self, event: AstrMessageEvent, index: int, time_text: GreedyStr
    ):
        """设置自定义提醒（仅私聊）。用法: /todo remind <序号> <时间>"""
        if not self._is_private(event):
            yield event.plain_result("自定义提醒功能仅在私聊中可用。")
            return

        reminder_time = parse_time(time_text)
        if not reminder_time:
            yield event.plain_result(
                f"无法识别时间：「{time_text}」\n支持：明天下午三点、2026-02-20 18:00、3天后 等"
            )
            return

        key = self._get_storage_key(event)
        item = await self.data_manager.set_custom_reminder(key, index, reminder_time)

        if item:
            yield event.plain_result(
                f"已设置提醒\n{item.content}\n提醒时间：{format_time(reminder_time)}"
            )
        else:
            yield event.plain_result(f"序号 {index} 不存在，请用 /todo list 查看列表。")

    @todo.command("test_report")
    async def todo_test_report(self, event: AstrMessageEvent):
        """测试早报推送（立即发送一次早报到当前会话）"""
        key = self._get_storage_key(event)
        undone_count = self.data_manager.get_undone_count(key)

        if undone_count == 0:
            yield event.plain_result("暂无待办事项，无需生成早报。")
            return

        due_today = self.data_manager.get_due_today(key)
        overdue = self.data_manager.get_overdue(key)
        upcoming = self.data_manager.get_upcoming(key, days=3)
        done_count = self.data_manager.get_done_count(key)
        items = await self.data_manager.get_todos(key)

        lines = ["每日待办早报（测试）", ""]

        if overdue:
            lines.append(f"[已逾期] ({len(overdue)} 项)：")
            for item in overdue:
                lines.append(f"   - {item.content} ({format_relative(item.deadline)})")
            lines.append("")

        if due_today:
            lines.append(f"[今日到期] ({len(due_today)} 项)：")
            for item in due_today:
                lines.append(f"   - {item.content} ({format_time(item.deadline)})")
            lines.append("")

        if upcoming:
            lines.append(f"[近3天到期] ({len(upcoming)} 项)：")
            for item in upcoming:
                lines.append(f"   - {item.content} ({format_time(item.deadline)})")
            lines.append("")

        no_deadline = [i for i in items if not i.deadline]
        if no_deadline:
            lines.append(f"[无截止时间] ({len(no_deadline)} 项)：")
            for item in no_deadline:
                lines.append(f"   - {item.content}")
            lines.append("")

        lines.append(f"待办总计：未完成 {undone_count} 项 | 已完成 {done_count} 项")

        yield event.plain_result("\n".join(lines))

    @todo.command("new")
    async def todo_new(self, event: AstrMessageEvent):
        """查看最新更新日志"""
        changelog_path = os.path.join(os.path.dirname(__file__), "CHANGELOG.md")
        if not os.path.exists(changelog_path):
            yield event.plain_result("未找到更新日志文件。")
            return

        with open(changelog_path, encoding="utf-8") as f:
            content = f.read()

        # 提取最新版本日志
        lines = content.split("\n")
        latest_log = []
        found_version = False

        for line in lines:
            if line.startswith("## v"):
                if found_version:
                    break
                found_version = True
                latest_log.append(line)
            elif found_version:
                latest_log.append(line)

        if not latest_log:
            yield event.plain_result("无法解析更新日志。")
            return

        yield event.plain_result("\n".join(latest_log).strip())

    @todo.command("at_all")
    async def todo_at_all(self, event: AstrMessageEvent, switch: str):
        """设置群聊提醒是否@全体成员。用法: /todo at_all y/n"""
        if self._is_private(event):
            yield event.plain_result("该指令仅在群聊中可用。")
            return

        switch = switch.strip().lower()
        if switch not in ("y", "n"):
            yield event.plain_result("请输入 y 或 n。\n示例：/todo at_all y")
            return

        key = self._get_storage_key(event)
        enabled = switch == "y"
        await self.data_manager.set_setting(key, "at_all", enabled)

        status = "开启" if enabled else "关闭"
        yield event.plain_result(f"群聊提醒@全体成员已{status}。")

    @todo.command("help")
    async def todo_help(self, event: AstrMessageEvent):
        """查看帮助信息"""
        help_text = """使用帮助

基础指令：

/todo add [截止时间] <内容>
   添加待办事项
   示例：/todo add 明天下午三点 交报告

/todo list
   查看未完成的待办列表

/todo done <序号>
   标记某条待办为已完成

/todo del <序号>
   删除某条待办

/todo del_all
   删除所有未完成的待办

/todo history
   查看已完成记录（最近20条）

/todo history_clear
   清空所有已完成记录

/todo remind <序号> <时间>
   设置自定义提醒（仅私聊）

/todo test_report
   测试早报推送（立即发送一次）

/todo new
   查看最新更新日志

/todo at_all y/n
   设置群聊提醒是否@全体成员（仅群聊）

支持的时间格式：
   标准格式：2026-02-20 18:00
   中文日期：明天、后天、3天后、下周一
   中文时间：下午三点、晚上8点半
   组合使用：明天下午三点、后天晚上8点"""
        yield event.plain_result(help_text)

    # ==================== 时间解析辅助 ====================

    def _extract_content_and_time(self, text: str) -> tuple[str, datetime | None]:
        """从输入文本中分离时间和内容（时间在前，内容在后）。

        采用按空格分词后逐步组合的方式，避免 parse_time 内部
        re.search 匹配子串导致的误判。
        """
        text = text.strip()
        if not text:
            return text, None

        # 按空格分割为词组
        parts = text.split()
        if len(parts) <= 1:
            # 只有一个词，尝试整体解析为时间（只有时间没有内容则不拆分）
            parsed = parse_time(text)
            if parsed:
                # 整个输入就是时间，没有内容，当作纯内容处理
                return text, None
            return text, None

        # 从前往后逐步将更多的词加入时间部分
        best_split = 0  # 分割点：前 best_split 个词是时间
        best_time = None

        for i in range(1, len(parts)):
            candidate = " ".join(parts[:i])
            parsed = parse_time(candidate)
            if parsed:
                best_split = i
                best_time = parsed

        if best_time:
            content = " ".join(parts[best_split:]).strip()
            if content:
                return content, best_time

        return text.strip(), None

    # ==================== 定时任务回调 ====================

    async def _on_daily_report(self):
        """每日早报推送回调。"""
        logger.info("[Todo] 开始推送每日早报...")
        keys = self.data_manager.get_all_keys()

        for key in keys:
            undone_count = self.data_manager.get_undone_count(key)
            if undone_count == 0:
                continue

            due_today = self.data_manager.get_due_today(key)
            overdue = self.data_manager.get_overdue(key)
            upcoming = self.data_manager.get_upcoming(key, days=3)
            done_count = self.data_manager.get_done_count(key)

            lines = ["每日待办早报", ""]

            if overdue:
                lines.append(f"[已逾期] ({len(overdue)} 项)：")
                for item in overdue:
                    lines.append(
                        f"   - {item.content} ({format_relative(item.deadline)})"
                    )
                lines.append("")

            if due_today:
                lines.append(f"[今日到期] ({len(due_today)} 项)：")
                for item in due_today:
                    lines.append(f"   - {item.content} ({format_time(item.deadline)})")
                lines.append("")

            if upcoming:
                lines.append(f"[近3天到期] ({len(upcoming)} 项)：")
                for item in upcoming:
                    lines.append(f"   - {item.content} ({format_time(item.deadline)})")
                lines.append("")

            no_deadline = [
                i for i in await self.data_manager.get_todos(key) if not i.deadline
            ]
            if no_deadline:
                lines.append(f"[无截止时间] ({len(no_deadline)} 项)：")
                for item in no_deadline:
                    lines.append(f"   - {item.content}")
                lines.append("")

            lines.append(f"待办总计：未完成 {undone_count} 项 | 已完成 {done_count} 项")

            try:
                at_all = self.data_manager.get_setting(key, "at_all", False)
                message_chain = MessageChain().message("\n".join(lines))
                if at_all:
                    message_chain = message_chain.at_all()
                await self.context.send_message(key, message_chain)
            except Exception as e:
                logger.debug(f"[Todo] 早报推送失败 (key={key}): {e}")

    async def _on_reminder_check(self):
        """截止提醒检查回调。"""
        keys = self.data_manager.get_all_keys()

        for key in keys:
            needs_reminder = self.data_manager.get_needs_reminder(
                key, self.reminder_advance
            )
            for item in needs_reminder:
                try:
                    msg = (
                        f"待办即将到期提醒\n"
                        f"{item.content}\n"
                        f"截止：{format_time(item.deadline)} ({format_relative(item.deadline)})"
                    )
                    at_all = self.data_manager.get_setting(key, "at_all", False)
                    message_chain = MessageChain().message(msg)
                    if at_all:
                        message_chain = message_chain.at_all()
                    await self.context.send_message(key, message_chain)
                    await self.data_manager.set_reminded(key, item.id)
                except Exception as e:
                    logger.debug(f"[Todo] 截止提醒发送失败 (key={key}): {e}")

            custom_due = self.data_manager.get_custom_reminder_due(key)
            for item in custom_due:
                try:
                    msg = f"自定义提醒\n{item.content}"
                    if item.deadline:
                        msg += f"\n截止：{format_time(item.deadline)}"
                    message_chain = MessageChain().message(msg)
                    await self.context.send_message(key, message_chain)
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

            lines = [f"你有 {len(overdue)} 条逾期待办：", ""]
            for item in overdue:
                lines.append(f"- {item.content}")
                lines.append(
                    f"   截止：{format_time(item.deadline)} ({format_relative(item.deadline)})"
                )

            try:
                at_all = self.data_manager.get_setting(key, "at_all", False)
                message_chain = MessageChain().message("\n".join(lines))
                if at_all:
                    message_chain = message_chain.at_all()
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
