import logging
import json
import sqlite3
from pathlib import Path
from typing import Generator
from flask import Flask, request, Response, jsonify, send_from_directory
from flask_cors import CORS
from src.main import workflow
from src.agents.models import create_initial_state
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

# ==================== SQLite 数据库 ====================
DB_PATH = Path(__file__).parent / "data" / "checkpoints.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# ==================== Flask App ====================
app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
checkpointer = SqliteSaver(conn)
graph = workflow.compile(checkpointer=checkpointer)


# ==================== 路由：静态页面 ====================
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/chat/<thread_id>')
def chat_page(thread_id):
    return send_from_directory('static', 'index.html')

# ==================== API：获取欢迎词 ====================
@app.route('/api/welcome', methods=['GET'])
def get_welcome_message():
    """返回聊天助手的欢迎词"""
    welcome_text = """👋 **您好！我是 AI 聊天助手**

**我可以帮您：**
• 回答各种问题
• 提供建议和想法
• 进行友好的对话

**随时告诉我您的需求，我很乐意帮助您！** 😊"""
    
    return jsonify({
        "success": True,
        "message": welcome_text
    })

def get_message_role(message) -> str:
    """判断消息角色类型"""
    # 检查工具调用（支持流式和非流式两种情况）
    if (hasattr(message, "tool_call_chunks") and message.tool_call_chunks and len(message.tool_call_chunks) > 0) or \
       (hasattr(message, "tool_calls") and message.tool_calls and len(message.tool_calls) > 0):
        return "tool_call"
    # 检查工具结果
    elif isinstance(message, ToolMessage):
        return "tool_result"
    # 普通消息
    else:
        return "human" if isinstance(message, HumanMessage) else "ai"


def streaming_process(graph, message, config) -> Generator[str, None, None]:
    """处理流式响应，返回 SSE 格式的事件流"""
    message_id = None
    message_role = None
    
    try:
        for mode, chunk in graph.stream(
            {"messages": [HumanMessage(content=message)], "config": config},
            config=config,
            stream_mode=["messages"],
            stream_subgraphs=True
        ):
            if mode != "messages":
                continue
            
            message_token, metadata = chunk
            chunk_position = message_token.chunk_position if hasattr(message_token, "chunk_position") and message_token.chunk_position else None
            
            # 检测新消息
            if message_id != message_token.id:
                message_role = get_message_role(message_token)
                if message_role == "ai" and message_token.content == "":
                    continue
                yield f'data: {json.dumps({"type": "message_change", "role": message_role})}\n\n'
                message_id = message_token.id
            
            # 根据消息角色格式化内容
            if message_role == "tool_call":
                tool_call_content = ""
                for tool_call in message_token.tool_call_chunks:
                    tool_call_id = "" if tool_call.get("id") is None else f"🔧 Tool Call({tool_call['id']}):\n"
                    tool_call_name = "" if tool_call.get("name") is None else f"name: {tool_call['name']}\nargs: "
                    tool_call_args = tool_call['args']
                    tool_call_content += f"{tool_call_id}{tool_call_name}{tool_call_args}"
                yield f'data: {json.dumps({"type": "token", "content": tool_call_content, "chunk_position": chunk_position})}\n\n'
            
            elif message_role == "tool_result":
                if not message_token.tool_call_id and message_token.content:
                    continue
                yield f'data: {json.dumps({"type": "token", "content": f"✅ Tool Result({message_token.tool_call_id}):\nresult: {message_token.content}", "chunk_position": chunk_position})}\n\n'
            
            else:
                yield f'data: {json.dumps({"type": "token", "content": message_token.content, "chunk_position": chunk_position})}\n\n'
    
    except Exception as e:
        logger.error(f"[STREAM] Graph execution error: {e}", exc_info=True)
        yield f'data: {json.dumps({"type": "error", "error": f"执行出错: {str(e)}"})}\n\n'
    
    # 总是发送结束信号
    yield f'data: {json.dumps({"type": "done"})}\n\n'

# ==================== API：流式对话 ====================
@app.route('/api/chat/stream', methods=['POST'])
def chat_stream():
    data = request.json
    thread_id = data.get('thread_id')
    message = data.get('message')
    
    logger.info(f"[STREAM] 收到请求 - thread_id: {thread_id}, message: {message[:50] if message else 'None'}...")
    
    if not thread_id or not message:
        return jsonify({"error": "missing thread_id or message"}), 400
    
    def generate():
        # 发送 thread_id
        yield f'data: {json.dumps({"type": "thread_id", "thread_id": thread_id})}\n\n'
        # 配置
        config = {"configurable": {"thread_id": thread_id}}
        # 调用流式处理函数
        yield from streaming_process(graph, message, config)
    
    return Response(generate(), mimetype='text/event-stream')

# ==================== API：初始化会话 ====================
@app.route('/api/thread/<thread_id>/init', methods=['POST'])
def init_thread(thread_id):
    """初始化新会话，创建空的 checkpoint"""
    try:
        config = {"configurable": {"thread_id": thread_id}}
        
        # 检查是否已存在
        state = graph.get_state(config)
        if state and state.values.get("messages"):
            logger.info(f"[INIT] Thread already exists: {thread_id}")
            return jsonify({"success": True, "message": "thread_already_exists"})
        
        # 使用 update_state 创建初始 checkpoint
        graph.update_state(config, create_initial_state())
        
        logger.info(f"[INIT] Thread initialized: {thread_id}")
        return jsonify({"success": True, "thread_id": thread_id})
        
    except Exception as e:
        logger.error(f"[INIT] Init thread error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== API：获取历史消息 ====================
@app.route('/api/thread/<thread_id>/messages', methods=['GET'])
def get_history(thread_id):
    try:
        config = {"configurable": {"thread_id": thread_id}}
        state = graph.get_state(config)
        
        if not state or len(state.values) == 0:
            return jsonify({"success": False, "error": "thread_not_found"}), 404
        
        messages = []
        for msg in state.values["messages"]:
            # 工具调用消息
            role = get_message_role(msg)
            if role == "tool_call":
                message_content = ""  # ✅ 初始化变量
                for tool_call in msg.tool_calls:
                    if tool_call['id'] == None or tool_call['name'] == None or tool_call['args'] == None:
                        continue
                    message_content += f"🔧 Tool Call({tool_call['id']}):\nname: {tool_call['name']}\nargs: {tool_call['args']}\n\n"
                messages.append({
                    "role": "tool_call",
                    "content": message_content.strip()
                })
            elif role == "tool_result":
                messages.append({
                    "role": role,
                    "content": f"✅ Tool Result({msg.tool_call_id}):\nresult: {msg.content}"  # ✅ 修复变量引用
                })
            else:
                messages.append({
                    "role": role,
                    "content": msg.content
                })
        return jsonify({"success": True, "messages": messages})
    except Exception as e:
        logger.error(f"Get history error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== 启动 ====================
if __name__ == "__main__":
    logger.info("服务启动！")
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
