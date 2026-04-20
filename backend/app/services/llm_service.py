"""LLM服务模块"""

from __future__ import annotations

import os
import sys

from hello_agents import HelloAgentsLLM


sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_settings


_llm_instance = None


def get_llm():
    """
    获取 LLM 实例（单例模式）

    Returns:
        HelloAgentsLLM 实例
    """
    global _llm_instance

    if _llm_instance is None:
        settings = get_settings()
        if HelloAgentsLLM is None:
            return None
        _llm_instance = HelloAgentsLLM()

        print("LLM 服务初始化成功")
        print(f"模型: {_llm_instance.model}")

    return _llm_instance


def reset_llm():
    """重置 LLM 实例（用于测试或重新配置）"""
    global _llm_instance
    _llm_instance = None
