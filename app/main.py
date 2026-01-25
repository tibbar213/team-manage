"""
GPT Team 管理和兑换码自动邀请系统
FastAPI 应用入口文件
"""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
import logging
from pathlib import Path
from datetime import datetime

from contextlib import asynccontextmanager
# 导入路由
from app.routes import redeem, auth, admin, api, user
from app.config import settings
from app.database import init_db, close_db, AsyncSessionLocal
from app.services.auth import auth_service

# 获取项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"

from starlette.exceptions import HTTPException as StarletteHTTPException

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    启动时初始化数据库，关闭时释放资源
    """
    logger.info("系统正在启动，正在初始化数据库...")
    try:
        # 0. 确保数据库目录存在
        db_file = settings.database_url.split("///")[-1]
        Path(db_file).parent.mkdir(parents=True, exist_ok=True)
        
        # 1. 创建数据库表
        await init_db()
        # 2. 初始化管理员密码（如果不存在）
        async with AsyncSessionLocal() as session:
            await auth_service.initialize_admin_password(session)
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
    
    yield
    
    # 关闭连接
    await close_db()
    logger.info("系统正在关闭，已释放数据库连接")


# 创建 FastAPI 应用实例
app = FastAPI(
    title="GPT Team 管理系统",
    description="ChatGPT Team 账号管理和兑换码自动邀请系统",
    version="0.1.0",
    lifespan=lifespan
)

# 全局异常处理
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """ 处理 HTTP 异常 """
    if exc.status_code in [401, 403]:
        # 检查是否是 HTML 请求
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return RedirectResponse(url="/login")
    
    # 默认返回 JSON 响应（FastAPI 的默认行为）
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

# 配置 Session 中间件
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="session",
    max_age=14 * 24 * 60 * 60,  # 14 天
    same_site="lax",
    https_only=False  # 开发环境设为 False，生产环境应设为 True
)

# 配置静态文件
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

# 配置模板引擎
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

# 添加模板过滤器
def format_datetime(dt):
    """格式化日期时间"""
    if not dt:
        return "-"
    if isinstance(dt, str):
        try:
            # 兼容包含时区信息的字符串
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except:
            return dt
    
    # 统一转换为北京时间显示 (如果它是 aware datetime)
    import pytz
    from app.config import settings
    if dt.tzinfo is None:
        # 如果是 naive datetime，假设它是本地时区（CST）的时间
        pass
    else:
        # 如果是 aware datetime，转换为目标时区
        tz = pytz.timezone(settings.timezone)
        dt = dt.astimezone(tz)
        
    return dt.strftime("%Y-%m-%d %H:%M")

def escape_js(value):
    """转义字符串用于 JavaScript"""
    if not value:
        return ""
    return value.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")

templates.env.filters["format_datetime"] = format_datetime
templates.env.filters["escape_js"] = escape_js

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 注册路由
app.include_router(user.router)  # 用户路由(根路径)
app.include_router(redeem.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(api.router)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """登录页面"""
    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request, "user": None}
    )


@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug
    )
