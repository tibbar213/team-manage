"""
兑换码管理服务
用于管理兑换码的生成、验证、使用和查询
"""
import logging
import secrets
import string
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from sqlalchemy import select, update, delete, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import RedemptionCode, RedemptionRecord, Team
from app.utils.time_utils import get_now

logger = logging.getLogger(__name__)


class RedemptionService:
    """兑换码管理服务类"""

    def __init__(self):
        """初始化兑换码管理服务"""
        pass

    def _generate_random_code(self, length: int = 16) -> str:
        """
        生成随机兑换码

        Args:
            length: 兑换码长度

        Returns:
            随机兑换码字符串
        """
        # 使用大写字母和数字,排除容易混淆的字符 (0, O, I, 1)
        alphabet = string.ascii_uppercase + string.digits
        alphabet = alphabet.replace('0', '').replace('O', '').replace('I', '').replace('1', '')

        # 生成随机码
        code = ''.join(secrets.choice(alphabet) for _ in range(length))

        # 格式化为 XXXX-XXXX-XXXX-XXXX
        if length == 16:
            code = f"{code[0:4]}-{code[4:8]}-{code[8:12]}-{code[12:16]}"

        return code

    async def generate_code_single(
        self,
        db_session: AsyncSession,
        code: Optional[str] = None,
        expires_days: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        生成单个兑换码

        Args:
            db_session: 数据库会话
            code: 自定义兑换码 (可选,如果不提供则自动生成)
            expires_days: 有效期天数 (可选,如果不提供则永久有效)

        Returns:
            结果字典,包含 success, code, message, error
        """
        try:
            # 1. 生成或使用自定义兑换码
            if not code:
                # 生成随机码,确保唯一性
                max_attempts = 10
                for _ in range(max_attempts):
                    code = self._generate_random_code()

                    # 检查是否已存在
                    stmt = select(RedemptionCode).where(RedemptionCode.code == code)
                    result = await db_session.execute(stmt)
                    existing = result.scalar_one_or_none()

                    if not existing:
                        break
                else:
                    return {
                        "success": False,
                        "code": None,
                        "message": None,
                        "error": "生成唯一兑换码失败,请重试"
                    }
            else:
                # 检查自定义兑换码是否已存在
                stmt = select(RedemptionCode).where(RedemptionCode.code == code)
                result = await db_session.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    return {
                        "success": False,
                        "code": None,
                        "message": None,
                        "error": f"兑换码 {code} 已存在"
                    }

            # 2. 计算过期时间
            expires_at = None
            if expires_days:
                expires_at = get_now() + timedelta(days=expires_days)

            # 3. 创建兑换码记录
            redemption_code = RedemptionCode(
                code=code,
                status="unused",
                expires_at=expires_at
            )

            db_session.add(redemption_code)
            await db_session.commit()

            logger.info(f"生成兑换码成功: {code}")

            return {
                "success": True,
                "code": code,
                "message": f"兑换码生成成功: {code}",
                "error": None
            }

        except Exception as e:
            await db_session.rollback()
            logger.error(f"生成兑换码失败: {e}")
            return {
                "success": False,
                "code": None,
                "message": None,
                "error": f"生成兑换码失败: {str(e)}"
            }

    async def generate_code_batch(
        self,
        db_session: AsyncSession,
        count: int,
        expires_days: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        批量生成兑换码

        Args:
            db_session: 数据库会话
            count: 生成数量
            expires_days: 有效期天数 (可选)

        Returns:
            结果字典,包含 success, codes, total, message, error
        """
        try:
            if count <= 0 or count > 1000:
                return {
                    "success": False,
                    "codes": [],
                    "total": 0,
                    "message": None,
                    "error": "生成数量必须在 1-1000 之间"
                }

            # 计算过期时间
            expires_at = None
            if expires_days:
                expires_at = get_now() + timedelta(days=expires_days)

            # 批量生成兑换码
            codes = []
            for i in range(count):
                # 生成唯一兑换码
                max_attempts = 10
                for _ in range(max_attempts):
                    code = self._generate_random_code()

                    # 检查是否已存在 (包括本次批量生成的)
                    if code not in codes:
                        stmt = select(RedemptionCode).where(RedemptionCode.code == code)
                        result = await db_session.execute(stmt)
                        existing = result.scalar_one_or_none()

                        if not existing:
                            codes.append(code)
                            break
                else:
                    logger.warning(f"生成第 {i+1} 个兑换码失败")
                    continue

            # 批量插入数据库
            for code in codes:
                redemption_code = RedemptionCode(
                    code=code,
                    status="unused",
                    expires_at=expires_at
                )
                db_session.add(redemption_code)

            await db_session.commit()

            logger.info(f"批量生成兑换码成功: {len(codes)} 个")

            return {
                "success": True,
                "codes": codes,
                "total": len(codes),
                "message": f"成功生成 {len(codes)} 个兑换码",
                "error": None
            }

        except Exception as e:
            await db_session.rollback()
            logger.error(f"批量生成兑换码失败: {e}")
            return {
                "success": False,
                "codes": [],
                "total": 0,
                "message": None,
                "error": f"批量生成兑换码失败: {str(e)}"
            }

    async def validate_code(
        self,
        code: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        验证兑换码

        Args:
            code: 兑换码
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, valid, reason, redemption_code, error
        """
        try:
            # 1. 查询兑换码
            stmt = select(RedemptionCode).where(RedemptionCode.code == code)
            result = await db_session.execute(stmt)
            redemption_code = result.scalar_one_or_none()

            if not redemption_code:
                return {
                    "success": True,
                    "valid": False,
                    "reason": "兑换码不存在",
                    "redemption_code": None,
                    "error": None
                }

            # 2. 检查状态
            if redemption_code.status != "unused":
                reason = "兑换码已被使用" if redemption_code.status == "used" else f"兑换码已{redemption_code.status}"
                return {
                    "success": True,
                    "valid": False,
                    "reason": reason,
                    "redemption_code": None,
                    "error": None
                }

            # 3. 检查是否过期
            if redemption_code.expires_at:
                if redemption_code.expires_at < get_now():
                    # 更新状态为 expired
                    redemption_code.status = "expired"
                    await db_session.commit()

                    return {
                        "success": True,
                        "valid": False,
                        "reason": "兑换码已过期",
                        "redemption_code": None,
                        "error": None
                    }

            # 4. 验证通过
            return {
                "success": True,
                "valid": True,
                "reason": "兑换码有效",
                "redemption_code": {
                    "id": redemption_code.id,
                    "code": redemption_code.code,
                    "status": redemption_code.status,
                    "expires_at": redemption_code.expires_at.isoformat() if redemption_code.expires_at else None,
                    "created_at": redemption_code.created_at.isoformat() if redemption_code.created_at else None
                },
                "error": None
            }

        except Exception as e:
            logger.error(f"验证兑换码失败: {e}")
            return {
                "success": False,
                "valid": False,
                "reason": None,
                "redemption_code": None,
                "error": f"验证兑换码失败: {str(e)}"
            }

    async def use_code(
        self,
        code: str,
        email: str,
        team_id: int,
        account_id: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        使用兑换码

        Args:
            code: 兑换码
            email: 使用者邮箱
            team_id: Team ID
            account_id: Account ID
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, message, error
        """
        try:
            # 1. 验证兑换码
            validate_result = await self.validate_code(code, db_session)

            if not validate_result["success"]:
                return {
                    "success": False,
                    "message": None,
                    "error": validate_result["error"]
                }

            if not validate_result["valid"]:
                return {
                    "success": False,
                    "message": None,
                    "error": validate_result["reason"]
                }

            # 2. 更新兑换码状态
            stmt = select(RedemptionCode).where(RedemptionCode.code == code)
            result = await db_session.execute(stmt)
            redemption_code = result.scalar_one_or_none()

            redemption_code.status = "used"
            redemption_code.used_by_email = email
            redemption_code.used_team_id = team_id
            redemption_code.used_at = get_now()

            # 3. 创建使用记录
            redemption_record = RedemptionRecord(
                email=email,
                code=code,
                team_id=team_id,
                account_id=account_id
            )

            db_session.add(redemption_record)
            await db_session.commit()

            logger.info(f"使用兑换码成功: {code} -> {email}")

            return {
                "success": True,
                "message": "兑换码使用成功",
                "error": None
            }

        except Exception as e:
            await db_session.rollback()
            logger.error(f"使用兑换码失败: {e}")
            return {
                "success": False,
                "message": None,
                "error": f"使用兑换码失败: {str(e)}"
            }

    async def get_all_codes(
        self,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        获取所有兑换码

        Args:
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, codes, total, error
        """
        try:
            stmt = select(RedemptionCode).order_by(RedemptionCode.created_at.desc())
            result = await db_session.execute(stmt)
            codes = result.scalars().all()

            # 构建返回数据
            code_list = []
            for code in codes:
                code_list.append({
                    "id": code.id,
                    "code": code.code,
                    "status": code.status,
                    "created_at": code.created_at.isoformat() if code.created_at else None,
                    "expires_at": code.expires_at.isoformat() if code.expires_at else None,
                    "used_by_email": code.used_by_email,
                    "used_team_id": code.used_team_id,
                    "used_at": code.used_at.isoformat() if code.used_at else None
                })

            logger.info(f"获取所有兑换码成功: 共 {len(code_list)} 个")

            return {
                "success": True,
                "codes": code_list,
                "total": len(code_list),
                "error": None
            }

        except Exception as e:
            logger.error(f"获取所有兑换码失败: {e}")
            return {
                "success": False,
                "codes": [],
                "total": 0,
                "error": f"获取所有兑换码失败: {str(e)}"
            }

    async def get_code_by_code(
        self,
        code: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        根据兑换码查询

        Args:
            code: 兑换码
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, code_info, error
        """
        try:
            stmt = select(RedemptionCode).where(RedemptionCode.code == code)
            result = await db_session.execute(stmt)
            redemption_code = result.scalar_one_or_none()

            if not redemption_code:
                return {
                    "success": False,
                    "code_info": None,
                    "error": f"兑换码 {code} 不存在"
                }

            code_info = {
                "id": redemption_code.id,
                "code": redemption_code.code,
                "status": redemption_code.status,
                "created_at": redemption_code.created_at.isoformat() if redemption_code.created_at else None,
                "expires_at": redemption_code.expires_at.isoformat() if redemption_code.expires_at else None,
                "used_by_email": redemption_code.used_by_email,
                "used_team_id": redemption_code.used_team_id,
                "used_at": redemption_code.used_at.isoformat() if redemption_code.used_at else None
            }

            return {
                "success": True,
                "code_info": code_info,
                "error": None
            }

        except Exception as e:
            logger.error(f"查询兑换码失败: {e}")
            return {
                "success": False,
                "code_info": None,
                "error": f"查询兑换码失败: {str(e)}"
            }

    async def get_unused_codes(
        self,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        获取未使用的兑换码

        Args:
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, codes, total, error
        """
        try:
            stmt = select(RedemptionCode).where(
                RedemptionCode.status == "unused"
            ).order_by(RedemptionCode.created_at.desc())

            result = await db_session.execute(stmt)
            codes = result.scalars().all()

            # 构建返回数据
            code_list = []
            for code in codes:
                code_list.append({
                    "id": code.id,
                    "code": code.code,
                    "status": code.status,
                    "created_at": code.created_at.isoformat() if code.created_at else None,
                    "expires_at": code.expires_at.isoformat() if code.expires_at else None
                })

            return {
                "success": True,
                "codes": code_list,
                "total": len(code_list),
                "error": None
            }

        except Exception as e:
            logger.error(f"获取未使用兑换码失败: {e}")
            return {
                "success": False,
                "codes": [],
                "total": 0,
                "error": f"获取未使用兑换码失败: {str(e)}"
            }

    async def get_all_records(
        self,
        db_session: AsyncSession,
        email: Optional[str] = None,
        code: Optional[str] = None,
        team_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        获取所有兑换记录 (支持筛选)

        Args:
            db_session: 数据库会话
            email: 邮箱模糊搜索
            code: 兑换码模糊搜索
            team_id: Team ID 筛选

        Returns:
            结果字典,包含 success, records, total, error
        """
        try:
            stmt = select(RedemptionRecord)
            
            # 添加筛选条件
            filters = []
            if email:
                filters.append(RedemptionRecord.email.ilike(f"%{email}%"))
            if code:
                filters.append(RedemptionRecord.code.ilike(f"%{code}%"))
            if team_id:
                filters.append(RedemptionRecord.team_id == team_id)
                
            if filters:
                stmt = stmt.where(and_(*filters))
                
            stmt = stmt.order_by(RedemptionRecord.redeemed_at.desc())
            
            result = await db_session.execute(stmt)
            records = result.scalars().all()

            # 构建返回数据
            record_list = []
            for record in records:
                record_list.append({
                    "id": record.id,
                    "email": record.email,
                    "code": record.code,
                    "team_id": record.team_id,
                    "account_id": record.account_id,
                    "redeemed_at": record.redeemed_at.isoformat() if record.redeemed_at else None
                })

            logger.info(f"获取所有兑换记录成功: 共 {len(record_list)} 条")

            return {
                "success": True,
                "records": record_list,
                "total": len(record_list),
                "error": None
            }

        except Exception as e:
            logger.error(f"获取所有兑换记录失败: {e}")
            return {
                "success": False,
                "records": [],
                "total": 0,
                "error": f"获取所有兑换记录失败: {str(e)}"
            }

    async def delete_code(
        self,
        code: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        删除兑换码

        Args:
            code: 兑换码
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, message, error
        """
        try:
            # 查询兑换码
            stmt = select(RedemptionCode).where(RedemptionCode.code == code)
            result = await db_session.execute(stmt)
            redemption_code = result.scalar_one_or_none()

            if not redemption_code:
                return {
                    "success": False,
                    "message": None,
                    "error": f"兑换码 {code} 不存在"
                }

            # 删除兑换码
            await db_session.delete(redemption_code)
            await db_session.commit()

            logger.info(f"删除兑换码成功: {code}")

            return {
                "success": True,
                "message": f"兑换码 {code} 已删除",
                "error": None
            }

        except Exception as e:
            await db_session.rollback()
            logger.error(f"删除兑换码失败: {e}")
            return {
                "success": False,
                "message": None,
                "error": f"删除兑换码失败: {str(e)}"
            }


# 创建全局兑换码服务实例
redemption_service = RedemptionService()
