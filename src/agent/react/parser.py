"""LLM output parsers for ReAct node responses.

All parsers handle both Chinese and English output robustly.
Each returns a dict with documented keys; malformed input returns safe defaults.
"""

import json
import re
from typing import Any


def parse_think_response(response_text: str) -> dict[str, Any]:
    """Parse LLM think response into thought and intent_type.

    Expected format (either language):
        thought: ...
        intent_type: ...

    Args:
        response_text: Raw LLM output string.

    Returns:
        {"thought": str, "intent_type": str}
        Defaults: thought="", intent_type="TASK_EXECUTION"
    """
    text = response_text.strip()

    thought_match = re.search(
        r"(?:thought|thought[:\s]+\*?\s*)(.+?)(?:\n|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    intent_match = re.search(
        r"(?:intent_type|intent[:\s*])([A-Z_]+)",
        text,
        re.IGNORECASE,
    )

    thought = thought_match.group(1).strip() if thought_match else ""
    intent_type = intent_match.group(1).strip().upper() if intent_match else "TASK_EXECUTION"

    # Normalize intent_type
    valid_intents = {"STATUS_QUERY", "TASK_EXECUTION", "SEARCH", "MULTI_STEP", "CLARIFICATION", "CHITCHAT"}
    if intent_type not in valid_intents:
        intent_type = "TASK_EXECUTION"

    return {"thought": thought, "intent_type": intent_type}


def parse_plan_response(response_text: str) -> dict[str, Any]:
    """Parse LLM plan response into action dict or reply string.

    Expected formats (either language):
        action: {...}         (JSON dict with "tool" and "args")
        reply: <text>

    Args:
        response_text: Raw LLM output string.

    Returns:
        {"action": {"tool": str, "args": dict}}  OR  {"reply": str}
    """
    text = response_text.strip()

    # Try JSON action format first
    action_match = re.search(
        r"(?:action|action[:\s]+\*?\s*)({.*})",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if action_match:
        try:
            action_json = json.loads(action_match.group(1))
            if "tool" in action_json and "args" in action_json:
                return {"action": action_json}
        except json.JSONDecodeError:
            pass

    # Try key-based format: action: tool_name\nargs: {...}
    tool_match = re.search(
        r"(?:tool|tool_name)[:\s*]+([^\n]+)",
        text,
        re.IGNORECASE,
    )
    args_match = re.search(
        r"(?:args|parameters)[:\s\n]+(.*)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if tool_match:
        tool_name = tool_match.group(1).strip().strip('"\'')
        args = {}
        if args_match:
            try:
                args = json.loads(args_match.group(1).strip())
            except json.JSONDecodeError:
                args = {}
        return {"action": {"tool": tool_name, "args": args}}

    # Fallback: reply format
    reply_match = re.search(
        r"(?:reply|response|回复)[:\s]+\*?\s*(.+)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    reply = reply_match.group(1).strip() if reply_match else "好的，我明白了。"

    return {"reply": reply}


def parse_observe_response(response_text: str) -> dict[str, Any]:
    """Parse LLM observe response into continue flag and next_thought.

    Expected format (either language):
        continue: true/false
        next_thought: ...

    Args:
        response_text: Raw LLM output string.

    Returns:
        {"continue": bool, "next_thought": str}
        Defaults: continue=False, next_thought=""
    """
    text = response_text.strip()

    continue_match = re.search(
        r"continue[:\s*]+(true|false|是|否|继续|结束)",
        text,
        re.IGNORECASE,
    )
    next_thought_match = re.search(
        r"(?:next_thought|next|后续思考)[:\s*]+\*?\s*(.+)",
        text,
        re.IGNORECASE | re.DOTALL,
    )

    continue_flag = False
    if continue_match:
        val = continue_match.group(1).lower().strip()
        if val in ("true", "是", "继续"):
            continue_flag = True
        elif val in ("false", "否", "结束"):
            continue_flag = False

    next_thought = next_thought_match.group(1).strip() if next_thought_match else ""

    return {"continue": continue_flag, "next_thought": next_thought}
