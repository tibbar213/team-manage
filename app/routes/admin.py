"""
管理员路由
处理管理员面板的所有页面和操作
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.database import get_db
from app.dependencies.auth import require_admin
from app.services.team import TeamService
from app.services.redemption import RedemptionService
from app.utils.time_utils import get_now

logger = logging.getLogger(__name__)

# 创建路由器
router = APIRouter(
    prefix="/admin",
    tags=["admin"]
)

# 服务实例
team_service = TeamService()
redemption_service = RedemptionService()


# 请求模型
class TeamImportRequest(BaseModel):
    """Team 导入请求"""
    import_type: str = Field(..., description="导入类型: single 或 batch")
    access_token: Optional[str] = Field(None, description="AT Token (单个导入)")
    email: Optional[str] = Field(None, description="邮箱 (单个导入)")
    account_id: Optional[str] = Field(None, description="Account ID (单个导入)")
    content: Optional[str] = Field(None, description="批量导入内容")


class AddMemberRequest(BaseModel):
    """添加成员请求"""
    email: str = Field(..., description="成员邮箱")


class CodeGenerateRequest(BaseModel):
    """兑换码生成请求"""
    type: str = Field(..., description="生成类型: single 或 batch")
    code: Optional[str] = Field(None, description="自定义兑换码 (单个生成)")
    count: Optional[int] = Field(None, description="生成数量 (批量生成)")
    expires_days: Optional[int] = Field(None, description="有效期天数")


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    管理员面板首页

    Args:
        request: FastAPI Request 对象
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        管理员面板首页 HTML
    """
    try:
        # 导入模板引擎
        from app.main import templates

        logger.info("管理员访问控制台")

        # 获取所有 Team 列表
        teams_result = await team_service.get_all_teams(db)
        teams = teams_result.get("teams", [])

        # 获取兑换码统计
        codes_result = await redemption_service.get_all_codes(db)
        all_codes = codes_result.get("codes", [])

        # 计算统计数据
        stats = {
            "total_teams": len(teams),
            "available_teams": len([t for t in teams if t["status"] == "active" and t["current_members"] < t["max_members"]]),
            "total_codes": len(all_codes),
            "used_codes": len([c for c in all_codes if c["status"] == "used"])
        }

        return templates.TemplateResponse(
            "admin/index.html",
            {
                "request": request,
                "user": current_user,
                "active_page": "dashboard",
                "teams": teams,
                "stats": stats
            }
        )

    except Exception as e:
        logger.error(f"加载管理员面板失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"加载管理员面板失败: {str(e)}"
        )


@router.post("/teams/{team_id}/delete")
async def delete_team(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    删除 Team

    Args:
        team_id: Team ID
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        删除结果
    """
    try:
        logger.info(f"管理员删除 Team: {team_id}")

        result = await team_service.delete_team(team_id, db)

        if not result["success"]:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=result
            )

        return JSONResponse(content=result)

    except Exception as e:
        logger.error(f"删除 Team 失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": f"删除 Team 失败: {str(e)}"
            }
        )




@router.post("/teams/import")
async def team_import(
    import_data: TeamImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    处理 Team 导入

    Args:
        import_data: 导入数据
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        导入结果
    """
    try:
        logger.info(f"管理员导入 Team: {import_data.import_type}")

        if import_data.import_type == "single":
            # 单个导入
            if not import_data.access_token:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "success": False,
                        "error": "Access Token 不能为空"
                    }
                )

            result = await team_service.import_team_single(
                access_token=import_data.access_token,
                db_session=db,
                email=import_data.email,
                account_id=import_data.account_id
            )

            if not result["success"]:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content=result
                )

            return JSONResponse(content=result)

        elif import_data.import_type == "batch":
            # 批量导入
            if not import_data.content:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "success": False,
                        "error": "批量导入内容不能为空"
                    }
                )

            result = await team_service.import_team_batch(
                text=import_data.content,
                db_session=db
            )

            return JSONResponse(content=result)

        else:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "success": False,
                    "error": "无效的导入类型"
                }
            )

    except Exception as e:
        logger.error(f"导入 Team 失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": f"导入失败: {str(e)}"
            }
        )





@router.get("/teams/{team_id}/members/list")
async def team_members_list(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    获取 Team 成员列表 (JSON)

    Args:
        team_id: Team ID
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        成员列表 JSON
    """
    try:
        # 获取成员列表
        result = await team_service.get_team_members(team_id, db)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"获取成员列表失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": f"获取成员列表失败: {str(e)}"
            }
        )


@router.post("/teams/{team_id}/members/add")
async def add_team_member(
    team_id: int,
    member_data: AddMemberRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    添加 Team 成员

    Args:
        team_id: Team ID
        member_data: 成员数据
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        添加结果
    """
    try:
        logger.info(f"管理员添加成员到 Team {team_id}: {member_data.email}")

        result = await team_service.add_team_member(
            team_id=team_id,
            email=member_data.email,
            db_session=db
        )

        if not result["success"]:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=result
            )

        return JSONResponse(content=result)

    except Exception as e:
        logger.error(f"添加成员失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": f"添加成员失败: {str(e)}"
            }
        )


@router.post("/teams/{team_id}/members/{user_id}/delete")
async def delete_team_member(
    team_id: int,
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    删除 Team 成员

    Args:
        team_id: Team ID
        user_id: 用户 ID
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        删除结果
    """
    try:
        logger.info(f"管理员从 Team {team_id} 删除成员: {user_id}")

        result = await team_service.delete_team_member(
            team_id=team_id,
            user_id=user_id,
            db_session=db
        )

        if not result["success"]:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=result
            )

        return JSONResponse(content=result)

    except Exception as e:
        logger.error(f"删除成员失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": f"删除成员失败: {str(e)}"
            }
        )


@router.post("/teams/{team_id}/invites/revoke")
async def revoke_team_invite(
    team_id: int,
    member_data: AddMemberRequest, # 使用相同的包含 email 的模型
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    撤回 Team 邀请

    Args:
        team_id: Team ID
        member_data: 成员数据 (包含 email)
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        撤回结果
    """
    try:
        logger.info(f"管理员从 Team {team_id} 撤回邀请: {member_data.email}")

        result = await team_service.revoke_team_invite(
            team_id=team_id,
            email=member_data.email,
            db_session=db
        )

        if not result["success"]:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=result
            )

        return JSONResponse(content=result)

    except Exception as e:
        logger.error(f"撤回邀请失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": f"撤回邀请失败: {str(e)}"
            }
        )


# ==================== 兑换码管理路由 ====================

@router.get("/codes", response_class=HTMLResponse)
async def codes_list_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    兑换码列表页面

    Args:
        request: FastAPI Request 对象
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        兑换码列表页面 HTML
    """
    try:
        from app.main import templates

        logger.info("管理员访问兑换码列表页面")

        # 获取所有兑换码
        codes_result = await redemption_service.get_all_codes(db)
        all_codes = codes_result.get("codes", [])

        # 计算统计数据
        stats = {
            "total": len(all_codes),
            "unused": len([c for c in all_codes if c["status"] == "unused"]),
            "used": len([c for c in all_codes if c["status"] == "used"]),
            "expired": len([c for c in all_codes if c["status"] == "expired"])
        }

        # 格式化日期时间
        from datetime import datetime
        for code in all_codes:
            if code.get("created_at"):
                dt = datetime.fromisoformat(code["created_at"])
                code["created_at"] = dt.strftime("%Y-%m-%d %H:%M")
            if code.get("expires_at"):
                dt = datetime.fromisoformat(code["expires_at"])
                code["expires_at"] = dt.strftime("%Y-%m-%d %H:%M")
            if code.get("used_at"):
                dt = datetime.fromisoformat(code["used_at"])
                code["used_at"] = dt.strftime("%Y-%m-%d %H:%M")

        return templates.TemplateResponse(
            "admin/codes/index.html",
            {
                "request": request,
                "user": current_user,
                "active_page": "codes",
                "codes": all_codes,
                "stats": stats
            }
        )

    except Exception as e:
        logger.error(f"加载兑换码列表页面失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"加载页面失败: {str(e)}"
        )




@router.post("/codes/generate")
async def generate_codes(
    generate_data: CodeGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    处理兑换码生成

    Args:
        generate_data: 生成数据
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        生成结果
    """
    try:
        logger.info(f"管理员生成兑换码: {generate_data.type}")

        if generate_data.type == "single":
            # 单个生成
            result = await redemption_service.generate_code_single(
                db_session=db,
                code=generate_data.code,
                expires_days=generate_data.expires_days
            )

            if not result["success"]:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content=result
                )

            return JSONResponse(content=result)

        elif generate_data.type == "batch":
            # 批量生成
            if not generate_data.count:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "success": False,
                        "error": "生成数量不能为空"
                    }
                )

            result = await redemption_service.generate_code_batch(
                db_session=db,
                count=generate_data.count,
                expires_days=generate_data.expires_days
            )

            if not result["success"]:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content=result
                )

            return JSONResponse(content=result)

        else:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "success": False,
                    "error": "无效的生成类型"
                }
            )

    except Exception as e:
        logger.error(f"生成兑换码失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": f"生成失败: {str(e)}"
            }
        )


@router.post("/codes/{code}/delete")
async def delete_code(
    code: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    删除兑换码

    Args:
        code: 兑换码
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        删除结果
    """
    try:
        logger.info(f"管理员删除兑换码: {code}")

        result = await redemption_service.delete_code(code, db)

        if not result["success"]:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=result
            )

        return JSONResponse(content=result)

    except Exception as e:
        logger.error(f"删除兑换码失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": f"删除失败: {str(e)}"
            }
        )


@router.get("/codes/export")
async def export_codes(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    导出兑换码为Excel文件

    Args:
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        兑换码Excel文件
    """
    try:
        from fastapi.responses import Response
        from datetime import datetime
        import xlsxwriter
        from io import BytesIO

        logger.info("管理员导出兑换码为Excel")

        # 获取所有兑换码
        codes_result = await redemption_service.get_all_codes(db)
        all_codes = codes_result.get("codes", [])

        # 创建Excel文件到内存
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('兑换码列表')

        # 定义格式
        header_format = workbook.add_format({
            'bold': True,
            'fg_color': '#4F46E5',
            'font_color': 'white',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1
        })

        cell_format = workbook.add_format({
            'align': 'left',
            'valign': 'vcenter',
            'border': 1
        })

        # 设置列宽
        worksheet.set_column('A:A', 25)  # 兑换码
        worksheet.set_column('B:B', 12)  # 状态
        worksheet.set_column('C:C', 18)  # 创建时间
        worksheet.set_column('D:D', 18)  # 过期时间
        worksheet.set_column('E:E', 30)  # 使用者邮箱
        worksheet.set_column('F:F', 18)  # 使用时间

        # 写入表头
        headers = ['兑换码', '状态', '创建时间', '过期时间', '使用者邮箱', '使用时间']
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)

        # 写入数据
        for row, code in enumerate(all_codes, start=1):
            status_text = {
                'unused': '未使用',
                'used': '已使用',
                'expired': '已过期'
            }.get(code['status'], code['status'])

            worksheet.write(row, 0, code['code'], cell_format)
            worksheet.write(row, 1, status_text, cell_format)
            worksheet.write(row, 2, code.get('created_at', '-'), cell_format)
            worksheet.write(row, 3, code.get('expires_at', '永久有效'), cell_format)
            worksheet.write(row, 4, code.get('used_by_email', '-'), cell_format)
            worksheet.write(row, 5, code.get('used_at', '-'), cell_format)

        # 关闭workbook
        workbook.close()

        # 获取Excel数据
        excel_data = output.getvalue()
        output.close()

        # 生成文件名
        filename = f"redemption_codes_{get_now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        # 返回Excel文件
        return Response(
            content=excel_data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )

    except Exception as e:
        logger.error(f"导出兑换码失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导出失败: {str(e)}"
        )


@router.get("/records", response_class=HTMLResponse)
async def records_page(
    request: Request,
    email: Optional[str] = None,
    code: Optional[str] = None,
    team_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: Optional[str] = "1",
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    使用记录页面

    Args:
        request: FastAPI Request 对象
        email: 邮箱筛选
        code: 兑换码筛选
        team_id: Team ID 筛选
        start_date: 开始日期
        end_date: 结束日期
        page: 页码
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        使用记录页面 HTML
    """
    try:
        from app.main import templates
        from datetime import datetime, timedelta
        import math

        # 解析参数
        try:
            actual_team_id = int(team_id) if team_id and team_id.strip() else None
        except (ValueError, TypeError):
            actual_team_id = None
            
        try:
            page_int = int(page) if page and page.strip() else 1
        except (ValueError, TypeError):
            page_int = 1
            
        logger.info(f"管理员访问使用记录页面 (page={page_int})")

        # 获取记录 (支持邮箱、兑换码、Team ID 筛选)
        records_result = await redemption_service.get_all_records(
            db, 
            email=email, 
            code=code, 
            team_id=actual_team_id
        )
        all_records = records_result.get("records", [])

        # 仅由于日期范围筛选目前还在内存中处理，如果未来记录数极大可以移至数据库
        filtered_records = []
        for record in all_records:
            # 日期范围筛选
            if start_date or end_date:
                try:
                    record_date = datetime.fromisoformat(record["redeemed_at"]).date()

                    if start_date:
                        start = datetime.strptime(start_date, "%Y-%m-%d").date()
                        if record_date < start:
                            continue

                    if end_date:
                        end = datetime.strptime(end_date, "%Y-%m-%d").date()
                        if record_date > end:
                            continue
                except:
                    pass

            filtered_records.append(record)

        # 获取Team信息并关联到记录
        teams_result = await team_service.get_all_teams(db)
        teams = teams_result.get("teams", [])
        team_map = {team["id"]: team for team in teams}

        # 为记录添加Team名称
        for record in filtered_records:
            team = team_map.get(record["team_id"])
            record["team_name"] = team["team_name"] if team else None

        # 计算统计数据
        now = get_now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)

        stats = {
            "total": len(filtered_records),
            "today": 0,
            "this_week": 0,
            "this_month": 0
        }

        for record in filtered_records:
            try:
                record_time = datetime.fromisoformat(record["redeemed_at"])
                if record_time >= today_start:
                    stats["today"] += 1
                if record_time >= week_start:
                    stats["this_week"] += 1
                if record_time >= month_start:
                    stats["this_month"] += 1
            except:
                pass

        # 分页
        per_page = 20
        total_records = len(filtered_records)
        total_pages = math.ceil(total_records / per_page) if total_records > 0 else 1

        # 确保页码有效
        if page_int < 1:
            page_int = 1
        if page_int > total_pages:
            page_int = total_pages

        start_idx = (page_int - 1) * per_page
        end_idx = start_idx + per_page
        paginated_records = filtered_records[start_idx:end_idx]

        # 格式化时间
        for record in paginated_records:
            try:
                dt = datetime.fromisoformat(record["redeemed_at"])
                record["redeemed_at"] = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                pass

        return templates.TemplateResponse(
            "admin/records/index.html",
            {
                "request": request,
                "user": current_user,
                "active_page": "records",
                "records": paginated_records,
                "stats": stats,
                "filters": {
                    "email": email,
                    "code": code,
                    "team_id": team_id,
                    "start_date": start_date,
                    "end_date": end_date
                },
                "pagination": {
                    "current_page": page_int,
                    "total_pages": total_pages,
                    "total": total_records,
                    "per_page": per_page
                }
            }
        )

    except Exception as e:
        logger.error(f"获取使用记录失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取使用记录失败: {str(e)}"
        )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    系统设置页面

    Args:
        request: FastAPI Request 对象
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        系统设置页面 HTML
    """
    try:
        from app.main import templates
        from app.services.settings import settings_service

        logger.info("管理员访问系统设置页面")

        # 获取当前配置
        proxy_config = await settings_service.get_proxy_config(db)
        log_level = await settings_service.get_log_level(db)

        return templates.TemplateResponse(
            "admin/settings/index.html",
            {
                "request": request,
                "user": current_user,
                "active_page": "settings",
                "proxy_enabled": proxy_config["enabled"],
                "proxy": proxy_config["proxy"],
                "log_level": log_level
            }
        )

    except Exception as e:
        logger.error(f"获取系统设置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取系统设置失败: {str(e)}"
        )


class ProxyConfigRequest(BaseModel):
    """代理配置请求"""
    enabled: bool = Field(..., description="是否启用代理")
    proxy: str = Field("", description="代理地址")


class LogLevelRequest(BaseModel):
    """日志级别请求"""
    level: str = Field(..., description="日志级别")


@router.post("/settings/proxy")
async def update_proxy_config(
    proxy_data: ProxyConfigRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    更新代理配置

    Args:
        proxy_data: 代理配置数据
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        更新结果
    """
    try:
        from app.services.settings import settings_service

        logger.info(f"管理员更新代理配置: enabled={proxy_data.enabled}, proxy={proxy_data.proxy}")

        # 验证代理地址格式
        if proxy_data.enabled and proxy_data.proxy:
            proxy = proxy_data.proxy.strip()
            if not (proxy.startswith("http://") or proxy.startswith("https://") or proxy.startswith("socks5://")):
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "success": False,
                        "error": "代理地址格式错误,应为 http://host:port 或 socks5://host:port"
                    }
                )

        # 更新配置
        success = await settings_service.update_proxy_config(
            db,
            proxy_data.enabled,
            proxy_data.proxy.strip() if proxy_data.proxy else ""
        )

        if success:
            return JSONResponse(content={"success": True, "message": "代理配置已保存"})
        else:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"success": False, "error": "保存失败"}
            )

    except Exception as e:
        logger.error(f"更新代理配置失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": f"更新失败: {str(e)}"}
        )


@router.post("/settings/log-level")
async def update_log_level(
    log_data: LogLevelRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    更新日志级别

    Args:
        log_data: 日志级别数据
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        更新结果
    """
    try:
        from app.services.settings import settings_service

        logger.info(f"管理员更新日志级别: {log_data.level}")

        # 更新日志级别
        success = await settings_service.update_log_level(db, log_data.level)

        if success:
            return JSONResponse(content={"success": True, "message": "日志级别已保存"})
        else:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"success": False, "error": "无效的日志级别"}
            )

    except Exception as e:
        logger.error(f"更新日志级别失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": f"更新失败: {str(e)}"}
        )


