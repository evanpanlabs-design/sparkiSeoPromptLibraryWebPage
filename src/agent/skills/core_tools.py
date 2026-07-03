"""Twelve core phase skills for the Skill Registry (V3.2).

Replaces tool_crawl with 5 independent phase skills:
  crawl_tweets, extract_prompts, score_prompts, sync_images, build_html
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.agent.skills.base import Skill, Parameter

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
OUTPUT_PATH = PROJECT_ROOT / "outputs" / "index.html"


# ---------------------------------------------------------------------------
# 1. crawl_tweets — direct Apify API, no src.main run
# ---------------------------------------------------------------------------

def tool_crawl_tweets(args: dict) -> str:
    """Crawl X.com tweets via Apify API and write tweets to DB.

    Args:
        queries: list of search keywords (default from configs/queries.yaml)
        from_cache: bool, skip crawl if True (default False for phase skill)
        max_cost: float, max cost per query in USD (default 0.10)
        max_items: int, max tweets per query (Apify maxItems, default 500)
        sort: str, sort order — "Latest + Top" | "Latest" | "Top" (default "Latest + Top")
        include_search_terms: bool, include searchTerms in results (default False)
    """
    try:
        import os
        import yaml
        from src.crawler.apify import ApifyCrawler
        from src.memory.schema import _conn

        queries = args.get("queries")
        if queries is None:
            with open("configs/queries.yaml", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            queries = cfg.get("queries", [])

        if not queries:
            return "错误: 没有配置搜索关键词，请检查 configs/queries.yaml"

        from_cache = args.get("from_cache", False)
        max_cost = float(args.get("max_cost", 0.10))
        max_items = int(args.get("max_items", 500))
        sort = str(args.get("sort", "Latest + Top"))
        include_search_terms = bool(args.get("include_search_terms", False))

        if from_cache:
            return "爬取完成: 使用缓存模式，跳过实际爬取（from_cache=True）"

        # Load Apify config
        with open("configs/crawler.yaml", encoding="utf-8") as f:
            crawler_cfg = yaml.safe_load(f)
        apify_cfg = crawler_cfg.get("apify", {})
        actor_id = apify_cfg.get("actor_id", "nfp1fpt5gUlBwPcor")
        api_token_env = apify_cfg.get("api_token_env", "APIFY_API_TOKEN")
        api_token = os.environ.get(api_token_env, "")

        crawler = ApifyCrawler(
            actor_id=actor_id,
            api_token=api_token,
            timeout_ms=apify_cfg.get("timeout_ms", 600_000),
            max_retries=apify_cfg.get("max_retries", 2),
            retry_delay_s=apify_cfg.get("retry_delay_s", 30),
        )

        conn = _conn()
        total_tweets = 0

        for query in queries:
            tweets = asyncio.run(crawler.crawl(
                query,
                max_cost_usd=max_cost,
                max_items=max_items,
                sort=sort,
                include_search_terms=include_search_terms,
            ))
            total_tweets += len(tweets)

            from datetime import datetime, timezone

            now = datetime.now(timezone.utc).isoformat()
            for tw in tweets:
                author = tw.get("author") or {}
                conn.execute(
                    """
                    INSERT OR REPLACE INTO tweets
                    (tweet_id, url, text, short_text, author_name, author_screen,
                     author_followers, likes_count, retweet_count, reply_count,
                     view_count, scraped_at, detail_enriched, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tw.get("tweet_id", ""),
                        tw.get("url", ""),
                        tw.get("text", ""),
                        tw.get("short_text", ""),
                        author.get("name", ""),
                        author.get("screen_name", ""),
                        author.get("followers_count", 0),
                        tw.get("favorite_count", 0),
                        tw.get("retweet_count", 0),
                        tw.get("reply_count", 0),
                        tw.get("view_count", 0),
                        tw.get("scraped_at", ""),
                        0,
                        now,
                    ),
                )
            conn.commit()

        return (
            f"爬取完成: {total_tweets} tweets, {len(queries)} queries\n"
            f"写入 DB 完成，待 extract_prompts 阶段处理"
        )

    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# 2. extract_prompts — LLM extraction from DB tweets
# ---------------------------------------------------------------------------

def tool_extract_prompts(args: dict) -> str:
    """Extract prompts from tweets in DB that have no prompt_text.

    Args:
        batch: int, max tweets to process (default 50)
    """
    try:
        import os
        from src.memory.schema import _conn
        from src.llm.gemini_client import GeminiClient
        from src.worker.extractor import PromptExtractor, build_extracted_prompt
        from src.types.tweet import Tweet, AuthorRef

        batch = int(args.get("batch", 50))

        conn = _conn()
        rows = conn.execute(
            """
            SELECT tweet_id, url, text, short_text, author_name, author_screen,
                   author_followers, likes_count, retweet_count, reply_count,
                   view_count
            FROM tweets
            WHERE prompt_text IS NULL
            ORDER BY likes_count DESC
            LIMIT ?
            """,
            (batch,),
        ).fetchall()

        if not rows:
            return "提取完成: 0/0 — 没有需要提取的推文"

        # Build LLM client — Gemini via Vertex AI
        from src.llm.gemini_client import GeminiClient
        llm = GeminiClient()

        # Categories from DB
        cat_rows = conn.execute("SELECT name FROM categories").fetchall()
        categories = [r["name"] for r in cat_rows] if cat_rows else ["video-generation", "cinematic", "other"]

        extractor = PromptExtractor(llm, categories=categories)

        extracted = 0
        skipped = 0

        for row in rows:
            tweet = Tweet(
                tweet_id=str(row["tweet_id"]),
                url=row["url"] or "",
                text=row["text"] or row["short_text"] or "",
                short_text=row["short_text"] or "",
                author=AuthorRef(
                    name=row["author_name"] or "unknown",
                    screen_name=row["author_screen"] or "unknown",
                    profile_url=f"https://x.com/{row['author_screen']}",
                    followers_count=int(row["author_followers"] or 0),
                ),
                favorite_count=int(row["likes_count"] or 0),
                retweet_count=int(row["retweet_count"] or 0),
                reply_count=int(row["reply_count"] or 0),
                view_count=int(row["view_count"] or 0),
                scraped_at="",
            )

            result = extractor.extract(tweet)
            if not result.is_prompt:
                skipped += 1
                continue

            prompt_obj, _ = build_extracted_prompt(
                tweet=tweet,
                result=result,
                known_categories=set(categories),
            )

            conn.execute(
                """
                UPDATE tweets SET
                    prompt_text = ?,
                    category = ?,
                    title = ?,
                    notes = ?
                WHERE tweet_id = ?
                """,
                (
                    prompt_obj.prompt_text,
                    prompt_obj.category,
                    prompt_obj.title,
                    prompt_obj.notes,
                    tweet.tweet_id,
                ),
            )

            # Insert into prompts table
            conn.execute(
                """
                INSERT OR REPLACE INTO prompts
                (tweet_id, url, category, title, prompt_text, notes,
                 author_name, author_screen, author_followers,
                 likes_count, retweet_count, reply_count, view_count,
                 extracted_at, image_status, quality_scores)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL)
                """,
                (
                    tweet.tweet_id,
                    tweet.url,
                    prompt_obj.category,
                    prompt_obj.title,
                    prompt_obj.prompt_text,
                    prompt_obj.notes,
                    tweet.author.name,
                    tweet.author.screen_name,
                    tweet.author.followers_count,
                    tweet.favorite_count,
                    tweet.retweet_count,
                    tweet.reply_count,
                    tweet.view_count,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            extracted += 1

        conn.commit()

        return f"提取完成: {extracted}/{len(rows)} prompts extracted（跳过 {skipped} 条非 Prompt 推文）"

    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# 3. score_prompts — quality scoring + filtering
# ---------------------------------------------------------------------------

def tool_score_prompts(args: dict) -> str:
    """Score quality of extracted prompts and filter by minimum score.

    Args:
        batch: int, max prompts to score (default 50)
        min_score: float, minimum overall score to qualify (default 0.4)
    """
    try:
        from src.memory.schema import _conn
        from src.llm.gemini_client import GeminiClient
        from src.worker.scorer import QualityScorer
        from src.types.prompt import ExtractedPrompt
        from src.types.config import QualityConfig, QualityWeights, QualityThresholds

        batch = int(args.get("batch", 50))
        min_score = float(args.get("min_score", 0.4))

        conn = _conn()
        rows = conn.execute(
            """
            SELECT id, tweet_id, url, category, title, prompt_text, notes,
                   author_name, author_screen, author_followers,
                   likes_count, retweet_count, reply_count, view_count
            FROM prompts
            WHERE quality_scores IS NULL AND prompt_text IS NOT NULL
            ORDER BY likes_count DESC
            LIMIT ?
            """,
            (batch,),
        ).fetchall()

        if not rows:
            return f"评分完成: 0 qualified（没有待评分的 prompts）"

        llm = GeminiClient()

        quality_cfg = QualityConfig(
            weights=QualityWeights(),
            thresholds=QualityThresholds(min_overall=min_score),
        )
        scorer = QualityScorer(llm, quality_cfg)

        qualified = 0
        unqualified = 0

        for row in rows:
            prompt_obj = ExtractedPrompt(
                id=row["id"],
                tweet_id=str(row["tweet_id"]),
                url=row["url"] or "",
                category=row["category"] or "other",
                title=row["title"] or "",
                prompt_text=row["prompt_text"] or "",
                notes=row["notes"] or "",
                author_name=row["author_name"] or "unknown",
                author_screen=row["author_screen"] or "unknown",
                author_followers=int(row["author_followers"] or 0),
                likes_count=int(row["likes_count"] or 0),
                retweet_count=int(row["retweet_count"] or 0),
                reply_count=int(row["reply_count"] or 0),
                view_count=int(row["view_count"] or 0),
                extracted_at="",
                quality_scores=None,
                needs_image=True,
            )

            scores = scorer.score(prompt_obj)
            scores_json = (
                f"{scores.specificity},{scores.visual_detail},"
                f"{scores.novelty},{scores.generatable},{scores.overall}"
            )

            conn.execute(
                "UPDATE prompts SET quality_scores = ? WHERE id = ?",
                (scores_json, row["id"]),
            )

            if scores.overall >= min_score:
                qualified += 1
            else:
                unqualified += 1

        conn.commit()

        return (
            f"评分完成: {qualified}/{qualified + unqualified} qualified "
            f"（min={min_score}，batch={batch}）"
        )

    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# 4. sync_images — GCS → generated_images/
# ---------------------------------------------------------------------------

def tool_sync_images(args: dict) -> str:
    """Sync cover images from GCS to local generated_images/ directory.

    Reads prompts with image_status='done' and image_gcs_url from DB.
    Copies images from outputs/images/{cat}/{yyyy-mm}/ to generated_images/{id}.png.
    """
    try:
        # Import the sync function from sync_images_from_gcs.py
        sys.path.insert(0, str(PROJECT_ROOT))
        from scripts.sync_images_from_gcs import download_all
        from scripts.build_html import _sync_images_to_flat_dir

        # Step 1: Download from GCS to outputs/images/{cat}/{yyyy-mm}/
        gcs_stats = download_all(dry_run=False, limit=None)

        # Step 2: Copy to flat generated_images/ directory
        img_stats = _sync_images_to_flat_dir()

        return (
            f"Images: {img_stats['copied']} copied, "
            f"{img_stats['skipped']} skipped, "
            f"{img_stats['errors']} errors"
        )

    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# 5. build_html — DB + template → outputs/index.html
# ---------------------------------------------------------------------------

def tool_build_html(args: dict) -> str:
    """Build HTML from done prompts.

    Args:
        category: str, filter by category (optional)
        min_score: float, minimum quality score (optional)
        sync_images: bool, whether to sync images first (default True)
        limit: int, max number of prompts (optional)
    """
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from scripts.build_html import build, sync_images_to_flat_dir

        category = args.get("category")
        min_score = args.get("min_score")
        sync_images = bool(args.get("sync_images", True))
        limit = args.get("limit")

        if sync_images:
            _ = sync_images_to_flat_dir()

        stats = build(
            sync_images=False,  # already synced above
            category=category,
            min_score=min_score,
            limit=limit,
        )

        return f"Built HTML: {stats.get('total_prompts', 0)} prompts"

    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Existing tools (unchanged — parameters updated for 2 tools only)
# ---------------------------------------------------------------------------

def tool_pool_status(args: dict) -> str:
    """Query prompt pool status counts by image_status."""
    try:
        from src.memory.schema import _conn

        conn = _conn()
        rows = conn.execute(
            "SELECT image_status, COUNT(*) as cnt FROM prompts GROUP BY image_status"
        ).fetchall()

        status_counts: dict[str, int] = {}
        for row in rows:
            status_counts[row["image_status"] or "pending"] = row["cnt"]

        labels = ["pending", "generating", "done", "failed", "published"]
        parts = []
        for label in labels:
            cnt = status_counts.get(label, 0)
            parts.append(f"  {label:12s}: {cnt:4d}")

        total = sum(status_counts.values())
        parts.append(f"  {'─' * 18}")
        parts.append(f"  {'总计':12s}: {total:4d}")
        return "Prompt Pool 状态:\n" + "\n".join(parts)

    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


def tool_search_prompts(args: dict) -> str:
    """Semantic search prompts via embeddings (placeholder until Code-4)."""
    try:
        top_k = args.get("top_k", 5)
        min_score = args.get("min_score")

        try:
            from src.agent.memory.embedding import search_prompts as _search
            from src.memory.schema import _conn

            conn = _conn()
            results = _search(conn, query=args.get("query", ""), top_k=top_k)
            if not results:
                return f"未找到相关Prompt（关键词: {args.get('query')}）"

            lines = [f"找到 {len(results)} 条相关Prompt（按相关性排序）:"]
            for i, r in enumerate(results, 1):
                score = r.get("score", 0.0)
                if min_score and score < min_score:
                    continue
                text = r.get("prompt_text", "")
                # Truncate: prefer newline boundary, then word boundary, then char limit
                if len(text) > 200:
                    # Try to break at newline first
                    truncated = ""
                    remaining = text
                    while remaining:
                        line_end = remaining.find("\n")
                        if line_end == -1:
                            line_end = len(remaining)
                        line = remaining[:line_end]
                        if len(truncated) + len(line) + 1 <= 200:
                            truncated += ("\n" if truncated else "") + line
                            if line_end < len(remaining):
                                remaining = remaining[line_end + 1:]
                            else:
                                break
                        else:
                            # This line would overflow — break at word boundary
                            if truncated:
                                break
                            else:
                                # No newline fit, hard char截断
                                truncated = remaining[:200].rstrip()
                                break
                    text = truncated.rstrip() + "..." if len(truncated) < len(text) else text
                lines.append(f"  {i}. [{score:.2f}] {text}")
            return "\n".join(lines)
        except (ImportError, AttributeError):
            return "Embedding搜索暂不可用（等待Code-4实现），请稍后再试。"

    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


def tool_generate_images(args: dict) -> str:
    """Generate cover images for pending prompts."""
    try:
        from src.memory.schema import _conn
        from src.image_gen.generator import RateLimitSafeGenerator

        batch = args.get("batch", 8)  # changed default from 0 to 8
        sort_by = args.get("sort_by", "score")
        filter_dict = args.get("filter")

        conn = _conn()
        sql = "SELECT id, prompt_text, category FROM prompts WHERE image_gcs_url IS NULL AND image_status = 'pending'"
        params: list[Any] = []

        if filter_dict and filter_dict.get("min_score"):
            sql += " AND CAST(quality_scores AS REAL) >= ?"
            params.append(filter_dict["min_score"])

        if sort_by == "score":
            sql += " ORDER BY CAST(quality_scores AS REAL) DESC"
        elif sort_by == "newest":
            sql += " ORDER BY id DESC"

        if batch > 0:
            sql += f" LIMIT {batch}"
        rows = conn.execute(sql, params).fetchall()

        if not rows:
            return "没有需要生成图片的pending prompt"

        generator = RateLimitSafeGenerator(
            max_workers=args.get("max_workers", 3),
            max_retries=3,
            retry_delay_base=2.0,
        )

        items = [
            {
                "prompt_id": row["id"],
                "prompt_text": row["prompt_text"],
                "category": row["category"],
            }
            for row in rows
        ]

        results = generator.generate_batch(items)

        success, failed = 0, 0
        total = len(results)
        done = 0
        result_map = {r["prompt_id"]: r for r in results}

        for row in rows:
            done += 1
            result = result_map.get(row["id"])
            if result and result.get("gcs_url"):
                conn.execute(
                    "UPDATE prompts SET image_gcs_url = ?, image_status = 'done' WHERE id = ?",
                    (result["gcs_url"], row["id"]),
                )
                success += 1
                model_tag = f"[{result.get('model_used', '')}]" if result.get('model_used') else ''
                print(f"  [{done}/{total}] OK   id={row['id']} cat={row['category']} {model_tag}")
            else:
                err = result.get("error", "unknown") if result else "unknown"
                conn.execute(
                    "UPDATE prompts SET image_status = 'failed' WHERE id = ?",
                    (row["id"],),
                )
                failed += 1
                print(f"  [{done}/{total}] FAIL id={row['id']} cat={row['category']} err={err[:60]}")

        conn.commit()

        total_cnt = conn.execute("SELECT COUNT(*) as cnt FROM prompts").fetchone()["cnt"]
        pending = conn.execute(
            "SELECT COUNT(*) as cnt FROM prompts WHERE image_status = 'pending'"
        ).fetchone()["cnt"]
        done_cnt = conn.execute(
            "SELECT COUNT(*) as cnt FROM prompts WHERE image_status = 'done'"
        ).fetchone()["cnt"]
        failed_cnt = conn.execute(
            "SELECT COUNT(*) as cnt FROM prompts WHERE image_status = 'failed'"
        ).fetchone()["cnt"]

        return (
            f"图片生成完成: {success}/{success + failed} 成功, {failed}/{success + failed} 失败\n"
            f"模型: gemini-2.5-flash-image\n"
            f"当前池: {pending} pending, {done_cnt} done, {failed_cnt} failed"
        )

    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


def tool_retry_failed(args: dict) -> str:
    """Retry image generation for failed prompts."""
    try:
        from src.memory.schema import _conn
        from src.image_gen.generator import RateLimitSafeGenerator

        batch = args.get("batch", 8)

        conn = _conn()
        rows = conn.execute(
            "SELECT id, prompt_text, category FROM prompts WHERE image_status = 'failed' LIMIT ?",
            (batch,),
        ).fetchall()

        if not rows:
            return "没有需要重试的failed prompt"

        ids = [r["id"] for r in rows]
        placeholders = ",".join(["?"] * len(ids))
        conn.execute(
            f"UPDATE prompts SET image_status = 'pending' WHERE id IN ({placeholders})",
            ids,
        )
        conn.commit()

        generator = RateLimitSafeGenerator()
        success, failed = 0, 0

        for row in rows:
            try:
                gcs_url = generator.generate(
                    prompt=row["prompt_text"],
                    category=row["category"],
                    prompt_id=row["id"],
                )
                if gcs_url:
                    conn.execute(
                        "UPDATE prompts SET image_gcs_url = ?, image_status = 'done' WHERE id = ?",
                        (gcs_url, row["id"]),
                    )
                    success += 1
                else:
                    conn.execute(
                        "UPDATE prompts SET image_status = 'failed' WHERE id = ?",
                        (row["id"],),
                    )
                    failed += 1
            except Exception:
                conn.execute(
                    "UPDATE prompts SET image_status = 'failed' WHERE id = ?",
                    (row["id"],),
                )
                failed += 1

        conn.commit()

        pending = conn.execute(
            "SELECT COUNT(*) as cnt FROM prompts WHERE image_status = 'pending'"
        ).fetchone()["cnt"]
        done_cnt = conn.execute(
            "SELECT COUNT(*) as cnt FROM prompts WHERE image_status = 'done'"
        ).fetchone()["cnt"]
        failed_cnt = conn.execute(
            "SELECT COUNT(*) as cnt FROM prompts WHERE image_status = 'failed'"
        ).fetchone()["cnt"]

        return (
            f"已重置 {len(rows)} 条 failed → pending\n"
            f"图片生成完成: {success}/{success + failed} 成功, {failed}/{success + failed} 失败\n"
            f"当前池: {pending} pending, {done_cnt} done, {failed_cnt} failed"
        )

    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


def tool_publish(args: dict) -> str:
    """Build HTML + sync images + push to GitHub Pages.

    Args:
        category: only this category
        min_score: minimum quality score filter
        repo: git repo path to push (default: PROJECT_ROOT/.git)
        message: commit message
    """
    repo = args.get("repo", str(PROJECT_ROOT / ".git"))
    commit_msg = args.get("message", "Update prompt library")

    # Build HTML (includes sync_images via --sync-images flag)
    build_r = subprocess.run(
        ["python", "scripts/build_html.py", "--sync-images"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    if build_r.returncode != 0:
        return f"HTML build failed: {build_r.stderr}"

    output_lines = build_r.stdout.strip().splitlines()
    built_count = 0
    for line in output_lines:
        if "total_prompts" in line:
            try:
                # Parse "Done: index=1, details=154, total_prompts=154"
                import re as _re
                m = _re.search(r"total_prompts=(\d+)", line)
                if m:
                    built_count = int(m.group(1))
            except Exception:
                pass

    # Git add + commit + push — add all outputs (index, 404, prompts/, sitemap, generated_images)
    html_path = OUTPUT_PATH.relative_to(PROJECT_ROOT)
    outputs_dir = str(OUTPUT_PATH.parent.relative_to(PROJECT_ROOT))
    try:
        # Add the entire outputs/ directory (index.html, 404.html, prompts/, sitemap.xml, generated_images/)
        subprocess.run(["git", "add", outputs_dir], cwd=repo, check=True)

        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        push_r = subprocess.run(
            ["git", "push", "origin", "gh-pages"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        push_ok = push_r.returncode == 0
    except Exception as e:
        return f"Git operations failed: {e}\nBuild succeeded with {built_count} prompts."

    return (
        f"发布完成! {built_count} 条 Prompt\n"
        f"HTML: {OUTPUT_PATH}\n"
        f"Git: {'OK' if push_ok else 'failed - check repo'}"
    )


def tool_show_history(args: dict) -> str:
    """Show recent task execution history."""
    try:
        from src.memory.schema import _conn

        limit = args.get("limit", 5)
        include_conv = args.get("include_conversation", True)

        conn = _conn()
        rows = conn.execute(
            """
            SELECT id, description, result_summary, created_at, completed_at
            FROM task_history
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        if not rows:
            return f"最近 {limit} 次运行:（暂无历史记录）"

        lines = [f"最近 {len(rows)} 次运行:"]
        for row in rows:
            desc = row["description"] or "—"
            created = row["created_at"][:16] if row["created_at"] else "—"
            lines.append(f"  #{row['id']} | {created} | {desc[:30]}")

        if include_conv:
            conv_rows = conn.execute(
                """
                SELECT role, content, created_at FROM conversation_history
                ORDER BY created_at DESC LIMIT 10
                """
            ).fetchall()
            if conv_rows:
                lines.append("\n最近对话:")
                for cr in conv_rows[:5]:
                    role = cr["role"]
                    content = cr["content"][:60] if cr["content"] else "—"
                    ts = cr["created_at"][:16] if cr["created_at"] else "—"
                    lines.append(f"  [{role}] {ts}: {content}...")

        return "\n".join(lines)

    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


def tool_save_preference(args: dict) -> str:
    """Save a user preference to the database."""
    try:
        from src.memory.schema import _conn
        from datetime import datetime, timezone

        key = args.get("key")
        value = args.get("value")

        if not key or value is None:
            return "错误: key 和 value 都是必填的"

        conn = _conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO user_preferences (key, value, updated_at) VALUES (?, ?, ?)",
            (key, str(value), now),
        )
        conn.commit()

        return f"已保存: {key} = {value}"

    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


def tool_get_preference(args: dict) -> str:
    """Retrieve a user preference from the database."""
    try:
        from src.memory.schema import _conn

        key = args.get("key")
        if not key:
            return "错误: key 是必填的"

        conn = _conn()
        row = conn.execute(
            "SELECT key, value FROM user_preferences WHERE key = ?", (key,)
        ).fetchone()

        if not row:
            return f"未找到偏好: {key}"

        return f"{row['key']} = {row['value']}"

    except Exception as e:
        return f"错误: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Core skills registration — 12 skills
# ---------------------------------------------------------------------------


def register_core_tools(registry: "SkillRegistry") -> None:
    """Register all 12 core skills into the given registry."""

    # 1. crawl_tweets (NEW — replaces tool_crawl)
    registry.register(Skill(
        name="crawl_tweets",
        description="从 X.com 爬取推文，直接调用 Apify API，将结果写入 DB",
        category="data_collection",
        parameters=[
            Parameter("queries", "array", "搜索关键词列表，默认使用 configs/queries.yaml", default=None),
            Parameter("from_cache", "boolean", "跳过爬取（仅返回提示）", default=False),
            Parameter("max_cost", "float", "每查询最大消费 USD，默认 0.10", default=0.10),
            Parameter("max_items", "integer", "每次爬取最大条数（Apify maxItems），默认 500", default=500),
            Parameter("sort", "string", "排序方式：Latest + Top / Latest / Top，默认 Latest + Top", default="Latest + Top"),
            Parameter("include_search_terms", "boolean", "是否在结果中包含搜索关键词，默认 False", default=False),
        ],
        execute=tool_crawl_tweets,
        examples=["爬取最新推文", "用新关键词跑一轮 crawl"],
    ))

    # 2. extract_prompts (NEW)
    registry.register(Skill(
        name="extract_prompts",
        description="从 DB 中无 prompt_text 的推文提取 Prompt（LLM 分析）",
        category="data_collection",
        parameters=[
            Parameter("batch", "integer", "最大处理条数，默认 50", default=50),
        ],
        execute=tool_extract_prompts,
        examples=["提取前50条prompt", "跑一遍 extract 阶段"],
    ))

    # 3. score_prompts (NEW)
    registry.register(Skill(
        name="score_prompts",
        description="对提取的 Prompts 做质量评分，过滤低于阈值的",
        category="data_collection",
        parameters=[
            Parameter("batch", "integer", "最大评分条数，默认 50", default=50),
            Parameter("min_score", "float", "最低质量分门槛，默认 0.4", default=0.4),
        ],
        execute=tool_score_prompts,
        examples=["评分质量分0.5以上", "跑一遍评分过滤"],
    ))

    # 4. sync_images (NEW)
    registry.register(Skill(
        name="sync_images",
        description="将 GCS 中的封面图同步到本地 generated_images/ 目录",
        category="ai_generation",
        parameters=[],
        execute=tool_sync_images,
        examples=["同步所有封面图", "把 GCS 图片同步到本地"],
    ))

    # 5. build_html (NEW)
    registry.register(Skill(
        name="build_html",
        description="将 DB 中的 done prompts 生成为可浏览的 HTML 页面",
        category="web_maintenance",
        parameters=[
            Parameter("category", "string", "按分类筛选（可选）", default=None),
            Parameter("min_score", "float", "最低质量分门槛（可选）", default=None),
            Parameter("sync_images", "boolean", "是否同步图片到扁平目录，默认 True", default=True),
            Parameter("limit", "integer", "最大条数限制（可选）", default=None),
        ],
        execute=tool_build_html,
        examples=["生成 HTML 页面", "构建最新一批 prompt 的网页"],
    ))

    # 6. pool_status (EXISTING)
    registry.register(Skill(
        name="pool_status",
        description="查询 Prompt 池的当前状态——各状态的数量统计",
        category="system",
        parameters=[],
        execute=tool_pool_status,
        examples=["池子状态怎么样？", "还有多少图没生成？"],
    ))

    # 7. search_prompts (EXISTING — placeholder until Code-4)
    registry.register(Skill(
        name="search_prompts",
        description="通过语义 Embedding 搜索 Prompt 库，找到与关键词最相关的 Prompt",
        category="memory",
        parameters=[
            Parameter("query", "string", "语义搜索的关键词", required=True),
            Parameter("top_k", "integer", "返回数量，默认 5", default=5),
            Parameter("min_score", "float", "最低相关性分数筛选", default=None),
        ],
        execute=tool_search_prompts,
        examples=["找 Veo 3 相关的 prompt", "搜索动画风格高质量提示词"],
    ))

    # 8. generate_images (EXISTING — updated batch default)
    registry.register(Skill(
        name="generate_images",
        description="为池中 pending 的 Prompt 生成封面图（串行安全模式，15s 间隔）",
        category="ai_generation",
        parameters=[
            Parameter("batch", "integer", "生成数量，默认 8（0=全部）", default=8),
            Parameter("sort_by", "string", "排序方式：score（质量分）/ newest（最新）", default="score"),
            Parameter("filter", "object", "过滤条件，如 {\"min_score\": 0.6}", default=None),
        ],
        execute=tool_generate_images,
        examples=["生成 10 张图", "按分数生成前 5 张"],
    ))

    # 9. retry_failed (EXISTING)
    registry.register(Skill(
        name="retry_failed",
        description="重试之前图片生成失败的 Prompt",
        category="ai_generation",
        parameters=[
            Parameter("batch", "integer", "最大重试数量，默认 8", default=8),
        ],
        execute=tool_retry_failed,
        examples=["重试失败的图", "把失败的再跑一遍"],
    ))

    # 10. publish (EXISTING — updated parameters)
    registry.register(Skill(
        name="publish",
        description="将池中 done 状态的 Prompt 发布到 GitHub Pages 网站",
        category="web_maintenance",
        parameters=[
            Parameter("category", "string", "按分类筛选（可选）", default=None),
            Parameter("min_score", "float", "最低质量分门槛（可选）", default=None),
            Parameter("message", "string", "git 提交信息", default="Update prompt library"),
        ],
        execute=tool_publish,
        examples=["发布网页", "更新网站"],
    ))

    # 11. show_history (EXISTING)
    registry.register(Skill(
        name="show_history",
        description="查看最近的任务执行历史和对话记录",
        category="system",
        parameters=[
            Parameter("limit", "integer", "显示数量，默认 5", default=5),
            Parameter("include_conversation", "boolean", "是否包含对话历史", default=True),
        ],
        execute=tool_show_history,
        examples=["之前做了什么", "看看历史"],
    ))

    # 12. save_preference (EXISTING)
    registry.register(Skill(
        name="save_preference",
        description="保存用户偏好设置",
        category="memory",
        parameters=[
            Parameter("key", "string", "偏好键名", required=True),
            Parameter("value", "string", "偏好值", required=True),
        ],
        execute=tool_save_preference,
        examples=["记住我偏好 10 张一批", "设置默认模型为 gemini-2.5"],
    ))

    # 13. get_preference (EXISTING)
    registry.register(Skill(
        name="get_preference",
        description="读取用户偏好设置",
        category="memory",
        parameters=[
            Parameter("key", "string", "偏好键名", required=True),
        ],
        execute=tool_get_preference,
        examples=["我之前偏好是什么", "默认批次大小是多少"],
    ))