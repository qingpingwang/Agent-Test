from langgraph.graph import StateGraph, START, END
from src.agents import chatbot, State

# ==================== Graph 构建 ====================
workflow = StateGraph(State)

# 添加聊天节点
workflow.add_node("chatbot", chatbot)

# 简单的线性流程：START → chatbot → END
workflow.add_edge(START, "chatbot")
workflow.add_edge("chatbot", END)