"""
JWT Token 解析工具
用于解析和验证 ChatGPT Access Token (AT)
"""
import jwt
from typing import Optional, Dict, Any
from datetime import datetime
import logging
from app.utils.time_utils import get_now

logger = logging.getLogger(__name__)


class JWTParser:
    """JWT Token 解析器"""

    def __init__(self, verify_signature: bool = False):
        """
        初始化 JWT 解析器

        Args:
            verify_signature: 是否验证签名 (开发环境可设为 False)
        """
        self.verify_signature = verify_signature

    def decode_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        解析 JWT Token

        Args:
            token: JWT Token 字符串

        Returns:
            解析后的 payload 字典,失败返回 None
        """
        try:
            # 解析 JWT (不验证签名)
            payload = jwt.decode(
                token,
                options={
                    "verify_signature": self.verify_signature,
                    "verify_exp": False  # 手动检查过期时间
                }
            )
            return payload

        except jwt.InvalidTokenError as e:
            logger.error(f"JWT Token 解析失败: {e}")
            return None
        except Exception as e:
            logger.error(f"解析 Token 时发生错误: {e}")
            return None

    def extract_email(self, token: str) -> Optional[str]:
        """
        从 Token 中提取邮箱地址

        Args:
            token: JWT Token 字符串

        Returns:
            邮箱地址,失败返回 None
        """
        payload = self.decode_token(token)
        if not payload:
            return None

        try:
            # ChatGPT Token 的邮箱字段路径
            profile = payload.get("https://api.openai.com/profile", {})
            email = profile.get("email")
            return email
        except Exception as e:
            logger.error(f"提取邮箱失败: {e}")
            return None

    def extract_user_id(self, token: str) -> Optional[str]:
        """
        从 Token 中提取用户 ID

        Args:
            token: JWT Token 字符串

        Returns:
            用户 ID,失败返回 None
        """
        payload = self.decode_token(token)
        if not payload:
            return None

        try:
            # ChatGPT Token 的 user_id 字段路径
            auth = payload.get("https://api.openai.com/auth", {})
            user_id = auth.get("user_id")
            return user_id
        except Exception as e:
            logger.error(f"提取 user_id 失败: {e}")
            return None

    def get_expiration_time(self, token: str) -> Optional[datetime]:
        """
        获取 Token 过期时间

        Args:
            token: JWT Token 字符串

        Returns:
            过期时间 (datetime 对象),失败返回 None
        """
        payload = self.decode_token(token)
        if not payload:
            return None

        try:
            exp_timestamp = payload.get("exp")
            if exp_timestamp:
                return datetime.fromtimestamp(exp_timestamp)
            return None
        except Exception as e:
            logger.error(f"获取过期时间失败: {e}")
            return None

    def is_token_expired(self, token: str) -> bool:
        """
        检查 Token 是否已过期

        Args:
            token: JWT Token 字符串

        Returns:
            True 表示已过期,False 表示未过期
        """
        exp_time = self.get_expiration_time(token)
        if not exp_time:
            return True  # 无法获取过期时间,视为已过期

        return get_now() > exp_time

    def validate_token(self, token: str) -> Dict[str, Any]:
        """
        验证 Token 并返回详细信息

        Args:
            token: JWT Token 字符串

        Returns:
            验证结果字典,包含 valid, email, user_id, exp_time, is_expired 等字段
        """
        result = {
            "valid": False,
            "email": None,
            "user_id": None,
            "exp_time": None,
            "is_expired": True,
            "error": None
        }

        # 解析 Token
        payload = self.decode_token(token)
        if not payload:
            result["error"] = "Token 解析失败"
            return result

        # 提取信息
        result["email"] = self.extract_email(token)
        result["user_id"] = self.extract_user_id(token)
        result["exp_time"] = self.get_expiration_time(token)
        result["is_expired"] = self.is_token_expired(token)

        # 验证必要字段
        if not result["email"]:
            result["error"] = "无法提取邮箱地址"
            return result

        if result["is_expired"]:
            result["error"] = "Token 已过期"
            return result

        # 验证通过
        result["valid"] = True
        return result


# 创建全局实例 (从配置读取是否验证签名)
def create_jwt_parser(verify_signature: bool = False) -> JWTParser:
    """
    创建 JWT 解析器实例

    Args:
        verify_signature: 是否验证签名

    Returns:
        JWTParser 实例
    """
    return JWTParser(verify_signature=verify_signature)
