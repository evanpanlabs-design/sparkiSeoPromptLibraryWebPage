"""CLI entry point for Sparki V3 ReAct Agent.

Supports two modes:
  python -m src.agent.chat          → interactive REPL
  python -m src.agent.chat --msg X  → single command, print reply, exit
"""

import argparse
import os

# Suppress LangChainPendingDeprecationWarning before any langgraph import
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGCHAIN_WARNING"] = "false"

from src.agent.skills.registry import SkillRegistry
from src.agent.skills.core_tools import register_core_tools
from src.agent.chat_agent import SparkiReActAgent
from src.memory.schema import init_db
from src.llm.gemini_client import GeminiClient


# Commands that need confirmation (no slash prefix)
_EXIT_COMMANDS = {"exit", "退出", "quit"}


def _confirm_exit() -> bool:
    """Ask user to confirm exit. Returns True if should exit."""
    while True:
        reply = input("是否确认退出? (Y/N): ").strip().upper()
        if reply == "Y":
            return True
        if reply in ("N", ""):
            return False
        print("请输入 Y 或 N")


def main() -> None:
    parser = argparse.ArgumentParser(prog="sparki", description="Sparki V3 ReAct Agent CLI")
    parser.add_argument(
        "--msg", "-m",
        metavar="MSG",
        help="Single message mode — agent prints reply and exits",
    )
    parser.add_argument(
        "--max-history",
        type=int,
        default=20,
        help="Max history entries to show (default 20)",
    )
    args = parser.parse_args()

    # ── Build skill registry ─────────────────────────────────────────────────
    skill_registry = SkillRegistry()
    register_core_tools(skill_registry)

    # ── Build LLM ───────────────────────────────────────────────────────────
    llm = GeminiClient(
        project="sparki-op",
        location="global",
        default_model="gemini-3.5-flash",
    )

    # ── Init DB ─────────────────────────────────────────────────────────────
    db_conn = init_db()

    # ── Create agent ────────────────────────────────────────────────────────
    agent = SparkiReActAgent(
        llm=llm,
        db_conn=db_conn,
        skill_registry=skill_registry,
    )

    # ── Run ──────────────────────────────────────────────────────────────────
    if args.msg:
        result = agent.run(args.msg)
        print(result)
        return

    print("Sparki Crawl&Visualize ReAct Agent v3.0")
    print("输入 /help 查看命令, /quit 退出\n")

    while True:
        user_input = input("\n你: ").strip()
        if not user_input:
            continue

        # Built-in slash commands
        if user_input == "/quit":
            break
        if user_input == "/history":
            for t in agent.get_history(limit=args.max_history):
                print(f"[{t['role']}]: {t['content'][:80]}")
            continue
        if user_input == "/help":
            print("可用命令: /quit 退出, /history 查看历史")
            continue

        # Bare exit/退出 — ask for confirmation
        if user_input.lower() in _EXIT_COMMANDS:
            if _confirm_exit():
                print("感谢使用，再见！")
                break
            print("好的，继续对话。")
            continue

        result = agent.run(user_input)
        print(f"\nSparki: {result}")


if __name__ == "__main__":
    main()