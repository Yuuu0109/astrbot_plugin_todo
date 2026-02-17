"""
定时任务调度模块。

使用 asyncio 实现以下定时任务：
- 每日早报推送（仅私聊会话）
- 截止时间提醒（仅私聊待办）
- 逾期检查（仅私聊待办）
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from astrbot.api import logger


class Scheduler:
    """定时任务调度器。"""

    def __init__(self):
        self._tasks: list[asyncio.Task] = []

    def start_daily_report(
        self,
        report_time: str,
        callback: Callable[[], Awaitable[None]],
    ):
        """
        启动每日早报定时任务。

        Args:
            report_time: 早报时间，格式 "HH:MM"
            callback: 早报回调函数
        """
        task = asyncio.create_task(self._daily_report_loop(report_time, callback))
        self._tasks.append(task)

    def start_reminder_check(
        self,
        interval_minutes: int,
        callback: Callable[[], Awaitable[None]],
    ):
        """
        启动截止提醒检查定时任务。

        Args:
            interval_minutes: 检查间隔（分钟）
            callback: 检查回调函数
        """
        task = asyncio.create_task(self._interval_loop(interval_minutes * 60, callback, "截止提醒"))
        self._tasks.append(task)

    def start_overdue_check(
        self,
        interval_hours: int,
        callback: Callable[[], Awaitable[None]],
    ):
        """
        启动逾期检查定时任务。

        Args:
            interval_hours: 检查间隔（小时）
            callback: 检查回调函数
        """
        task = asyncio.create_task(self._interval_loop(interval_hours * 3600, callback, "逾期检查"))
        self._tasks.append(task)

    async def _daily_report_loop(self, report_time: str, callback: Callable[[], Awaitable[None]]):
        """每日定时执行的循环。"""
        while True:
            try:
                now = datetime.now()
                # 解析目标时间
                parts = report_time.split(":")
                target_hour = int(parts[0])
                target_minute = int(parts[1]) if len(parts) > 1 else 0

                target = now.replace(
                    hour=target_hour, minute=target_minute, second=0, microsecond=0
                )
                if target <= now:
                    target += timedelta(days=1)

                wait_seconds = (target - now).total_seconds()
                logger.info(f"[Todo] 每日早报将在 {target.strftime('%Y-%m-%d %H:%M')} 执行，等待 {wait_seconds:.0f} 秒")
                await asyncio.sleep(wait_seconds)

                try:
                    await callback()
                except Exception as e:
                    logger.error(f"[Todo] 每日早报执行出错: {e}")

            except asyncio.CancelledError:
                logger.info("[Todo] 每日早报任务已取消")
                break
            except Exception as e:
                logger.error(f"[Todo] 每日早报循环出错: {e}")
                await asyncio.sleep(60)  # 出错后等待1分钟再重试

    async def _interval_loop(
        self,
        interval_seconds: int,
        callback: Callable[[], Awaitable[None]],
        name: str,
    ):
        """固定间隔执行的循环。"""
        # 首次执行等待一小段时间，让插件初始化完成
        await asyncio.sleep(30)
        while True:
            try:
                try:
                    await callback()
                except Exception as e:
                    logger.error(f"[Todo] {name}执行出错: {e}")

                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                logger.info(f"[Todo] {name}任务已取消")
                break
            except Exception as e:
                logger.error(f"[Todo] {name}循环出错: {e}")
                await asyncio.sleep(60)

    def cancel_all(self):
        """取消所有定时任务。"""
        for task in self._tasks:
            if not task.done():
                task.cancel()
        self._tasks.clear()

    async def wait_all(self):
        """等待所有任务完成取消。"""
        for task in self._tasks:
            if not task.done():
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"[Todo] 等待任务取消时出错: {e}")
