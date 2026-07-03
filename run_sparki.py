#!/usr/bin/env python
"""Wrapper that suppresses langgraph deprecation warning before running chat CLI.

Usage:
    python run_sparki.py
    python run_sparki.py --msg "池子状态"
"""
import warnings
import sys

# Suppress LangChainPendingDeprecationWarning before ANY other import
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=PendingDeprecationWarning)

# Attempt to patch warnings.warn to catch langgraph's custom warning class
_orig_warn = warnings.warn
def _patched_warn(message, category=None, **kwargs):
    cat_name = getattr(category, "__name__", str(category))
    if "LangChain" in cat_name or (isinstance(message, str) and "LangChain" in message):
        return
    return _orig_warn(message, category, **kwargs)
warnings.warn = _patched_warn

# Now run the chat CLI
if __name__ == "__main__":
    from src.agent.chat import main
    main()
