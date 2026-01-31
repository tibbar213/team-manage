"""
兑换流程服务
协调用户兑换流程，包括验证、Team选择、邀请发送、事务处理和并发控制
"""
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Team, RedemptionCode, RedemptionRecord
from app.services.redemption import RedemptionService
from app.services.warranty import WarrantyService
from app.services.team import TeamService
from app.services.chatgpt import ChatGPTService
from app.services.encryption import encryption_service
from app.utils.time_utils import get_now

logger = logging.getLogger(__name__)


class RedeemFlowService:
    """兑换流程服务类"""

    def __init__(self):
        """初始化兑换流程服务"""
        from app.services.chatgpt import chatgpt_service
        self.redemption_service = RedemptionService()
        self.warranty_service = WarrantyService()
        self.team_service = TeamService()
        self.chatgpt_service = chatgpt_service

    async def verify_code_and_get_teams(
        self,
        code: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        验证兑换码并获取可用 Team 列表

        Args:
            code: 兑换码
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, valid, reason, teams, error
        """
        try:
            # 1. 验证兑换码
            # 使用事务以确保状态更新(如标记为已过期)被持久化
            async with db_session.begin():
                validate_result = await self.redemption_service.validate_code(code, db_session)
            
            if not validate_result["success"]:
                return {
                    "success": False,
                    "valid": False,
                    "reason": None,
                    "teams": [],
                    "error": validate_result["error"]
                }
            
            if not validate_result["valid"]:
                return {
                    "success": True,
                    "valid": False,
                    "reason": validate_result["reason"],
                    "teams": [],
                    "error": None
                }

            # 2. 获取可用 Team 列表
            teams_result = await self.team_service.get_available_teams(db_session)

            if not teams_result["success"]:
                return {
                    "success": False,
                    "valid": True,
                    "reason": None,
                    "teams": [],
                    "error": teams_result["error"]
                }

            logger.info(f"验证兑换码成功: {code}, 可用 Team 数量: {len(teams_result['teams'])}")

            return {
                "success": True,
                "valid": True,
                "reason": None,
                "teams": teams_result["teams"],
                "error": None
            }

        except Exception as e:
            logger.error(f"验证兑换码并获取 Team 列表失败: {e}")
            return {
                "success": False,
                "valid": False,
                "reason": None,
                "teams": [],
                "error": f"验证失败: {str(e)}"
            }

    async def select_team_auto(
        self,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        自动选择 Team (选择过期时间最早的)

        Args:
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, team_id, error
        """
        try:
            # 查询可用 Team，按过期时间升序排序
            stmt = select(Team).where(
                Team.status == "active",
                Team.current_members < Team.max_members
            ).order_by(Team.expires_at.asc()).limit(1)

            result = await db_session.execute(stmt)
            team = result.scalar_one_or_none()

            if not team:
                return {
                    "success": False,
                    "team_id": None,
                    "error": "没有可用的 Team"
                }

            logger.info(f"自动选择 Team: {team.id} (过期时间: {team.expires_at})")

            return {
                "success": True,
                "team_id": team.id,
                "error": None
            }

        except Exception as e:
            logger.error(f"自动选择 Team 失败: {e}")
            return {
                "success": False,
                "team_id": None,
                "error": f"自动选择 Team 失败: {str(e)}"
            }

    async def redeem_and_join_team(
        self,
        email: str,
        code: str,
        team_id: Optional[int],
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        完整的兑换流程 (带事务和并发控制)
        优化版本: 将网络请求移出写事务,避免 SQLite 锁定
        """
        max_retries = 3
        current_target_team_id = team_id
        last_error = "未知错误"

        for attempt in range(max_retries):
            # 彻底确保会话处于干净状态，防止 "A transaction is already begun" 错误
            # SELECT 操作会隐式开启事务，导致后续 begin() 报错
            if db_session.in_transaction():
                await db_session.rollback()
                
            # 确保每次尝试都从数据库读取最新数据, 避免 identity map 缓存了上一次尝试修改后的状态
            db_session.expire_all()
            
            logger.info(f"正在尝试兑换 (第 {attempt + 1}/{max_retries} 次尝试): email={email}, code={code}")
            team_id_final = None
            try:
                # --- 阶段 1: 验证并占位 (短事务) ---
                async with db_session.begin():
                    # 1. 验证兑换码 (在事务内验证确保原子性)
                    validate_result = await self.redemption_service.validate_code(code, db_session)
                    if not validate_result["success"]:
                        return {"success": False, "error": validate_result["error"]}
                    if not validate_result["valid"]:
                        return {"success": False, "error": validate_result["reason"]}

                    # 再次验证并锁定
                    stmt = select(RedemptionCode).where(RedemptionCode.code == code)
                    result = await db_session.execute(stmt)
                    redemption_code = result.scalar_one_or_none()
                    
                    if not redemption_code:
                        return {"success": False, "error": "兑换码记录丢失"}

                    # 检查状态是否依然有效 (可能在循环间隙被别人捷足先登)
                    if redemption_code.status not in ["unused", "warranty_active"]:
                        return {"success": False, "error": "兑换码已被使用"}

                    # 2. 选择 Team
                    if current_target_team_id is None:
                        select_result = await self.select_team_auto(db_session)
                        if not select_result["success"]:
                            return {"success": False, "error": select_result["error"]}
                        team_id_final = select_result["team_id"]
                    else:
                        team_id_final = current_target_team_id

                    # 3. 检查 Team
                    stmt = select(Team).where(Team.id == team_id_final)
                    result = await db_session.execute(stmt)
                    team = result.scalar_one_or_none()

                    if not team:
                        if current_target_team_id is None and attempt < max_retries - 1:
                            logger.warning(f"选择的 Team {team_id_final} 消失了, 尝试下一次循环")
                            continue
                        return {"success": False, "error": f"Team {team_id_final} 不存在"}
                    
                    if team.current_members >= team.max_members:
                        if current_target_team_id is None and attempt < max_retries - 1:
                            logger.warning(f"选择的 Team {team_id_final} 已满, 尝试下一次循环")
                            continue 
                        return {"success": False, "error": "Team 已满，请选择其他 Team"}
                    
                    if team.status != "active":
                        if current_target_team_id is None and attempt < max_retries - 1:
                            logger.warning(f"选择的 Team {team_id_final} 状态异常 ({team.status}), 尝试下一次循环")
                            continue
                        return {"success": False, "error": f"Team 状态异常: {team.status}"}

                    # 特殊处理质保码逻辑
                    is_warranty_code = redemption_code.has_warranty
                    is_first_use = redemption_code.status == "unused"
                    
                    if not is_first_use:
                        # 如果不是首次使用，检查是否为质保码且可重复使用
                        if is_warranty_code:
                            warranty_check = await self.warranty_service.validate_warranty_reuse(
                                db_session, code, email
                            )
                            if not warranty_check["success"] or not warranty_check["can_reuse"]:
                                return {"success": False, "error": warranty_check.get("reason", "兑换码质保验证未通过")}
                        else:
                            return {"success": False, "error": "兑换码已被占用"}

                    # 4. 更新状态执行占位
                    if is_warranty_code:
                        redemption_code.status = "warranty_active"
                        if is_first_use:
                            warranty_days = redemption_code.warranty_days or 30
                            redemption_code.warranty_expires_at = get_now() + timedelta(days=warranty_days)
                    else:
                        redemption_code.status = "used"
                    
                    redemption_code.used_by_email = email
                    redemption_code.used_team_id = team_id_final
                    redemption_code.used_at = get_now()

                    # 增加 Team 成员数占位
                    team.current_members += 1
                    if team.current_members >= team.max_members:
                        team.status = "full"
                    
                    # 记录信息供 Phase 2 使用
                    final_team_account_id = team.account_id
                    final_team_name = team.team_name
                    final_team_expires_at = team.expires_at
                    final_access_token_encrypted = team.access_token_encrypted
                    final_is_warranty = is_warranty_code
                    
                    # 事务 commit
                
                # --- 阶段 2: 网络请求 ---
                try:
                    access_token = encryption_service.decrypt_token(final_access_token_encrypted)
                except Exception as e:
                    logger.error(f"解密 Token 失败: {e}")
                    await self._rollback_redemption(db_session, code, team_id_final)
                    return {"success": False, "error": f"系统解密失败: {str(e)}"}

                invite_result = await self.chatgpt_service.send_invite(
                    access_token, final_team_account_id, email, db_session
                )

                # --- 阶段 3: 最终化 ---
                if invite_result["success"]:
                    # 阶段 2 的网络请求中可能涉及查询设置(代理等)，会隐式开启事务
                    if db_session.in_transaction():
                        await db_session.rollback()
                        
                    async with db_session.begin():
                        redemption_record = RedemptionRecord(
                            email=email,
                            code=code,
                            team_id=team_id_final,
                            account_id=final_team_account_id,
                            is_warranty_redemption=final_is_warranty
                        )
                        db_session.add(redemption_record)
                    
                    logger.info(f"兑换成功: {email} 加入 Team {team_id_final}")
                    return {
                        "success": True,
                        "message": f"成功加入 Team: {final_team_name}",
                        "team_info": {
                            "team_id": team_id_final,
                            "team_name": final_team_name,
                            "account_id": final_team_account_id,
                            "expires_at": final_team_expires_at.isoformat() if final_team_expires_at else None
                        }
                    }
                else:
                    logger.warning(f"API 邀请失败 (尝试 {attempt + 1}): {invite_result['error']}")
                    await self._rollback_redemption(db_session, code, team_id_final)
                    
                    error_msg = invite_result.get("error", "未知错误")
                    
                    # 致命错误处理
                    stmt = select(Team).where(Team.id == team_id_final)
                    res = await db_session.execute(stmt)
                    target_team = res.scalar_one_or_none()
                    
                    is_fatal = False
                    if target_team and await self.team_service._handle_api_error(invite_result, target_team, db_session):
                        is_fatal = True
                        if invite_result.get("error_code") == "account_deactivated":
                            error_msg = "Team 账号被封禁"
                        elif invite_result.get("error_code") == "token_invalidated":
                            error_msg = "Team 账号已封禁/失效"
                    
                    last_error = error_msg
                    if is_fatal and attempt < max_retries - 1:
                        logger.info(f"致命错误，尝试更换 Team 重试...")
                        current_target_team_id = None
                        continue
                    else:
                        return {"success": False, "error": f"加入失败: {error_msg}"}

            except Exception as e:
                logger.error(f"兑换尝试异常 (第 {attempt + 1} 次): {e}")
                if team_id_final:
                    try:
                        await self._rollback_redemption(db_session, code, team_id_final)
                    except:
                        pass
                if attempt < max_retries - 1:
                    continue
                return {"success": False, "error": f"兑换系统异常: {str(e)}"}

    async def _rollback_redemption(
        self,
        db_session: AsyncSession,
        code: str,
        team_id: int
    ):
        """回退兑换占位"""
        try:
            # 确保会话干净，防止在异常处理路径中再次触发事务冲突
            if db_session.in_transaction():
                await db_session.rollback()
                
            async with db_session.begin():
                # 回退兑换码状态
                stmt = select(RedemptionCode).where(RedemptionCode.code == code)
                result = await db_session.execute(stmt)
                redemption_code = result.scalar_one_or_none()
                if redemption_code:
                    # 质保码回退到 warranty_active 或 unused
                    if redemption_code.has_warranty:
                        # 检查是否有其他成功的兑换记录
                        stmt = select(RedemptionRecord).where(
                            RedemptionRecord.code == code
                        ).order_by(RedemptionRecord.redeemed_at.desc())
                        result = await db_session.execute(stmt)
                        other_record = result.scalars().first()
                        
                        if other_record:
                            # 有其他记录，恢复为最后一次成功的状态
                            redemption_code.status = "warranty_active"
                            redemption_code.used_by_email = other_record.email
                            redemption_code.used_team_id = other_record.team_id
                            redemption_code.used_at = other_record.redeemed_at
                        else:
                            # 没有其他成功记录，彻底回退到未使用
                            redemption_code.status = "unused"
                            redemption_code.warranty_expires_at = None
                            redemption_code.used_by_email = None
                            redemption_code.used_team_id = None
                            redemption_code.used_at = None
                    else:
                        # 普通码彻底回退到 unused
                        redemption_code.status = "unused"
                        redemption_code.used_by_email = None
                        redemption_code.used_team_id = None
                        redemption_code.used_at = None

                # 回退 Team 计数
                stmt = select(Team).where(Team.id == team_id)
                result = await db_session.execute(stmt)
                team = result.scalar_one_or_none()
                if team:
                    if team.current_members > 0:
                        team.current_members -= 1
                    if team.status == "full" and team.current_members < team.max_members:
                        team.status = "active"
            logger.info(f"已回退兑换占位: code={code}, team_id={team_id}")
        except Exception as e:
            logger.error(f"回退兑换占位失败: {e}")


# 创建全局实例
redeem_flow_service = RedeemFlowService()
