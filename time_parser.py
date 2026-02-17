"""
轻量级中文自然语言时间解析器。

支持的格式：
- 标准格式：2026-02-20 18:00 / 2026/02/20 18:00
- 相对日期：明天、后天、大后天、N天后、下周X
- 中文时间：下午三点、晚上8点半、上午十点三十分
- 组合：明天下午三点、后天晚上8点
"""

import re
from datetime import datetime, timedelta

# 中文数字映射
CN_NUM_MAP = {
    "零": 0, "〇": 0,
    "一": 1, "壹": 1,
    "二": 2, "两": 2, "贰": 2,
    "三": 3, "叁": 3,
    "四": 4, "肆": 4,
    "五": 5, "伍": 5,
    "六": 6, "陆": 6,
    "七": 7, "柒": 7,
    "八": 8, "捌": 8,
    "九": 9, "玖": 9,
    "十": 10, "拾": 10,
}

# 星期映射
WEEKDAY_MAP = {
    "一": 0, "二": 1, "三": 2, "四": 3,
    "五": 4, "六": 5, "日": 6, "天": 6,
}


def cn_to_int(cn_str: str) -> int | None:
    """将中文数字字符串转为整数。支持 一~九十九 的范围。"""
    if not cn_str:
        return None

    # 如果已经是阿拉伯数字
    if cn_str.isdigit():
        return int(cn_str)

    # 单个中文数字
    if cn_str in CN_NUM_MAP:
        return CN_NUM_MAP[cn_str]

    result = 0
    # 处理 "十X"、"X十"、"X十X" 的情况
    if "十" in cn_str or "拾" in cn_str:
        sep = "十" if "十" in cn_str else "拾"
        parts = cn_str.split(sep)
        tens = CN_NUM_MAP.get(parts[0], 1) if parts[0] else 1  # "十二" → 1*10+2
        ones = CN_NUM_MAP.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        result = tens * 10 + ones
    else:
        # 尝试逐字转换（如 "二三" 按单字处理，取第一个）
        for ch in cn_str:
            if ch in CN_NUM_MAP:
                result = result * 10 + CN_NUM_MAP[ch]
            else:
                return None

    return result if result > 0 else None


def _parse_relative_date(text: str, base: datetime) -> datetime | None:
    """解析相对日期，如 明天、后天、3天后、下周一。"""
    today = base.replace(hour=0, minute=0, second=0, microsecond=0)

    if text == "今天" or text == "今日":
        return today
    if text == "明天" or text == "明日":
        return today + timedelta(days=1)
    if text == "后天":
        return today + timedelta(days=2)
    if text == "大后天":
        return today + timedelta(days=3)

    # N天后 / N日后
    m = re.match(r"(\d+|[一二三四五六七八九十百]+)\s*[天日]后", text)
    if m:
        n = cn_to_int(m.group(1))
        if n:
            return today + timedelta(days=n)

    # 下周X
    m = re.match(r"下周([一二三四五六日天])", text)
    if m:
        target_wd = WEEKDAY_MAP.get(m.group(1))
        if target_wd is not None:
            current_wd = base.weekday()
            days_ahead = (target_wd - current_wd) % 7
            days_ahead += 7  # "下周" 一定是下一个周
            return today + timedelta(days=days_ahead)

    # 这周X / 本周X / 周X
    m = re.match(r"(?:这|本)?周([一二三四五六日天])", text)
    if m:
        target_wd = WEEKDAY_MAP.get(m.group(1))
        if target_wd is not None:
            current_wd = base.weekday()
            days_ahead = (target_wd - current_wd) % 7
            if days_ahead == 0:
                days_ahead = 0  # 如果今天就是目标星期，返回今天
            return today + timedelta(days=days_ahead)

    return None


def _parse_time_of_day(text: str) -> tuple[int, int] | None:
    """解析时间部分，返回 (hour, minute)。"""

    # 先尝试匹配标准时间格式 HH:MM
    m = re.search(r"(\d{1,2}):(\d{2})", text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        # 处理上午/下午前缀
        if ("下午" in text or "晚上" in text or "晚" in text or "傍晚" in text) and h < 12:
            h += 12
        return (h, mi)

    # 中文时间：X点Y分 / X点半 / X点
    pattern = (
        r"(?:凌晨|早上|早晨|上午|中午|下午|傍晚|晚上|晚)?"
        r"\s*"
        r"(\d{1,2}|[一二三四五六七八九十两]+)"
        r"\s*[点时]"
        r"(?:\s*(\d{1,2}|[一二三四五六七八九十]+)\s*分?)?"
        r"(半)?"
    )
    m = re.search(pattern, text)
    if m:
        hour = cn_to_int(m.group(1))
        if hour is None:
            return None

        minute = 0
        if m.group(3):  # "半"
            minute = 30
        elif m.group(2):
            minute = cn_to_int(m.group(2)) or 0

        # 判断上午/下午
        period_match = re.search(r"(凌晨|早上|早晨|上午|中午|下午|傍晚|晚上|晚)", text)
        if period_match:
            period = period_match.group(1)
            if period in ("下午", "傍晚", "晚上", "晚") and hour < 12:
                hour += 12
            elif period == "中午" and hour == 12:
                pass
            elif period in ("凌晨",) and hour == 12:
                hour = 0

        return (hour, minute)

    return None


def parse_time(text: str, base: datetime | None = None) -> datetime | None:
    """
    解析中文自然语言时间表达式，返回 datetime 对象。

    Args:
        text: 时间文本，如 "明天下午三点"、"2026-02-20 18:00"、"3天后"
        base: 基准时间，默认为当前时间

    Returns:
        解析得到的 datetime 对象，解析失败返回 None
    """
    if not text or not text.strip():
        return None

    text = text.strip()
    if base is None:
        base = datetime.now()

    # 1. 尝试标准格式 YYYY-MM-DD HH:MM(:SS)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    # 2. 尝试带中文的标准格式 YYYY年MM月DD日
    m = re.match(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", text)
    if m:
        date_part = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        # 尝试解析后面的时间
        remaining = text[m.end():]
        time_part = _parse_time_of_day(remaining)
        if time_part:
            return date_part.replace(hour=time_part[0], minute=time_part[1])
        return date_part

    # 3. 尝试 MM月DD日 / MM-DD 格式
    m = re.match(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?", text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        date_part = base.replace(month=month, day=day, hour=0, minute=0, second=0, microsecond=0)
        if date_part < base:
            date_part = date_part.replace(year=date_part.year + 1)
        remaining = text[m.end():]
        time_part = _parse_time_of_day(remaining)
        if time_part:
            return date_part.replace(hour=time_part[0], minute=time_part[1])
        return date_part

    # 4. 解析相对日期 + 可选时间
    date_result = None
    time_result = None

    # 尝试提取日期部分
    date_patterns = [
        r"(大后天)", r"(后天)", r"(明天|明日)", r"(今天|今日)",
        r"(\d+|[一二三四五六七八九十百]+)\s*[天日]后",
        r"(下周[一二三四五六日天])",
        r"((?:这|本)?周[一二三四五六日天])",
    ]
    for pat in date_patterns:
        m = re.search(pat, text)
        if m:
            date_result = _parse_relative_date(m.group(0), base)
            break

    # 尝试提取时间部分
    time_result = _parse_time_of_day(text)

    # 组合日期和时间
    if date_result and time_result:
        return date_result.replace(hour=time_result[0], minute=time_result[1])
    elif date_result:
        return date_result
    elif time_result:
        # 没有日期，只有时间：认为是今天或明天
        result = base.replace(
            hour=time_result[0], minute=time_result[1], second=0, microsecond=0
        )
        if result <= base:
            result += timedelta(days=1)  # 时间已过就是明天
        return result

    # 5. N小时后 / N分钟后
    m = re.search(r"(\d+|[一二三四五六七八九十]+)\s*(?:个)?小时后", text)
    if m:
        n = cn_to_int(m.group(1))
        if n:
            return base + timedelta(hours=n)

    m = re.search(r"(\d+|[一二三四五六七八九十]+)\s*分钟后", text)
    if m:
        n = cn_to_int(m.group(1))
        if n:
            return base + timedelta(minutes=n)

    return None


def format_time(dt: datetime | None) -> str:
    """格式化 datetime 为易读字符串。"""
    if dt is None:
        return "未设置"
    return dt.strftime("%Y-%m-%d %H:%M")


def format_relative(dt: datetime | None) -> str:
    """格式化为相对时间描述，如 "2小时后"、"已逾期3天"。"""
    if dt is None:
        return ""
    now = datetime.now()
    diff = dt - now

    if diff.total_seconds() <= 0:
        # 已逾期
        past = abs(diff)
        days = past.days
        hours = past.seconds // 3600
        if days > 0:
            return f"已逾期{days}天"
        elif hours > 0:
            return f"已逾期{hours}小时"
        else:
            return "刚刚逾期"
    else:
        days = diff.days
        hours = diff.seconds // 3600
        if days > 0:
            return f"{days}天后到期"
        elif hours > 0:
            return f"{hours}小时后到期"
        else:
            minutes = diff.seconds // 60
            return f"{minutes}分钟后到期"
