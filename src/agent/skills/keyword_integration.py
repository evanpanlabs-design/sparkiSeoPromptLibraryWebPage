"""Keyword Strategy integration functions — priority logic, funnel recording, suggestions."""

import yaml
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
QUERIES_YAML = PROJECT_ROOT / "configs" / "queries.yaml"


def get_active_keywords(db_conn, user_specified_keywords=None):
    """
    Keyword 优先级：
    1. 用户明确指定 → 直接返回用户指定
    2. 用户无指定 → 查 approved_keywords 表
    3. 无已确认推荐 → 使用 configs/queries.yaml 的 seed_queries
    """
    if user_specified_keywords:
        return user_specified_keywords

    approved = db_conn.execute(
        "SELECT keyword FROM approved_keywords ORDER BY approved_at DESC"
    ).fetchall()
    if approved:
        return [r["keyword"] for r in approved]

    with open(QUERIES_YAML, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("queries", [])


def record_keyword_yield(db_conn, keyword: str, scrape_run_id: int,
                          raw: int, filtered: int,
                          extracted: int, qualified: int) -> None:
    """将漏斗数据写入 keyword_yields 表。"""
    qualified_rate = qualified / raw if raw > 0 else 0.0
    yield_score = qualified_rate  # yield_score = qualified_rate 口径一致
    db_conn.execute("""
        INSERT INTO keyword_yields
            (keyword, scrape_run_id, raw_tweets, filtered_tweets,
             extracted_prompts, qualified_prompts, qualified_rate, yield_score, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [keyword, scrape_run_id, raw, filtered, extracted, qualified,
          qualified_rate, yield_score, datetime.now(timezone.utc).isoformat()])
    db_conn.commit()


def get_keyword_suggestions(db_conn, top_n: int = 10) -> list[dict]:
    """返回待确认的关键词建议（从 keyword_suggestions 表）。"""
    rows = db_conn.execute("""
        SELECT suggested_keyword, reason, based_on_keyword, created_at
        FROM keyword_suggestions
        WHERE status = 'pending'
        ORDER BY created_at DESC
        LIMIT ?
    """, (top_n,)).fetchall()

    return [
        {
            "suggested_keyword": r["suggested_keyword"],
            "reason": r["reason"] or "",
            "based_on_keyword": r["based_on_keyword"] or "",
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def confirm_keywords(db_conn, keywords: list[str], action: str, note: str = None) -> str:
    """
    确认或否决建议的关键词。
    action='confirm' → 写入 approved_keywords
    action='reject' → 标记 keyword_suggestions.status='rejected'
    """
    if action == "confirm":
        now = datetime.now(timezone.utc).isoformat()
        for kw in keywords:
            db_conn.execute("""
                INSERT OR REPLACE INTO approved_keywords (keyword, source, approved_at, note)
                VALUES (?, 'agent_recommendation', ?, ?)
            """, [kw, now, note])
        db_conn.commit()
        return f"已确认 {len(keywords)} 个关键词：{keywords}"
    elif action == "reject":
        for kw in keywords:
            db_conn.execute(
                "UPDATE keyword_suggestions SET status='rejected' WHERE suggested_keyword=?",
                [kw]
            )
        db_conn.commit()
        return f"已否决 {len(keywords)} 个建议：{keywords}"
    return f"未知 action: {action}，支持 confirm / reject"
