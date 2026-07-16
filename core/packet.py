"""
基岩版协议封包模块
负责构建符合 Minecraft Bedrock WebSocket 协议的 JSON 数据包
"""

import json
import uuid


def make_packet(purpose: str, event_name: str = None, command_line: str = None, request_id: str = None) -> str:
    """
    构建 Minecraft Bedrock WebSocket 协议数据包。

    Args:
        purpose: 消息目的。若 command_line 以 "subscribe" 开头，自动修正为 "subscribe"。
        event_name: 事件名称，如 "PlayerMessage"
        command_line: 命令字符串，如 "say hello" / "subscribe PlayerMessage"
        request_id: 指定 requestId（用于指令响应匹配）。不传则自动生成。

    Returns:
        JSON 字符串格式的协议数据包
    """
    # 参数自适应：如果指令是订阅事件，messagePurpose 必须为 "subscribe"
    if command_line and command_line.lstrip().startswith("subscribe"):
        purpose = "subscribe"

    packet = {
        "header": {
            "version": 1,
            "requestId": request_id or str(uuid.uuid4()),
            "messageType": "commandRequest" if command_line else "eventRequest",
            "messagePurpose": purpose
        },
        "body": {}
    }

    if event_name:
        packet["body"]["eventName"] = event_name

    if command_line:
        # 去掉可能的前导 /
        if command_line.startswith("/"):
            command_line = command_line[1:]
        packet["body"]["commandLine"] = command_line
        packet["body"]["version"] = 1
        packet["body"]["origin"] = {"type": "player"}

    return json.dumps(packet)


def parse_packet(message: str) -> dict:
    """
    解析从 WebSocket 接收到的数据包，返回统一结构。

    Returns:
        {
            "header": {...},
            "body": {...},
            "purpose": str,
            "event_name": str | None,
            "is_event": bool,
            "is_command_response": bool
        }
    """
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        return None

    header = data.get("header", {})
    body = data.get("body", {})
    purpose = header.get("messagePurpose", "")

    return {
        "header": header,
        "body": body,
        "purpose": purpose,
        "event_name": header.get("eventName"),
        "is_event": purpose == "event",
        "is_command_response": purpose == "commandResponse"
    }
