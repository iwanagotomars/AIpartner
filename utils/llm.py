import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
# 初始化模型
load_dotenv()


def get_llm():
    llm = ChatOpenAI(
        model=os.getenv("LLM_MODEL_ID"),
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL"),
        temperature=0.7,
        extra_body={"thinking": {"type": "disabled"}}
    )
    return llm


def get_thinking_llm():
    """创建带有思考的模型，用于总结近期记忆、撰写人物传记"""
    return ChatOpenAI(
        model=os.getenv("LLM_MODEL_ID"),
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL"),
        extra_body={"thinking": {"type": "enabled"}},
    )


def get_display_llm():
    """创建确定性更高的演出规划模型。"""
    return ChatOpenAI(
        model=os.getenv("LLM_MODEL_ID"),
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL"),
        temperature=0.1,
        extra_body={"thinking": {"type": "disabled"}},
    )


def get_translation_llm():
    """创建低温度、关闭思考且限制等待时间的语音翻译模型。"""
    return ChatOpenAI(
        model=os.getenv("LLM_MODEL_ID"),
        api_key=os.getenv("LLM_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL"),
        temperature=0.1,
        request_timeout=5.0,
        # 翻译类已经负责失败后重试一次，避免模型客户端重复重试。
        max_retries=0,
        extra_body={"thinking": {"type": "disabled"}},
    )


def get_vision_llm():
    llm = ChatOpenAI(
        model=os.getenv("LLM_VISION_MODEL_ID"),
        api_key=os.getenv("LLM_VISION_API_KEY"),
        base_url=os.getenv("LLM_VISION_BASE_URL"),
        temperature=0.7,
        extra_body={"thinking": {"type": "disabled"}}
    )
    return llm