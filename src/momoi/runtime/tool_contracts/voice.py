"""Voice delivery contract for configured TTS and supported channels."""

SEND_VOICE_TOOL_SPEC = {
    "name": "send_voice",
    "description": (
        '作为语音消息说出的一段完整文本。等待语音合成后，独立于 end_turn 开始交付。若重试后合成失败，则改用 send_bubbles 以文本回复。'
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "minLength": 1,
                "description": (
                    '要大声说出的完整段落。不要包含贴纸、反应图片或 emotion:// 指令。'
                ),
            },
        },
        "required": ["text"],
        "additionalProperties": False,
    },
}
