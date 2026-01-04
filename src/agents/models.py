from typing import Annotated, TypedDict, List, Tuple
from langgraph.graph.message import add_messages, REMOVE_ALL_MESSAGES
from langchain_core.messages import AnyMessage, RemoveMessage
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from pydantic import BaseModel
import os
import logging

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

# ==================== Graph State ====================

class State(TypedDict):
    """Graph state - 完整的工作流状态"""
    messages: Annotated[list[AnyMessage], add_messages]  # 用户可见的对话历史（前端展示）
    llm_context: Annotated[list[AnyMessage], add_messages]  # LLM 工作上下文（包含摘要压缩）
    config: dict  # 对话配置


def create_initial_state() -> State:
    """
    创建 State 的初始值
    
    用于初始化新会话或需要重置状态的场景。
    确保所有字段都有正确的默认值。
    
    Returns:
        State: 初始化的状态字典
    """
    return {
        "messages": [],
        "llm_context": [],
        "config": {},
    }

    
API_KEY = os.getenv("OPENAI_API_KEY")
BASE_URL = os.getenv("OPENAI_BASE_URL")
MODEL_NAME = os.getenv("OPENAI_MODEL_NAME")

assert API_KEY is not None, "OPENAI_API_KEY is not set"
assert BASE_URL is not None, "OPENAI_BASE_URL is not set"
assert MODEL_NAME is not None, "OPENAI_MODEL_NAME is not set"

# LLM 参数配置（可选）
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "12288"))


def get_model(
    model_name: str = MODEL_NAME,
    temperature: float = TEMPERATURE,
    api_key: str = API_KEY,
    base_url: str = BASE_URL,
    max_tokens: int = MAX_TOKENS,
    streaming: bool = True, 
):
    """创建 ChatOpenAI 模型实例"""
    return ChatOpenAI(
        model=model_name,
        temperature=temperature,
        api_key=api_key,
        base_url=base_url,
        streaming=streaming,
        max_tokens=max_tokens,
    )


def create_summarized_agent(
    model=None,
    tools: List = None,
    system_prompt: str = None,
    summary_prompt: str = None,
    max_tokens_before_summary: int = 10000,
    messages_to_keep: int = 10,
    response_format: BaseModel = None,
    middleware: List = None,
    context_schema: BaseModel = None,
):
    """
    创建 Agent（可选摘要功能）
    
    Args:
        model: LLM 模型实例，默认使用 get_model()
              注意：如果需要结构化输出，请在外部先调用 model.with_structured_output() 再传入
        tools: 工具列表，默认为空列表
        system_prompt: 系统提示词
        summary_prompt: 摘要提示词模板（包含 {messages} 占位符）。
                       如果提供此参数，则启用摘要功能；否则创建普通 agent
        max_tokens_before_summary: 触发摘要的 token 阈值（仅在提供 summary_prompt 时生效）
        messages_to_keep: 摘要时保留的最近消息数（仅在提供 summary_prompt 时生效）
    
    Returns:
        配置好的 Agent 实例
        
    Examples:
        # 创建带摘要功能的 agent
        agent = create_summarized_agent(
            model=model,
            tools=[tool1, tool2],
            system_prompt="你是助手",
            summary_prompt="请总结对话：{messages}"
        )
        
        # 创建普通 agent（不启用摘要）
        agent = create_summarized_agent(
            model=model,
            tools=[tool1],
            system_prompt="你是助手"
        )
        
        # 外部处理结构化输出
        structured_model = get_model().with_structured_output(MySchema)
        agent = create_summarized_agent(
            model=structured_model,
            system_prompt="你是助手",
            summary_prompt="请总结对话：{messages}"
        )
    """
    if model is None:
        model = get_model()
    
    if tools is None:
        tools = []
    
    if system_prompt is None:
        system_prompt = "你是一个有用的 AI 助手。"
    
    # 根据是否提供 summary_prompt 决定是否启用摘要
    user_middleware = middleware if middleware is not None else []
    if summary_prompt is not None:
        user_middleware.append(
            SummarizationMiddleware(
                model=model,
                max_tokens_before_summary=max_tokens_before_summary,
                messages_to_keep=messages_to_keep,
                summary_prompt=summary_prompt,
            )
        )
    
    # 创建 agent
    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=user_middleware,
        response_format=response_format,
        context_schema=context_schema,
    )
    
    return agent


def invoke_agent_with_context(state: State, agent) -> Tuple[List[AnyMessage], List, dict]:
    """
    标准的 agent 调用模式：同步用户消息 → 调用 agent → 更新 llm_context
    
    Args:
        state: 当前 Graph State
        agent: 要调用的 agent 实例
    
    Returns:
        (new_ai_messages, result_llm_context): 
        - new_ai_messages: 新增的 AI 消息（用于更新前端 messages）
        - result_llm_context: 更新后的 llm_context（包含 RemoveMessage 标记）
    
    使用示例：
        def my_agent_node(state: State):
            # 调用 agent 并获取更新后的上下文
            new_ai_messages, result_llm_context = invoke_agent_with_context(state, my_agent)
            
            # 返回更新
            return {
                "messages": new_ai_messages,
                "llm_context": result_llm_context,
                # ... 其他状态更新
            }
    """
    # 1. 获取当前上下文
    messages = state["messages"]
    llm_context = state.get("llm_context", [])
    
    # 2. 同步最新的用户消息到 llm_context
    current_llm_context = llm_context + [messages[-1]] if messages else llm_context
    
    # 3. 调用 agent（会自动处理摘要）
    response = agent.invoke({"messages": current_llm_context}, config=state.get("config", {}), context=state)
    new_llm_context = response["messages"]
    
    # 4. 找出新增的 AI/Tool 消息（用于更新前端）
    old_ids = {m.id for m in current_llm_context}
    new_ai_messages = [m for m in new_llm_context if m.type in ("ai", "tool") and m.id not in old_ids]
    
    # 5. 使用 __remove_all__ 清空所有旧消息，然后添加新消息
    # 这样确保摘要永远在第一位，不会因为 add_messages 保持原有位置而错位
    result_llm_context = [RemoveMessage(id=REMOVE_ALL_MESSAGES)]
    result_llm_context.extend(new_llm_context)
    
    # 新增回复、全量更新 llm_context、当前回答
    return new_ai_messages, result_llm_context, response

