import sys
import os
from datetime import datetime

# 将项目根目录添加到 python 路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.utils.time_utils import get_now
from app.config import settings

def test_timezone():
    print(f"配置时区: {settings.timezone}")
    
    now = get_now()
    # 系统当前的 UTC 时间
    utc_now = datetime.utcnow()
    
    print(f"当前时间 (CST 预期): {now}")
    print(f"当前时间 (UTC 预期): {utc_now}")
    
    # 计算差异（小时）
    diff = (now - utc_now).total_seconds() / 3600
    print(f"小时差: {diff:.2f}")
    
    if 7.5 < diff < 8.5:
        print("✅ 验证成功: get_now() 返回的是 UTC+8 (北京时间)")
    else:
        print("❌ 验证失败: 时间差不是 8 小时，请检查时区配置")

if __name__ == "__main__":
    test_timezone()
