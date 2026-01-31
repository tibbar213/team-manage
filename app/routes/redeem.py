"""
兑换路由
处理用户兑换码验证和加入 Team 的请求
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.redeem_flow import redeem_flow_service

logger = logging.getLogger(__name__)

# 创建路由器
router = APIRouter(
    prefix="/redeem",
    tags=["redeem"]
)


# 请求模型
class VerifyCodeRequest(BaseModel):
    """验证兑换码请求"""
    code: str = Field(..., description="兑换码", min_length=1)


class RedeemRequest(BaseModel):
    """兑换请求"""
    email: EmailStr = Field(..., description="用户邮箱")
    code: str = Field(..., description="兑换码", min_length=1)
    team_id: Optional[int] = Field(None, description="Team ID (可选，不提供则自动选择)")


# 响应模型
class TeamInfo(BaseModel):
    """Team 信息"""
    id: int
    team_name: str
    current_members: int
    max_members: int
    expires_at: Optional[str]
    subscription_plan: Optional[str]


class VerifyCodeResponse(BaseModel):
    """验证兑换码响应"""
    success: bool
    valid: bool
    reason: Optional[str] = None
    teams: List[TeamInfo] = []
    error: Optional[str] = None


class RedeemResponse(BaseModel):
    """兑换响应"""
    success: bool
    message: Optional[str] = None
    team_info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@router.post("/verify", response_model=VerifyCodeResponse)
async def verify_code(
    request: VerifyCodeRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    验证兑换码并返回可用 Team 列表

    Args:
        request: 验证请求
        db: 数据库会话

    Returns:
        验证结果和可用 Team 列表
    """
    try:
        logger.info(f"验证兑换码请求: {request.code}")

        result = await redeem_flow_service.verify_code_and_get_teams(
            request.code,
            db
        )

        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result["error"]
            )

        return VerifyCodeResponse(
            success=result["success"],
            valid=result["valid"],
            reason=result["reason"],
            teams=[TeamInfo(**team) for team in result["teams"]],
            error=result["error"]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"验证兑换码失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"验证失败: {str(e)}"
        )


@router.post("/confirm", response_model=RedeemResponse)
async def confirm_redeem(
    request: RedeemRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    确认兑换并加入 Team

    Args:
        request: 兑换请求
        db: 数据库会话

    Returns:
        兑换结果
    """
    try:
        logger.info(f"兑换请求: {request.email} -> Team {request.team_id} (兑换码: {request.code})")

        result = await redeem_flow_service.redeem_and_join_team(
            request.email,
            request.code,
            request.team_id,
            db
        )

        if not result["success"]:
            # 根据错误类型返回不同的状态码
            error_msg = result["error"]
            if any(kw in error_msg for kw in ["不存在", "已使用", "已过期", "截止时间", "已满", "质保", "无效", "失效"]):
                status_code = status.HTTP_400_BAD_REQUEST
                if "已满" in error_msg:
                    status_code = status.HTTP_409_CONFLICT
                raise HTTPException(
                    status_code=status_code,
                    detail=error_msg
                )
            else:
                # 默认系统内部错误
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=error_msg
                )

        return RedeemResponse(
            success=result["success"],
            message=result["message"],
            team_info=result["team_info"],
            error=result["error"]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"兑换失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"兑换失败: {str(e)}"
        )
