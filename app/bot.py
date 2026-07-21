import asyncio
import logging
import os
import re

FILE_PRODUCING_TOOLS = {"generate_invoice_pdf", "generate_report_pptx"}
FILE_PATH_PATTERN = re.compile(r"FILE_PATH:\s*(\S+)")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("super-market-bot")


async def handle_telegram_message(request, chat_id: str, text: str, update_id: str) -> dict:
    agent = request.app.state.agent

    # Run synchronous invoke without blocking the event loop
    result = await asyncio.to_thread(
        agent.invoke,
        {"messages": [{"role": "user", "content": text}]},
        config={
            "configurable": {
                "chat_id": chat_id,
                "thread_id": chat_id,
                "update_id": update_id,
            }
        },
    )

    messages = result["messages"]

    
    assistant_msg = messages[-1]
    content = assistant_msg.content

    if isinstance(content, list):
        reply_text = "".join(
            block["text"]
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
    else:
        reply_text = str(content).strip() if content else ""

    if not reply_text:
        reply_text = "Sorry, I couldn't process that."

   
    file_path = None

    last_human_index = None

    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]

     
        if getattr(msg, "type", None) == "human":
            last_human_index = i
            break

    
    if last_human_index is not None:
        for msg in messages[last_human_index + 1:]:
            tool_name = getattr(msg, "name", None)

            if tool_name not in FILE_PRODUCING_TOOLS:
                continue

            tool_content = (
                msg.content if isinstance(msg.content, str)
                else str(msg.content)
            )

            match = FILE_PATH_PATTERN.search(tool_content)

            if match:
                candidate = match.group(1)

                if os.path.exists(candidate):
                    file_path = candidate

    logger.info("reply=%s", reply_text)
    logger.info("file_path=%s", repr(file_path))

    return {
        "text": reply_text,
        "file_path": file_path,
    }