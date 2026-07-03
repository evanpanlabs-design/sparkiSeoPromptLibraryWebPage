"""ReAct format helper functions.

These formatters convert internal data structures into human-readable
strings used in LLM prompts. All output is in Chinese.
"""

from typing import Any


def format_steps_for_prompt(steps: list[dict]) -> str:
    """Format a list of ReAct steps into a readable string for LLM prompts.

    Args:
        steps: List of step dicts, each containing:
            step_number, thought, action, observation (optional), result (optional)

    Returns:
        Multi-line string describing all completed steps.
    """
    if not steps:
        return "（暂无已完成的步骤）"

    lines = []
    for step in steps:
        step_num = step.get("step_number") or step.get("step") or 0
        thought = step.get("thought", "")
        action = step.get("action")
        observation = step.get("observation") or step.get("result") or ""

        lines.append(f"--- 第 {step_num} 步 ---")
        lines.append(f"思考：{thought}")

        if action:
            tool = action.get("tool", "unknown")
            args = action.get("args", {})
            if isinstance(args, dict) and args:
                args_str = ", ".join(f"{k}={v}" for k, v in args.items())
                lines.append(f"动作：{tool}({args_str})")
            else:
                lines.append(f"动作：{tool}")

        if observation:
            obs_text = str(observation)
            if len(obs_text) > 200:
                obs_text = obs_text[:200] + "..."
            lines.append(f"观察：{obs_text}")

        lines.append("")

    return "\n".join(lines)


def format_pool_summary(pool_summary: Any) -> str:
    """Format a PoolSummary object into a readable string.

    Args:
        pool_summary: PoolSummary dataclass or dict with fields:
            pending, done, failed (and optionally tweets_collected, prompts_extracted)

    Returns:
        Human-readable string describing pool status.
    """
    if pool_summary is None:
        return "池子状态：未知"

    # Support both object attributes and dict keys
    if hasattr(pool_summary, "__dict__"):
        pending = getattr(pool_summary, "pending", 0)
        done = getattr(pool_summary, "done", 0)
        failed = getattr(pool_summary, "failed", 0)
        tweets = getattr(pool_summary, "tweets_collected", None)
        prompts = getattr(pool_summary, "prompts_extracted", None)
    else:
        pending = pool_summary.get("pending", 0) if isinstance(pool_summary, dict) else 0
        done = pool_summary.get("done", 0) if isinstance(pool_summary, dict) else 0
        failed = pool_summary.get("failed", 0) if isinstance(pool_summary, dict) else 0
        tweets = pool_summary.get("tweets_collected", None) if isinstance(pool_summary, dict) else None
        prompts = pool_summary.get("prompts_extracted", None) if isinstance(pool_summary, dict) else None

    parts = [f"待处理：{pending}，已完成：{done}，失败：{failed}"]
    if tweets is not None:
        parts.append(f"已爬取推文：{tweets}")
    if prompts is not None:
        parts.append(f"已提取 Prompt：{prompts}")

    return "池子状态：" + "，".join(parts)


def format_history(recent_history: list[dict]) -> str:
    """Format recent conversation history into a readable string.

    Args:
        recent_history: List of message dicts, each containing:
            role ("user" or "assistant"), content (str)

    Returns:
        Multi-line string describing the recent conversation.
    """
    if not recent_history:
        return "（无历史对话）"

    lines = []
    for msg in recent_history[-20:]:  # Last 20 messages
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if not content:
            continue

        if role == "user":
            label = "用户"
        elif role == "assistant":
            label = "助手"
        else:
            label = role

        # Truncate long messages
        if len(content) > 150:
            content = content[:150] + "..."

        lines.append(f"{label}：{content}")

    return "\n".join(lines) if lines else "（无历史对话）"
