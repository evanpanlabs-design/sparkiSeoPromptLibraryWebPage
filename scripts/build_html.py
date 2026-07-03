#!/usr/bin/env python3
"""Build 1+N HTML pages: index.html + prompts/{tweet_id}.html for each prompt.

Minimal, correct, stable implementation.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

INDEX_TEMPLATE = PROJECT_ROOT / "outputs" / "templates" / "index.html"
OUTPUT_INDEX = PROJECT_ROOT / "outputs" / "index.html"
PROMPTS_DIR = PROJECT_ROOT / "outputs" / "prompts"
GEN_IMAGES_DIR = PROJECT_ROOT / "outputs" / "generated_images"
DB_PATH = PROJECT_ROOT / "data" / "veo_prompts.db"


# ─── Slug helpers ───────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    """Convert title to URL-safe slug."""
    s = (text or "").lower().strip()
    s = re.sub(r'[^\w\s-]', '', s, flags=re.UNICODE)
    s = re.sub(r'[\s_]+', '-', s)
    s = re.sub(r'-+', '-', s)
    s = s.strip('-')[:80]
    return s or "untitled"


def make_slug(prompt: dict) -> str:
    """Build a unique slug: <title-slug>-<tweet_id>."""
    base = slugify(prompt.get('title') or '')
    tid = str(prompt.get('tweet_id') or '')
    return f"{base}-{tid}" if tid else base


# ─── Database ───────────────────────────────────────────────────────────────

def db_connect():
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def fetch_all_prompts(category: str = None, min_score: float = None) -> list[dict]:
    conn = db_connect()
    sql = """SELECT p.*, t.created_at
             FROM prompts p
             LEFT JOIN tweets t ON p.tweet_id = t.tweet_id
             WHERE p.image_status = 'done' AND p.image_gcs_url IS NOT NULL"""
    params = []
    if category:
        sql += " AND p.category = ?"
        params.append(category)
    if min_score is not None:
        sql += " AND CAST(p.quality_scores AS REAL) >= ?"
        params.append(min_score)
    sql += " ORDER BY CAST(p.quality_scores AS REAL) DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    results = []
    for r in rows:
        item = {
            "id": r["id"],
            "tweet_id": str(r["tweet_id"]),
            "url": r["url"] or f"https://x.com/unknown/status/{r['tweet_id']}",
            "category": r["category"] or "other",
            "title": (r["title"] or "")[:120],
            "prompt_text": r["prompt_text"] or "",
            "notes": r["notes"] or None,
            "author": {
                "name": r["author_name"] or "Unknown",
                "screen_name": r["author_screen"] or "unknown",
                "followers": int(r["author_followers"] or 0),
            },
            "engagement": {
                "likes": int(r["likes_count"] or 0),
                "retweets": int(r["retweet_count"] or 0),
                "replies": int(r["reply_count"] or 0),
            },
            "created_at": r["created_at"] or None,
        }
        item["slug"] = make_slug(item)
        results.append(item)
    return results


# ─── Image sync ──────────────────────────────────────────────────────────────

def _safe_category(cat: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', cat or "other")


def sync_images_to_flat_dir() -> dict:
    """Copy GCS-synced images to generated_images/{db_id}.png keyed by db_id."""
    prompts = fetch_all_prompts()
    GEN_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    copied, skipped, errors = 0, 0, 0
    for p in prompts:
        tweet_id = p["tweet_id"]
        category = p["category"]
        safe_cat = _safe_category(category)
        dst = GEN_IMAGES_DIR / f"{p['id']}.png"

        if dst.exists():
            skipped += 1
            continue

        found = False
        img_dir = PROJECT_ROOT / "outputs" / "images" / safe_cat
        if img_dir.exists():
            for month_dir in img_dir.iterdir():
                if month_dir.is_dir():
                    src = month_dir / f"{tweet_id}.png"
                    if src.exists():
                        shutil.copy2(src, dst)
                        copied += 1
                        found = True
                        break
        if not found:
            errors += 1

    return {"copied": copied, "skipped": skipped, "errors": errors}


# ─── Build index.html ────────────────────────────────────────────────────────

def build_index(prompts: list[dict]) -> None:
    """Write index.html with embedded prompts array."""
    tmpl = INDEX_TEMPLATE.read_text(encoding="utf-8")

    si = tmpl.find("const prompts = [")
    ei = tmpl.find("] // PROMPTS_ARRAY_SENTINEL;")
    if si == -1 or ei == -1:
        raise ValueError("Sentinel markers not found in index template")

    data_start = si + len("const prompts = [")
    # Build JSON with outer brackets, then extract inner
    prompts_json = json.dumps(prompts, ensure_ascii=False, indent=4)
    # Remove first [ and last ] + trailing whitespace
    inner = prompts_json[1:-1].strip()

    new_html = tmpl[:data_start] + "\n" + inner + "\n" + tmpl[ei:]

    OUTPUT_INDEX.write_text(new_html, encoding="utf-8")
    print(f"  index.html written ({len(prompts)} prompts)")


# ─── Build detail pages ─────────────────────────────────────────────────────

# Fully static detail HTML template — all data hardcoded, no JS routing
_DETAIL_HTML = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{title}} — Veo Prompt Library</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-primary: #ffffff;
            --bg-secondary: #f0fdff;
            --bg-tertiary: #e6f7ff;
            --text-primary: #0a0a0a;
            --text-secondary: #404040;
            --text-tertiary: #737373;
            --border: #d0e8ff;
            --border-strong: #a5d4ff;
            --accent: #3B82F6;
            --accent-glow: rgba(59, 130, 246, 0.15);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
            -webkit-font-smoothing: antialiased;
            min-height: 100vh;
        }
        nav {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 48px;
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            background: rgba(255,255,255,0.95);
            backdrop-filter: blur(8px);
            z-index: 100;
        }
        .nav-logo { font-size: 18px; font-weight: 700; color: var(--text-primary); text-decoration: none; display: flex; align-items: center; gap: 8px; }
        .nav-center { display: flex; gap: 32px; }
        .nav-center a { text-decoration: none; color: var(--text-secondary); font-size: 14px; font-weight: 500; }
        .nav-center a:hover, .nav-center a.active { color: var(--text-primary); }
        .detail-page { max-width: 1100px; margin: 0 auto; padding: 48px 24px 80px; }
        .back-nav { display: flex; align-items: center; gap: 8px; margin-bottom: 32px; }
        .back-nav a { display: flex; align-items: center; gap: 8px; text-decoration: none; color: var(--text-secondary); font-size: 14px; font-weight: 500; }
        .back-nav a:hover { color: var(--text-primary); }
        .detail-header { display: grid; grid-template-columns: 1fr 1fr; gap: 40px; margin-bottom: 40px; align-items: stretch; }
        .detail-image { width: 100%; aspect-ratio: 16/9; border-radius: 12px; overflow: hidden; border: 1px solid #808080; background: var(--bg-tertiary); }
        .detail-image img { width: 100%; height: 100%; object-fit: cover; display: block; }
        .image-x-link { position: absolute; bottom: 12px; right: 12px; width: 36px; height: 36px; background: rgba(255,255,255,0.92); border-radius: 50%; display: flex; align-items: center; justify-content: center; text-decoration: none; }
        .detail-image-wrap { position: relative; }
        .detail-info { display: flex; flex-direction: column; justify-content: space-between; gap: 12px; }
        .detail-category { display: inline-block; align-self: flex-start; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; padding: 3px 10px; border-radius: 20px; color: white; background: var(--accent); }
        .detail-title { font-size: 26px; font-weight: 700; line-height: 1.3; letter-spacing: -0.5px; margin: 0; }
        .author-info { display: flex; align-items: center; gap: 6px; font-size: 12px; font-family: 'Inter', sans-serif; }
        .author-name { color: var(--text-primary); }
        .author-sep { color: var(--text-tertiary); }
        .author-handle { color: var(--accent); text-decoration: none; }
        .author-handle:hover { text-decoration: underline; }
        .author-followers { color: var(--text-tertiary); }
        .author-date { color: var(--text-tertiary); }
        .detail-stats { display: flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; flex-shrink: 0; }
        .detail-stat { flex: 1; padding: 12px 16px; display: flex; flex-direction: column; align-items: center; gap: 2px; }
        .detail-stat:not(:last-child) { border-right: 1px solid var(--border); }
        .detail-stat-value { font-size: 18px; font-weight: 700; }
        .detail-stat-label { font-size: 11px; color: var(--text-tertiary); text-transform: uppercase; letter-spacing: 0.5px; }
        .detail-actions { display: flex; gap: 10px; }
        .btn { flex: 1; padding: 11px 18px; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.15s; text-align: center; text-decoration: none; display: flex; align-items: center; justify-content: center; gap: 7px; border: 2px solid transparent; }
        .btn-primary { background: var(--accent); border-color: var(--accent); color: white; }
        .btn-primary:hover { background: #2563eb; border-color: #2563eb; }
        .btn-outline { background: white; border-color: var(--border-strong); color: var(--text-primary); }
        .btn-outline:hover { background: var(--bg-secondary); border-color: var(--accent); color: var(--accent); }
        .detail-section { border-top: 1px solid var(--border); padding-top: 32px; margin-bottom: 40px; }
        .section-label { font-size: 15px; font-weight: 700; color: var(--text-primary); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; }
        .prompt-text-block { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 10px; padding: 20px 24px; }
        .prompt-text-content { font-family: 'JetBrains Mono', monospace; font-size: 13px; line-height: 1.8; color: var(--text-primary); white-space: pre-wrap; word-break: break-word; }
        .toast { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%) translateY(80px); background: var(--text-primary); color: white; padding: 10px 20px; border-radius: 8px; font-size: 14px; font-weight: 500; z-index: 9999; transition: transform 0.3s ease; pointer-events: none; }
        .toast.show { transform: translateX(-50%) translateY(0); }
        .share-popover { position: absolute; top: 56px; right: 0; background: white; border: 1px solid var(--border); border-radius: 10px; padding: 8px; box-shadow: 0 8px 24px rgba(0,0,0,0.12); min-width: 180px; z-index: 200; display: none; }
        .share-popover.open { display: block; }
        .share-popover button { width: 100%; text-align: left; padding: 9px 12px; border: none; background: transparent; font-size: 13px; color: var(--text-primary); border-radius: 6px; cursor: pointer; display: flex; align-items: center; gap: 8px; }
        .share-popover button:hover { background: var(--bg-secondary); }
        .share-popover .divider { height: 1px; background: var(--border); margin: 4px 0; }
        .recs-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
        .recs-header h3 { font-size: 15px; font-weight: 700; color: var(--text-primary); }
        .recs-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
        .rec-card { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; cursor: pointer; text-decoration: none; color: inherit; transition: all 0.15s; }
        .rec-card:hover { border-color: var(--accent); box-shadow: 0 4px 12px var(--accent-glow); }
        .rec-card-image { aspect-ratio: 16/9; overflow: hidden; background: var(--bg-tertiary); }
        .rec-card-image img { width: 100%; height: 100%; object-fit: cover; display: block; }
        .rec-card-body { padding: 10px 12px; display: flex; flex-direction: column; gap: 4px; }
        .rec-card-category { display: inline-block; font-size: 9px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; padding: 2px 8px; border-radius: 20px; color: white; background: var(--accent); align-self: flex-start; }
        .rec-card-title { font-size: 12px; font-weight: 500; color: var(--text-primary); line-height: 1.4; }
        @media (max-width: 768px) { nav { padding: 14px 20px; } .nav-center { display: none; } .detail-header { grid-template-columns: 1fr; } .detail-title { font-size: 22px; } .detail-page { padding: 24px 16px 60px; } .recs-grid { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
<nav>
    <a href="/" class="nav-logo">
        <img src="https://sparki.io/_next/image?url=%2Flogo-text.svg&w=256&q=75" alt="Sparki" style="height:28px;">
    </a>
    <div class="nav-center">
        <a href="/">Prompts</a>
        <a href="#" class="active">Prompt Detail</a>
    </div>
</nav>

<div class="detail-page">
    <div class="back-nav">
        <a href="/">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 12H5M12 5l-7 7 7 7"/></svg>
            Back to Prompts
        </a>
    </div>

    <div class="detail-header">
        <div class="detail-image-wrap">
            <div class="detail-image">
                <img src="/generated_images/{{db_id}}.png" alt="{{title}}" onerror="this.src='https://picsum.photos/seed/{{tweet_id}}/1100/618'">
            </div>
            <a href="{{x_url}}" target="_blank" class="image-x-link">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
            </a>
        </div>

        <div class="detail-info">
            <span class="detail-category">{{category_display}}</span>
            <h1 class="detail-title">{{title}}</h1>
            <div class="author-info">
                <span class="author-name">{{author_name}}</span>
                <span class="author-sep">&nbsp;|&nbsp;</span>
                <a href="https://x.com/{{author_screen}}" target="_blank" class="author-handle">@{{author_screen}}</a>
                <span class="author-sep">&nbsp;|&nbsp;</span>
                <span class="author-followers">{{followers}}</span>
                <span class="author-sep">&nbsp;|&nbsp;</span>
                <span class="author-date">{{published_at}}</span>
            </div>

            <div class="detail-stats">
                <div class="detail-stat">
                    <div class="detail-stat-value">{{likes}}</div>
                    <div class="detail-stat-label">Likes</div>
                </div>
                <div class="detail-stat">
                    <div class="detail-stat-value">{{retweets}}</div>
                    <div class="detail-stat-label">Retweets</div>
                </div>
                <div class="detail-stat">
                    <div class="detail-stat-value">{{replies}}</div>
                    <div class="detail-stat-label">Replies</div>
                </div>
                <div class="detail-stat">
                    <div class="detail-stat-value">{{followers}}</div>
                    <div class="detail-stat-label">Followers</div>
                </div>
            </div>

            <div class="detail-actions">
                <a href="#" class="btn btn-primary" onclick='copyPromptText(event, {{prompt_text_json}})'>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                    Copy Prompt
                </a>
                <div style="position:relative; flex: 1;">
                    <a href="#" class="btn btn-outline" onclick="toggleSharePopover(event)" style="width:100%;">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
                        Share
                    </a>
                    <div class="share-popover" id="share-popover">
                        <button onclick="shareTwitter()">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
                            Share on X
                        </button>
                        <button onclick="copyLink()">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71"/></svg>
                            Copy Link
                        </button>
                        <div class="divider"></div>
                        <button onclick="tryPrompt()">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                            Try on Veo
                        </button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div class="detail-section">
        <div class="section-label">Prompt</div>
        <div class="prompt-text-block">
            <div class="prompt-text-content">{{prompt_text}}</div>
        </div>
    </div>

    {{#notes}}
    <div class="detail-section">
        <div class="section-label">Notes</div>
        <div class="prompt-text-block">
            <div class="prompt-text-content">{{notes}}</div>
        </div>
    </div>
    {{/notes}}

    <div class="recommendations-section">
        <div class="recs-header">
            <h3>Same Category</h3>
        </div>
        <div class="recs-grid">
{{same_category_cards}}
        </div>
    </div>
</div>

<div class="toast" id="toast"></div>

<script>
function showToast(msg) {
    var t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(function() { t.classList.remove('show'); }, 2000);
}

function copyPromptText(e, text) {
    e.preventDefault();
    navigator.clipboard.writeText(text).then(function() { showToast('Prompt copied!'); });
}

function toggleSharePopover(e) {
    e.preventDefault();
    document.getElementById('share-popover').classList.toggle('open');
}

document.addEventListener('click', function(e) {
    if (!e.target.closest('.detail-actions')) {
        document.getElementById('share-popover').classList.remove('open');
    }
});

function shareTwitter() {
    var text = encodeURIComponent('Check out this Veo prompt: {{title}}');
    window.open('https://x.com/intent/tweet?text=' + text + '&url=' + encodeURIComponent(location.href), '_blank');
}

function copyLink() {
    navigator.clipboard.writeText(location.href).then(function() { showToast('Link copied!'); });
}

function tryPrompt() {
    window.open('https://aistudio.google.com/', '_blank');
}
</script>
</body>
</html>
'''


def _format_number(num):
    num = int(num or 0)
    return str(num) if num < 1000 else f"{num/1000:.1f}k"


def _format_date(ts: str) -> str:
    """Format ISO timestamp to 'YYYY-MM-DD'."""
    if not ts:
        return ''
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d')
    except Exception:
        return ts[:10] if ts else ''


def _build_detail_static(prompt: dict, all_prompts: list[dict] = None) -> str:
    """Render static detail page with all data hardcoded."""
    category_display = prompt['category'].replace('-', ' ')
    prompt_text_json = json.dumps(prompt['prompt_text'])

    replacements = {
        '{{db_id}}': str(prompt['id']),
        '{{tweet_id}}': str(prompt['tweet_id']),
        '{{x_url}}': prompt['url'],
        '{{title}}': prompt['title'],
        '{{category}}': prompt['category'],
        '{{category_display}}': category_display,
        '{{author_name}}': prompt['author']['name'],
        '{{author_screen}}': prompt['author']['screen_name'],
        '{{followers}}': _format_number(prompt['author']['followers']),
        '{{likes}}': _format_number(prompt['engagement']['likes']),
        '{{retweets}}': _format_number(prompt['engagement']['retweets']),
        '{{replies}}': _format_number(prompt['engagement']['replies']),
        '{{prompt_text}}': prompt['prompt_text'],
        '{{prompt_text_json}}': prompt_text_json,
        '{{published_at}}': _format_date(prompt.get('created_at') or ''),
    }

    html = _DETAIL_HTML
    for placeholder, value in replacements.items():
        html = html.replace(placeholder, str(value))

    # If no published date, remove the date separator too
    if not _format_date(prompt.get('created_at') or ''):
        html = html.replace('<span class="author-sep">&nbsp;|&nbsp;</span>\n                <span class="author-date"></span>', '')

    # Handle notes conditionally — use regex to match the block regardless of indentation
    import re
    if prompt.get('notes'):
        notes_html = f'''
    <div class="detail-section">
        <div class="section-label">Notes</div>
        <div class="prompt-text-block">
            <div class="prompt-text-content">{prompt['notes']}</div>
        </div>
    </div>
'''
        notes_block_pattern = re.compile(r'\{\{#notes\}\}.*?\{\{/notes\}\}', re.DOTALL)
        html = notes_block_pattern.sub(notes_html, html)
    else:
        notes_block_pattern = re.compile(r'\{\{#notes\}\}.*?\{\{/notes\}\}', re.DOTALL)
        html = notes_block_pattern.sub('', html)

    # Same Category — up to 3 related prompts
    same_cat_cards = ''
    if all_prompts:
        related = [p for p in all_prompts if p['category'] == prompt['category'] and p['tweet_id'] != prompt['tweet_id']][:3]
        for rp in related:
            cat_disp = rp['category'].replace('-', ' ')
            same_cat_cards += f'''<a href="/prompts/{rp['slug']}.html" class="rec-card">
                <div class="rec-card-image">
                    <img src="/generated_images/{rp['id']}.png" alt="{rp['title']}" onerror="this.src='https://picsum.photos/seed/{rp['tweet_id']}/550/307'">
                </div>
                <div class="rec-card-body">
                    <span class="rec-card-category">{cat_disp}</span>
                    <div class="rec-card-title">{rp['title']}</div>
                </div>
            </a>
'''
    html = html.replace('{{same_category_cards}}', same_cat_cards)

    return html


def build_detail_pages(prompts: list[dict]) -> int:
    """Write one static HTML per prompt in prompts/ directory keyed by slug.

    Slug format: <title-slug>-<tweet_id>, e.g. "cyberpunk-city-1919xxxxx".
    Each detail page has all data hardcoded — no JS routing, no embedded prompts array.
    """
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)

    for p in prompts:
        html = _build_detail_static(p, all_prompts=prompts)
        out_path = PROMPTS_DIR / f"{p['slug']}.html"
        out_path.write_text(html, encoding="utf-8")

    print(f"  {len(prompts)} detail pages written to {PROMPTS_DIR}")
    return len(prompts)


# ─── Main ────────────────────────────────────────────────────────────────────

def build(sync_images: bool = False, category: str = None,
          min_score: float = None, limit: int = None) -> dict:
    if sync_images:
        print("Syncing images...")
        stats = sync_images_to_flat_dir()
        print(f"  {stats['copied']} copied, {stats['skipped']} skipped, {stats['errors']} errors")

    prompts = fetch_all_prompts(category=category, min_score=min_score)
    if limit:
        prompts = prompts[:limit]

    if not prompts:
        return {"index": 0, "details": 0}

    build_index(prompts)
    detail_count = build_detail_pages(prompts)

    return {"index": 1, "details": detail_count, "total_prompts": len(prompts)}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build index + detail pages")
    parser.add_argument("--sync-images", action="store_true")
    parser.add_argument("--category", default=None)
    parser.add_argument("--min-score", type=float, default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    stats = build(
        sync_images=args.sync_images,
        category=args.category,
        min_score=args.min_score,
        limit=args.limit,
    )
    print(f"\nDone: index={stats['index']}, details={stats['details']}")