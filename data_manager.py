"""
数据管理模块，负责待办事项的持久化存储。

存储路径：data/plugin_data/astrbot_plugin_todo/todos.json
存储键：
  - 群聊：{unified_msg_origin}_{sender_id}（群内每人独立）
  - 私聊：{unified_msg_origin}
"""

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta


class TodoItem:
    """待办事项数据模型。"""

    def __init__(
        self,
        content: str,
        deadline: datetime | None = None,
        todo_id: str | None = None,
        created_at: datetime | None = None,
        done: bool = False,
        done_at: datetime | None = None,
        reminded: bool = False,
        custom_reminder: datetime | None = None,
    ):
        self.id = todo_id or str(uuid.uuid4())[:8]
        self.content = content
        self.created_at = created_at or datetime.now()
        self.deadline = deadline
        self.done = done
        self.done_at = done_at
        self.reminded = reminded
        self.custom_reminder = custom_reminder

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "done": self.done,
            "done_at": self.done_at.isoformat() if self.done_at else None,
            "reminded": self.reminded,
            "custom_reminder": self.custom_reminder.isoformat()
            if self.custom_reminder
            else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TodoItem":
        return cls(
            content=data["content"],
            todo_id=data.get("id"),
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else None,
            deadline=datetime.fromisoformat(data["deadline"])
            if data.get("deadline")
            else None,
            done=data.get("done", False),
            done_at=datetime.fromisoformat(data["done_at"])
            if data.get("done_at")
            else None,
            reminded=data.get("reminded", False),
            custom_reminder=datetime.fromisoformat(data["custom_reminder"])
            if data.get("custom_reminder")
            else None,
        )


class DataManager:
    """待办事项数据管理器。"""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.data_file = os.path.join(self.data_dir, "todos.json")
        self._lock = asyncio.Lock()
        self._data: dict[str, list[dict]] = {}
        self._load()

    def _load(self):
        """从 JSON 文件加载数据。"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, encoding="utf-8") as f:
                    self._data = json.load(f)
            except (OSError, json.JSONDecodeError):
                self._data = {}
        else:
            self._data = {}

    async def _save(self):
        """异步保存数据到 JSON 文件。"""
        async with self._lock:
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def make_storage_key(
        unified_msg_origin: str, sender_id: str | None = None, is_group: bool = False
    ) -> str:
        """
        生成存储键。
        群聊：{umo}_{sender_id}，每群每人独立
        私聊：{umo}
        """
        if is_group and sender_id:
            return f"{unified_msg_origin}_{sender_id}"
        return unified_msg_origin

    def _get_items(self, key: str) -> list[TodoItem]:
        """获取指定键下的所有待办。"""
        raw = self._data.get(key, [])
        return [TodoItem.from_dict(item) for item in raw]

    def _set_items(self, key: str, items: list[TodoItem]):
        """设置指定键下的所有待办。"""
        self._data[key] = [item.to_dict() for item in items]

    async def add_todo(
        self, key: str, content: str, deadline: datetime | None = None
    ) -> TodoItem:
        """添加待办事项。"""
        item = TodoItem(content=content, deadline=deadline)
        items = self._get_items(key)
        items.append(item)
        self._set_items(key, items)
        await self._save()
        return item

    async def get_todos(self, key: str, include_done: bool = False) -> list[TodoItem]:
        """获取待办列表。"""
        items = self._get_items(key)
        if not include_done:
            items = [i for i in items if not i.done]
        return items

    async def mark_done(self, key: str, index: int) -> TodoItem | None:
        """标记第 index 条未完成待办为已完成（1-based）。"""
        items = self._get_items(key)
        undone = [i for i in items if not i.done]
        if index < 1 or index > len(undone):
            return None
        target = undone[index - 1]
        target.done = True
        target.done_at = datetime.now()
        self._set_items(key, items)
        await self._save()
        return target

    async def delete_todo(self, key: str, index: int) -> TodoItem | None:
        """删除第 index 条未完成待办（1-based）。"""
        items = self._get_items(key)
        undone = [i for i in items if not i.done]
        if index < 1 or index > len(undone):
            return None
        target = undone[index - 1]
        items.remove(target)
        self._set_items(key, items)
        await self._save()
        return target

    async def get_history(self, key: str, limit: int = 20) -> list[TodoItem]:
        """获取已完成待办（最近 limit 条）。"""
        items = self._get_items(key)
        done_items = [i for i in items if i.done]
        done_items.sort(key=lambda x: x.done_at or datetime.min, reverse=True)
        return done_items[:limit]

    async def clear_done(self, key: str) -> int:
        """清空已完成待办，返回清空数量。"""
        items = self._get_items(key)
        undone = [i for i in items if not i.done]
        cleared = len(items) - len(undone)
        self._set_items(key, undone)
        await self._save()
        return cleared

    async def set_custom_reminder(
        self, key: str, index: int, reminder_time: datetime
    ) -> TodoItem | None:
        """为第 index 条未完成待办设置自定义提醒时间（1-based）。"""
        items = self._get_items(key)
        undone = [i for i in items if not i.done]
        if index < 1 or index > len(undone):
            return None
        target = undone[index - 1]
        target.custom_reminder = reminder_time
        self._set_items(key, items)
        await self._save()
        return target

    async def set_reminded(self, key: str, todo_id: str):
        """标记某条待办已提醒。"""
        items = self._get_items(key)
        for item in items:
            if item.id == todo_id:
                item.reminded = True
                break
        self._set_items(key, items)
        await self._save()

    def get_all_keys(self) -> list[str]:
        """获取所有存储键。"""
        return list(self._data.keys())

    def get_due_today(self, key: str) -> list[TodoItem]:
        """获取今日到期的待办。"""
        items = self._get_items(key)
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        return [
            i
            for i in items
            if not i.done and i.deadline and today_start <= i.deadline <= today_end
        ]

    def get_overdue(self, key: str) -> list[TodoItem]:
        """获取已逾期未完成的待办。"""
        items = self._get_items(key)
        now = datetime.now()
        return [i for i in items if not i.done and i.deadline and i.deadline < now]

    def get_upcoming(self, key: str, days: int = 3) -> list[TodoItem]:
        """获取未来 N 天内到期的待办（不含今天）。"""
        items = self._get_items(key)
        now = datetime.now()
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        future = now + timedelta(days=days)
        return [
            i
            for i in items
            if not i.done and i.deadline and today_end < i.deadline <= future
        ]

    def get_needs_reminder(self, key: str, advance_minutes: int) -> list[TodoItem]:
        """获取需要截止提醒的待办（即将到期 + 未提醒）。"""
        items = self._get_items(key)
        now = datetime.now()
        threshold = now + timedelta(minutes=advance_minutes)
        return [
            i
            for i in items
            if not i.done
            and not i.reminded
            and i.deadline
            and now <= i.deadline <= threshold
        ]

    def get_custom_reminder_due(self, key: str) -> list[TodoItem]:
        """获取自定义提醒时间已到的待办。"""
        items = self._get_items(key)
        now = datetime.now()
        return [
            i
            for i in items
            if not i.done and i.custom_reminder and i.custom_reminder <= now
        ]

    def get_undone_count(self, key: str) -> int:
        """获取未完成待办数量。"""
        items = self._get_items(key)
        return sum(1 for i in items if not i.done)

    def get_done_count(self, key: str) -> int:
        """获取已完成待办数量。"""
        items = self._get_items(key)
        return sum(1 for i in items if i.done)
