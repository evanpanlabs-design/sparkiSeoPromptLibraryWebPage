"""Five Keyword Strategy tools for the Skill Registry — V3.2."""

import yaml
from datetime import datetime, timezone
from pathlib import Path

from src.agent.skills.base import Skill, Parameter
from src.agent.skills.registry import SkillRegistry

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
QUERIES_YAML = PROJECT_ROOT / "configs" / "queries.yaml"


# ---------------------------------------------------------------------------
# Keyword Strategy Helper Functions (DevGuide §8B)
# ---------------------------------------------------------------------------

def get_active_keywords(db_conn, user_specified=None):
    """
    Keyword 优先级：
    1. 用户明确指定 → 直接返回用户指定
    2. 用户无指定 → 查 approved_keywords 表（状态=approved）
    3. 无已确认推荐 → 使用 configs/queries.yaml 的 seed_queries
    """
    if user_specified:
        return user_specified

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
    """将漏斗数据写入 keyword_yields 表（DevGuide §8B.2）。"""
    qualified_rate = qualified / raw if raw > 0 else 0.0
    db_conn.execute("""
        INSERT INTO keyword_yields
            (keyword, scrape_run_id, raw_tweets, filtered_tweets,
             extracted_prompts, qualified_prompts, yield_score, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [keyword, scrape_run_id, raw, filtered, extracted, qualified,
          qualified_rate, datetime.now(timezone.utc).isoformat()])
    db_conn.commit()


def _confirm_keywords_impl(db_conn, keywords: list[str], action: str, note=None) -> str:
    """
    确认或否决建议的关键词（DevGuide §8B.4）。
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


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def tool_analyze_keyword_yield(args: dict) -> str:
    """分析历史漏斗表现，返回各关键词的 raw/filtered/extracted/qualified 数量和比率。"""
    try:
        from src.memory.schema import _conn

        top_n = args.get("top_n", 10)
        scrape_run_id = args.get("scrape_run_id")

        conn = _conn()
        if scrape_run_id:
            rows = conn.execute("""
                SELECT keyword, raw_tweets, filtered_tweets, extracted_prompts,
                       qualified_prompts, yield_score
                FROM keyword_yields
                WHERE scrape_run_id = ?
                ORDER BY yield_score DESC
                LIMIT ?
            """, (scrape_run_id, top_n)).fetchall()
        else:
            rows = conn.execute("""
                SELECT keyword,
                       SUM(raw_tweets) as raw_tweets,
                       SUM(filtered_tweets) as filtered_tweets,
                       SUM(extracted_prompts) as extracted_prompts,
                       SUM(qualified_prompts) as qualified_prompts,
                       CASE WHEN SUM(raw_tweets) > 0
                            THEN CAST(SUM(qualified_prompts) AS REAL) / SUM(raw_tweets)
                            ELSE 0 END as yield_score
                FROM keyword_yields
                GROUP BY keyword
                ORDER BY yield_score DESC
                LIMIT ?
            """, (top_n,)).fetchall()

        if not rows:
            return "暂无漏斗数据（先跑一轮爬取）"

        lines = ["关键词漏斗分析（按综合漏斗率排序）:"]
        for r in rows:
            kw = r["keyword"]
            raw = r["raw_tweets"]
            filt = r["filtered_tweets"]
            ext = r["extracted_prompts"]
            qual = r["qualified_prompts"]
            score = r["yield_score"]
            lines.append(
                f"  {kw}: {raw} raw → {filt} filtered → {ext} extracted → {qual} qualified "
                f"(综合漏斗率: {score:.2%})"
            )
        return "\n".join(lines)

    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


def tool_generate_keyword_suggestions(args: dict) -> str:
    """基于历史漏斗表现生成新的关键词建议（需要用户确认后才能用于爬虫）。"""
    try:
        from src.memory.schema import _conn

        top_n = args.get("top_n", 5)
        based_on_high_yield = args.get("based_on_high_yield", True)

        conn = _conn()

        if based_on_high_yield:
            rows = conn.execute("""
                SELECT keyword,
                       CASE WHEN SUM(raw_tweets) > 0
                            THEN CAST(SUM(qualified_prompts) AS REAL) / SUM(raw_tweets)
                            ELSE 0 END as qualified_rate
                FROM keyword_yields
                GROUP BY keyword
                HAVING qualified_rate >= 0.05
                ORDER BY qualified_rate DESC
                LIMIT 10
            """).fetchall()
        else:
            rows = conn.execute("""
                SELECT DISTINCT keyword FROM keyword_yields
                ORDER BY keyword
                LIMIT 10
            """).fetchall()
            for r in rows:
                r["qualified_rate"] = 0.0

        suggestions = []
        seen = set()
        seed_rows = conn.execute("SELECT keyword FROM approved_keywords").fetchall()
        for sr in seed_rows:
            seen.add(sr["keyword"])

        for r in rows:
            base = r["keyword"] if isinstance(r, dict) and "keyword" in r else r[0]
            rate = r.get("qualified_rate", 0.0) if isinstance(r, dict) else 0.0

            for variant in [f"{base} 3.1", f"{base} experimental", f"AI {base}"]:
                if variant not in seen:
                    suggestions.append({
                        "suggested_keyword": variant,
                        "reason": f"基于 '{base}' (qualified rate {rate:.1%}) 扩展",
                        "based_on_keyword": base,
                    })
                    seen.add(variant)
                if len(suggestions) >= top_n:
                    break
            if len(suggestions) >= top_n:
                break

        if not suggestions:
            return "未能生成新建议，请先运行爬取积累数据"

        now = datetime.now(timezone.utc).isoformat()
        for s in suggestions:
            conn.execute("""
                INSERT OR IGNORE INTO keyword_suggestions
                    (suggested_keyword, reason, based_on_keyword, status, created_at)
                VALUES (?, ?, ?, 'pending', ?)
            """, [s["suggested_keyword"], s["reason"], s["based_on_keyword"], now])
        conn.commit()

        lines = ["建议新增关键词（待确认）:"]
        for i, s in enumerate(suggestions, 1):
            lines.append(f"  {i}. {s['suggested_keyword']} | {s['reason']}")
        return "\n".join(lines)

    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


def tool_confirm_keywords(args: dict) -> str:
    """用户确认/否决 AI 建议的关键词（确认后写入 approved_keywords 表，用于下次爬虫）。"""
    try:
        from src.memory.schema import _conn

        keywords = args.get("keywords", [])
        action = args.get("action", "confirm")
        note = args.get("note")

        if not keywords:
            return "错误: keywords 是必填的"

        conn = _conn()
        return _confirm_keywords_impl(conn, keywords, action, note)

    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


def tool_show_approved_keywords(args: dict) -> str:
    """查看当前已确认用于爬取的关键词列表。"""
    try:
        from src.memory.schema import _conn

        conn = _conn()
        rows = conn.execute("""
            SELECT keyword, source, approved_at, note
            FROM approved_keywords
            ORDER BY approved_at DESC
        """).fetchall()

        if not rows:
            return "暂无已确认的关键词"

        lines = [f"已确认用于爬取的关键词（共 {len(rows)} 个）:"]
        for i, r in enumerate(rows, 1):
            kw = r["keyword"]
            src = r["source"] or "seed"
            at = r["approved_at"][:10] if r["approved_at"] else "—"
            note = f" ({r['note']})" if r["note"] else ""
            lines.append(f"  {i}. {kw} ({src}, {at}){note}")
        return "\n".join(lines)

    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


def tool_crawl_with_keywords(args: dict) -> str:
    """使用指定关键词执行爬虫（优先级：用户指定 > 已确认推荐 > seed）。"""
    try:
        import subprocess
        from src.memory.schema import _conn

        keywords_arg = args.get("keywords")
        from_cache = args.get("from_cache", True)
        record_yield = args.get("record_yield", True)

        conn = _conn()

        active_kw = get_active_keywords(conn, keywords_arg)

        if not active_kw:
            return "错误: 没有可用的关键词"

        queries = keywords_arg if keywords_arg else active_kw

        cmd = [
            "python", "-m", "src.main", "run",
            "--queries", ",".join(queries) if queries else "",
        ]
        if from_cache:
            cmd.append("--from-cache")
        cmd = [c for c in cmd if c]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        output = result.stdout + result.stderr

        if record_yield:
            run_rows = conn.execute(
                "SELECT id FROM scrape_runs ORDER BY id DESC LIMIT 1"
            ).fetchall()
            if run_rows:
                scrape_run_id = run_rows[0]["id"]
                for kw in queries:
                    q_rows = conn.execute(
                        """SELECT tweets_raw, tweets_filtered, prompts_extracted, qualified
                           FROM queries WHERE scrape_run_id = ? AND text = ?""",
                        (scrape_run_id, kw)
                    ).fetchall()
                    if q_rows:
                        qr = q_rows[0]
                        record_keyword_yield(
                            conn, kw, scrape_run_id,
                            raw=qr["tweets_raw"],
                            filtered=qr["tweets_filtered"],
                            extracted=qr["prompts_extracted"],
                            qualified=qr["qualified"]
                        )

        lines = output.splitlines()
        summary = [l for l in lines if "prompts" in l.lower() or "tweets" in l.lower()]
        if summary:
            return f"爬取完成: {len(queries)} 个关键词 | " + " | ".join(summary[-3:])
        return f"爬取完成（查看日志获取详情）"

    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Skill registration
# ---------------------------------------------------------------------------

def register_keyword_tools(registry: "SkillRegistry") -> None:
    """Register all 5 keyword strategy tools into the given registry."""

    registry.register(Skill(
        name="analyze_keyword_yield",
        description="分析历史漏斗表现，返回各关键词的 raw/filtered/extracted/qualified 数量和比率",
        category="keyword_strategy",
        parameters=[
            Parameter("top_n", "integer", "返回数量，默认10", default=10),
            Parameter("scrape_run_id", "integer", "限定某次爬取（可选）", default=None),
        ],
        execute=tool_analyze_keyword_yield,
        examples=["分析关键词效果", "哪些关键词表现最好？"],
    ))

    registry.register(Skill(
        name="generate_keyword_suggestions",
        description="基于历史漏斗表现生成新的关键词建议（需要用户确认后才能用于爬虫）",
        category="keyword_strategy",
        parameters=[
            Parameter("top_n", "integer", "建议数量，默认5", default=5),
            Parameter("based_on_high_yield", "boolean", "是否基于高 yield 词扩展", default=True),
        ],
        execute=tool_generate_keyword_suggestions,
        examples=["有什么优化建议？", "推荐新的关键词"],
    ))

    registry.register(Skill(
        name="confirm_keywords",
        description="用户确认/否决 AI 建议的关键词（确认后写入 approved_keywords 表，用于下次爬虫）",
        category="keyword_strategy",
        parameters=[
            Parameter("keywords", "array", "确认的关键词列表", required=True),
            Parameter("action", "string", "confirm 或 reject", default="confirm"),
            Parameter("note", "string", "备注（可选）", default=None),
        ],
        execute=tool_confirm_keywords,
        examples=["确认 Veo 3.1 prompt 和 Google Veo experimental", "否决第2个建议"],
    ))

    registry.register(Skill(
        name="show_approved_keywords",
        description="查看当前已确认用于爬取的关键词列表",
        category="keyword_strategy",
        parameters=[],
        execute=tool_show_approved_keywords,
        examples=["当前有哪些已确认的关键词？", "看看活跃的关键词"],
    ))

    registry.register(Skill(
        name="crawl_with_keywords",
        description="使用指定关键词执行爬虫（优先级：用户指定 > 已确认推荐 > seed）",
        category="data_collection",
        parameters=[
            Parameter("keywords", "array", "使用的关键词列表（默认使用已确认的推荐关键词）", default=None),
            Parameter("from_cache", "boolean", "是否使用缓存", default=True),
            Parameter("record_yield", "boolean", "是否记录漏斗数据（默认 True）", default=True),
        ],
        execute=tool_crawl_with_keywords,
        examples=["用已确认的关键词跑一轮", "用 Veo 3 prompt 和 AI video cinematic 爬"],
    ))
