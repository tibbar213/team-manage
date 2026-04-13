"""
数据库自动迁移模块
在应用启动时自动检测并执行必要的数据库迁移
"""
import logging
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def get_db_path():
    """获取数据库文件路径"""
    from app.config import settings
    db_file = settings.database_url.split("///")[-1]
    return Path(db_file)


def column_exists(cursor, table_name, column_name):
    """检查表中是否存在指定列"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns


def repair_warranty_timestamps(cursor) -> int:
    """
    用首次兑换时间回填质保起点，避免重复质保兑换重置质保期。
    """
    cursor.execute(
        """
        SELECT
            rc.id,
            rc.warranty_days,
            MIN(rr.redeemed_at) AS first_redeemed_at
        FROM redemption_codes rc
        JOIN redemption_records rr ON rr.code = rc.code
        WHERE rc.has_warranty = 1
        GROUP BY rc.id, rc.warranty_days
        """
    )

    repaired = 0
    for code_id, warranty_days, first_redeemed_at in cursor.fetchall():
        if not first_redeemed_at:
            continue

        first_redeemed_dt = datetime.fromisoformat(str(first_redeemed_at))
        warranty_expires_at = first_redeemed_dt + timedelta(days=warranty_days or 30)

        cursor.execute(
            """
            UPDATE redemption_codes
            SET used_at = ?, warranty_expires_at = ?
            WHERE id = ?
            """,
            (
                first_redeemed_dt.isoformat(sep=" "),
                warranty_expires_at.isoformat(sep=" "),
                code_id,
            ),
        )
        repaired += 1

    return repaired


def run_auto_migration():
    """
    自动运行数据库迁移
    检测缺失的列并自动添加
    """
    db_path = get_db_path()
    
    if not db_path.exists():
        logger.info("数据库文件不存在，跳过迁移")
        return
    
    logger.info("开始检查数据库迁移...")
    
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        migrations_applied = []
        
        # 检查并添加质保相关字段
        if not column_exists(cursor, "redemption_codes", "has_warranty"):
            logger.info("添加 redemption_codes.has_warranty 字段")
            cursor.execute("""
                ALTER TABLE redemption_codes 
                ADD COLUMN has_warranty BOOLEAN DEFAULT 0
            """)
            migrations_applied.append("redemption_codes.has_warranty")
        
        if not column_exists(cursor, "redemption_codes", "warranty_expires_at"):
            logger.info("添加 redemption_codes.warranty_expires_at 字段")
            cursor.execute("""
                ALTER TABLE redemption_codes 
                ADD COLUMN warranty_expires_at DATETIME
            """)
            migrations_applied.append("redemption_codes.warranty_expires_at")
        
        if not column_exists(cursor, "redemption_codes", "warranty_days"):
            logger.info("添加 redemption_codes.warranty_days 字段")
            cursor.execute("""
                ALTER TABLE redemption_codes 
                ADD COLUMN warranty_days INTEGER DEFAULT 30
            """)
            migrations_applied.append("redemption_codes.warranty_days")
        
        if not column_exists(cursor, "redemption_records", "is_warranty_redemption"):
            logger.info("添加 redemption_records.is_warranty_redemption 字段")
            cursor.execute("""
                ALTER TABLE redemption_records 
                ADD COLUMN is_warranty_redemption BOOLEAN DEFAULT 0
            """)
            migrations_applied.append("redemption_records.is_warranty_redemption")

        # 检查并添加 Token 刷新相关字段
        if not column_exists(cursor, "teams", "refresh_token_encrypted"):
            logger.info("添加 teams.refresh_token_encrypted 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN refresh_token_encrypted TEXT")
            migrations_applied.append("teams.refresh_token_encrypted")

        if not column_exists(cursor, "teams", "session_token_encrypted"):
            logger.info("添加 teams.session_token_encrypted 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN session_token_encrypted TEXT")
            migrations_applied.append("teams.session_token_encrypted")

        if not column_exists(cursor, "teams", "client_id"):
            logger.info("添加 teams.client_id 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN client_id VARCHAR(100)")
            migrations_applied.append("teams.client_id")

        if not column_exists(cursor, "teams", "error_count"):
            logger.info("添加 teams.error_count 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN error_count INTEGER DEFAULT 0")
            migrations_applied.append("teams.error_count")

        if not column_exists(cursor, "teams", "account_role"):
            logger.info("添加 teams.account_role 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN account_role VARCHAR(50)")
            migrations_applied.append("teams.account_role")

        if not column_exists(cursor, "teams", "device_code_auth_enabled"):
            logger.info("添加 teams.device_code_auth_enabled 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN device_code_auth_enabled BOOLEAN DEFAULT 0")
            migrations_applied.append("teams.device_code_auth_enabled")

        repaired_codes = repair_warranty_timestamps(cursor)
        if repaired_codes:
            migrations_applied.append(f"repair.warranty_timestamps({repaired_codes})")
        
        # 提交更改
        conn.commit()
        
        if migrations_applied:
            logger.info(f"数据库迁移完成，应用了 {len(migrations_applied)} 个迁移: {', '.join(migrations_applied)}")
        else:
            logger.info("数据库已是最新版本，无需迁移")
        
        conn.close()
        
    except Exception as e:
        logger.error(f"数据库迁移失败: {e}")
        raise


if __name__ == "__main__":
    # 允许直接运行此脚本进行迁移
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    run_auto_migration()
    print("迁移完成")
