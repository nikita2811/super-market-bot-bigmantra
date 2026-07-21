import re
import logging

FILE_PRODUCING_TOOLS = {"generate_invoice_pdf", "generate_report_pptx"}
FILE_PATH_PATTERN = re.compile(r"FILE_PATH:\s*(\S+)")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("super-market-bot")


async def handle_telegram_message(request, chat_id: str, text: str,update_id: str) -> dict:
    agent = request.app.state.agent
    result = agent.invoke(
        {"messages": [{"role": "user", "content": text}]},
        config={
            "configurable": {
                "chat_id": chat_id,
                "thread_id": chat_id,
                "update_id":update_id
            }
        },
    )
    messages = result["messages"]
    content = messages[-1].content

    if isinstance(content, list):
        
        reply_text = "".join(
            block["text"] for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ) or "Sorry, I couldn't process that."
    else:
        reply_text = content or "Sorry, I couldn't process that."


    file_path = None
    for msg in reversed(messages):
        tool_name = getattr(msg, "name", None)
        if tool_name in FILE_PRODUCING_TOOLS:
            tool_content = msg.content if isinstance(msg.content, str) else str(msg.content)
            match = FILE_PATH_PATTERN.search(tool_content)
            if match:
                file_path = match.group(1)
                break
      
    
    logger.info(f"file_path={repr(file_path)}")
    return {"text": reply_text, "file_path": file_path}