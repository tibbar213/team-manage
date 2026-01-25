from datetime import datetime
import pytz
from app.config import settings

def get_now() -> datetime:
    """获取当前时区的当前时间 (返回 naive datetime 以保持数据库兼容性)"""
    tz = pytz.timezone(settings.timezone)
    return datetime.now(tz).replace(tzinfo=None)
