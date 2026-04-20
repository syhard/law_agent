"""配置管理模块"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except Exception:
    class BaseSettings:
        def __init__(self, **kwargs):
            for name, value in self.__class__.__dict__.items():
                if name.startswith("_") or callable(value):
                    continue
                setattr(self, name, kwargs.get(name, os.getenv(name.upper(), value)))

    class SettingsConfigDict(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(*args, **kwargs):
        return False


load_dotenv()

# 然后尝试加载 backend/.env（如果存在）
backend_env = Path(__file__).resolve().parents[1] / ".env"
if backend_env.exists():
    load_dotenv(backend_env, override=False)


def _normalize_debug_env() -> None:
    value = os.getenv("DEBUG")
    if value is None:
        return

    normalized = value.strip().lower()
    mapping = {
        "release": "false",
        "prod": "false",
        "production": "false",
        "debug": "true",
        "dev": "true",
        "development": "true",
    }
    if normalized in mapping:
        os.environ["DEBUG"] = mapping[normalized]


_normalize_debug_env()


class Settings(BaseSettings):
    """应用配置"""

    # 应用基本配置
    app_name: str = "HelloAgents智能法律助手"
    app_version: str = "1.0.0"
    debug: bool = False

    # 服务配置
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS 配置
    cors_origins: str = (
        "http://localhost:5173,http://localhost:3000,"
        "http://127.0.0.1:5173,http://127.0.0.1:3000,null"
    )

    # LLM 配置
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model_id: str = "gpt-4"

    # 日志配置
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file="backend/.env",
        case_sensitive=False,
        extra="ignore",
    )

    def get_cors_origins_list(self) -> List[str]:
        """获取 CORS origins 列表"""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


def get_settings() -> Settings:
    """获取配置实例"""
    return settings


def validate_config():
    """验证配置是否完整"""
    warnings = []

    llm_api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or settings.llm_api_key
    if not llm_api_key:
        warnings.append("LLM_API_KEY 或 OPENAI_API_KEY 未配置，LLM 功能可能无法使用")

    if warnings:
        print("\n配置警告:")
        for warning in warnings:
            print(f"  - {warning}")

    return True


def print_config():
    """打印当前配置（隐藏敏感信息）"""
    print(f"应用名称: {settings.app_name}")
    print(f"版本: {settings.app_version}")
    print(f"服务地址: {settings.host}:{settings.port}")

    llm_api_key = os.getenv("LLM_API_KEY") or settings.llm_api_key
    llm_base_url = os.getenv("LLM_BASE_URL") or settings.llm_base_url
    llm_model = os.getenv("LLM_MODEL_ID") or settings.llm_model_id

    print(f"LLM API Key: {'已配置' if llm_api_key else '未配置'}")
    print(f"LLM Base URL: {llm_base_url}")
    print(f"LLM Model: {llm_model}")
    print(f"日志级别: {settings.log_level}")


settings = Settings()
