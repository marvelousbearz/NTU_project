from autogen import AssistantAgent, UserProxyAgent
import secret

llm_config = {
    "config_list": [
        {
            "model": "deepseek-chat",
            "api_key": secret.API,  
            "base_url": "https://api.deepseek.com/v1",
        }
    ],
    "temperature": 0.1
}

user_proxy = UserProxyAgent(
    name="user_proxy",
    human_input_mode="NEVER",
    max_consecutive_auto_reply=0,
    code_execution_config=False,
    llm_config=llm_config
)

assistant = AssistantAgent(
    name="assistant",
    llm_config=llm_config,
    system_message=(
        "你是银行客户分析专家。"
        "请根据用户提供的客户信息和流失概率，回答用户的问题。"
        "你的回答应该专业、精准，并且给出挽留客户的具体建议。"
        "如果你不知道答案，请诚实说明。"
        "用户用英文提问，你也要用英文回答"
    )
)

def ask_ai(question: str, context: str) -> str:
    message = f"客户数据上下文：{context}\n\n用户问题：{question}"

    try:
        result = user_proxy.initiate_chat(
            assistant,
            message=message,
            max_turns=1
        )

        # 从对话历史里倒序取出最后一条有内容的回复（即 assistant 的回答）
        if hasattr(result, "chat_history"):
            for msg in reversed(result.chat_history):
                content = msg.get("content") if isinstance(msg, dict) else None
                if content:
                    return content
        return "Sorry, AI agent cannot analyse"
    except Exception as e:
        return f"AI 分析出错：{e}"