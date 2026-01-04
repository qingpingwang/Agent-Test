import logging
from src.agents.models import (
    State,
    get_model,
    create_summarized_agent,
    invoke_agent_with_context,
    MAX_TOKENS
)

logger = logging.getLogger(__name__)

# ==================== 系统提示词 ====================

CHATBOT_SYSTEM_PROMPT = """你是一个友好、专业的 AI 聊天助手。

## 核心原则
1. 礼貌、耐心、友好地回应用户
2. 提供准确、有用的信息
3. 当不确定时，诚实地说明而不是编造

## 交流风格
- 自然、口语化的表达
- 适度使用 emoji 让对话更生动
- 根据用户的语气调整你的回应风格"""

# 摘要提示词（当对话历史过长时触发）
SUMMARY_PROMPT = """请简洁地总结以下对话历史的关键要点：

{messages}

总结要求：
1. 保留重要的上下文信息
2. 去除冗余的问候和寒暄
3. 突出用户的主要诉求和你的关键回复"""

# ==================== Agent 定义 ====================

# 创建聊天 agent（带摘要功能）
chatbot_agent = create_summarized_agent(
    model=get_model(),
    tools=[],
    system_prompt=CHATBOT_SYSTEM_PROMPT,
    summary_prompt=SUMMARY_PROMPT,
    max_tokens_before_summary=int(MAX_TOKENS*0.8),
    messages_to_keep=10,
    context_schema=State
)


def chatbot(state: State):
    """
    聊天 agent 节点：纯粹的对话交互
    
    功能：
    - 接收用户消息
    - 生成友好的回复
    - 自动管理对话历史（超长时自动摘要）
    
    Args:
        state: Graph State，包含 messages 和 llm_context
        
    Returns:
        更新后的 messages 和 llm_context
    """
    # 调用 agent 获取响应
    thread_id = state['config']['configurable']['thread_id']
    logger.info(f"thread_id: {thread_id} chatbot get messages: {state['messages'][-1].content}")
    new_ai_messages, result_llm_context, response = invoke_agent_with_context(state, chatbot_agent)
    logger.info(f"thread_id: {thread_id} chatbot response: {new_ai_messages[-1].content if new_ai_messages else 'empty'}")
    return {
        "messages": new_ai_messages,
        "llm_context": result_llm_context,
    }


# ==================== 测试代码 ====================

if __name__ == "__main__":
    from langchain_core.messages import HumanMessage
    
    # 构造测试 state
    state = {
        "messages": [HumanMessage(content="你好！今天天气真不错")],
        "llm_context": [],
        "config": {},
    }
    
    # 调用 chatbot 并获取更新
    result = chatbot(state)
    print(f"\n=== AI 回复 ===")
    print(result["messages"][-1].content)
    print(f"\n=== llm_context 长度 ===")
    print(len(result["llm_context"]))