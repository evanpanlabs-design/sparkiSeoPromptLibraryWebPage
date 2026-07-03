#!/usr/bin/env python3
"""Unified site build tool: sync images, build HTML, generate sitemap, optionally deploy.

Usage:
    python scripts/build_site.py                  # full build: sync + html + sitemap
    python scripts/build_site.py --no-sync        # skip image sync (use existing)
    python scripts/build_site.py --no-sitemap     # skip sitemap
    python scripts/build_site.py --no-deploy      # skip GitHub deploy
    python scripts/build_site.py --deploy-only     # only deploy (skip all builds)
    python scripts/build_site.py --sync-only       # only sync images
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ─── Paths ─────────────────────────────────────────────────────────────────

DB_PATH = PROJECT_ROOT / "data" / "veo_prompts.db"
GEN_IMAGES_DIR = PROJECT_ROOT / "outputs" / "generated_images"
PROMPTS_DIR = PROJECT_ROOT / "outputs" / "prompts"
OUTPUT_INDEX = PROJECT_ROOT / "outputs" / "index.html"
SITEMAP_PATH = PROJECT_ROOT / "outputs" / "sitemap.xml"
BASE_URL = "https://veo.sparki.io"


# ─── Database ────────────────────────────────────────────────────────────────

def db_connect():
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def fetch_all_prompts(category: str = None, min_score: float = None) -> list[dict]:
    conn = db_connect()
    sql = "SELECT * FROM prompts WHERE image_status = 'done' AND image_gcs_url IS NOT NULL"
    params = []
    if category:
        sql += " AND category = ?"
        params.append(category)
    if min_score is not None:
        sql += " AND CAST(quality_scores AS REAL) >= ?"
        params.append(min_score)
    sql += " ORDER BY CAST(quality_scores AS REAL) DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    results = []
    for r in rows:
        results.append({
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
        })
    return results


# ─── Image Sync ─────────────────────────────────────────────────────────────

def _safe_category(cat: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', cat or "other")


def sync_images_to_flat_dir(prompts: list[dict]) -> dict:
    """Copy images from outputs/images/{cat}/{yyyy-mm}/{tweet_id}.png
    to generated_images/{db_id}.png, clearing old content first.
    """
    GEN_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    # Clear old generated images to avoid stale data
    for f in GEN_IMAGES_DIR.iterdir():
        if f.suffix == ".png":
            f.unlink()

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


def sync_from_gcs(prompts: list[dict]) -> dict:
    """Download images from GCS to outputs/images/, then flatten to generated_images/."""
    try:
        from google.cloud import storage
    except ImportError:
        print("google-cloud-storage not installed, skipping GCS sync")
        return {"downloaded": 0, "skipped": 0, "errors": 0}

    client = storage.Client()
    bucket = client.bucket("sparki-op-test")
    blobs = list(bucket.list_blobs(prefix="prompts/"))

    db_info = {p["id"]: (p["tweet_id"], p["category"]) for p in prompts}
    downloaded, skipped, errors = 0, 0, 0

    for blob in blobs:
        name = blob.name
        if not name.endswith(".png") or len(name.split("/")) != 4:
            continue

        try:
            db_id = int(name.split("/")[-1][:-4])
        except ValueError:
            continue

        if db_id not in db_info:
            continue

        tweet_id, category = db_info[db_id]
        safe_cat = _safe_category(category)
        yyyy_mm = name.split("/")[2]
        local_dir = PROJECT_ROOT / "outputs" / "images" / safe_cat / yyyy_mm
        local_path = local_dir / f"{tweet_id}.png"

        local_dir.mkdir(parents=True, exist_ok=True)

        if local_path.exists() and local_path.stat().st_size == blob.size:
            skipped += 1
        else:
            try:
                with open(local_path, "wb") as f:
                    blob.download_to_file(f)
                downloaded += 1
            except Exception as e:
                print(f"  ERROR: {name}: {e}")
                errors += 1

    # After GCS sync, rebuild flat generated_images/
    flat_result = sync_images_to_flat_dir(prompts)
    return {"downloaded": downloaded, "skipped": skipped, "errors": errors, "flat": flat_result}


# ─── Index build ────────────────────────────────────────────────────────────

def build_index(prompts: list[dict]) -> None:
    INDEX_TEMPLATE = PROJECT_ROOT / "outputs" / "templates" / "index.html"
    tmpl = INDEX_TEMPLATE.read_text(encoding="utf-8")

    si = tmpl.find("const prompts = [")
    ei = tmpl.find("] // PROMPTS_ARRAY_SENTINEL;")
    if si == -1 or ei == -1:
        raise ValueError("Sentinel markers not found in index template")

    data_start = si + len("const prompts = [")
    prompts_json = json.dumps(prompts, ensure_ascii=False, indent=4)
    inner = prompts_json[1:-1].strip()

    new_html = tmpl[:data_start] + "\n" + inner + "\n" + tmpl[ei:]
    OUTPUT_INDEX.write_text(new_html, encoding="utf-8")
    print(f"  index.html written ({len(prompts)} prompts)")


# ─── Detail page template ──────────────────────────────────────────────────

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
        .detail-header { display: grid; grid-template-columns: 1fr 1fr; gap: 40px; margin-bottom: 40px; align-items: start; }
        .detail-image { width: 100%; aspect-ratio: 16/9; border-radius: 12px; overflow: hidden; border: 1px solid #808080; background: var(--bg-tertiary); }
        .detail-image img { width: 100%; height: 100%; object-fit: cover; display: block; }
        .image-x-link { position: absolute; bottom: 12px; right: 12px; width: 36px; height: 36px; background: rgba(255,255,255,0.92); border-radius: 50%; display: flex; align-items: center; justify-content: center; text-decoration: none; }
        .detail-image-wrap { position: relative; }
        .detail-info { display: flex; flex-direction: column; gap: 24px; }
        .detail-category { display: inline-block; align-self: flex-start; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; padding: 3px 10px; border-radius: 20px; color: white; background: var(--accent); }
        .detail-title { font-size: 26px; font-weight: 700; line-height: 1.3; letter-spacing: -0.5px; }
        .detail-author { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
        .author-col { padding: 14px 18px; display: flex; flex-direction: column; align-items: center; gap: 3px; }
        .author-col:not(:last-child) { border-right: 1px solid var(--border); }
        .author-col-name { font-size: 15px; font-weight: 600; }
        .author-col-handle { font-size: 12px; color: var(--accent); }
        .author-col-followers { font-size: 12px; color: var(--text-tertiary); }
        .detail-stats { display: flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
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
        .section-label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; color: var(--text-tertiary); margin-bottom: 12px; }
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
        .recs-header h3 { font-size: 14px; font-weight: 600; color: var(--text-secondary); }
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

            <div class="detail-author">
                <div class="author-col">
                    <span class="author-col-name">{{author_name}}</span>
                </div>
                <div class="author-col">
                    <span class="author-col-handle">@{{author_screen}}</span>
                </div>
                <div class="author-col">
                    <span class="author-col-followers">{{followers}}</span>
                </div>
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
                <a href="#" class="btn btn-primary" onclick="copyPromptText(event, {{prompt_text_json}})">
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
    }

    html = _DETAIL_HTML
    for placeholder, value in replacements.items():
        html = html.replace(placeholder, str(value))

    # Handle notes conditionally
    import re
    notes_block = '{{#notes}}\n    <div class="detail-section">\n        <div class="section-label">Notes</div>\n        <div class="prompt-text-block">\n            <div class="prompt-text-content">{{notes}}</div>\n        </div>\n    </div>\n    {{/notes}}'
    if prompt.get('notes'):
        notes_content = notes_block.replace('{{notes}}', prompt['notes'])
        html = html.replace(notes_block, notes_content)
    else:
        html = html.replace(notes_block, '')

    # Same Category — up to 3 related prompts
    same_cat_cards = ''
    if all_prompts:
        related = [p for p in all_prompts if p['category'] == prompt['category'] and p['tweet_id'] != prompt['tweet_id']][:3]
        for rp in related:
            cat_disp = rp['category'].replace('-', ' ')
            same_cat_cards += f'''<a href="/prompts/{rp['tweet_id']}.html" class="rec-card">
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
    """Write one static HTML per prompt in prompts/ directory keyed by tweet_id."""
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)

    for p in prompts:
        html = _build_detail_static(p, all_prompts=prompts)
        out_path = PROMPTS_DIR / f"{p['tweet_id']}.html"
        out_path.write_text(html, encoding="utf-8")

    print(f"  {len(prompts)} detail pages written to {PROMPTS_DIR}")
    return len(prompts)


# ─── Sitemap ───────────────────────────────────────────────────────────────

def generate_sitemap(prompts: list[dict]) -> None:
    static_pages = [{"loc": "/", "lastmod": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "changefreq": "daily", "priority": "1.0"}]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dynamic_pages = []
    for p in prompts:
        dynamic_pages.append({
            "loc": f"/prompts/{p['tweet_id']}",
            "lastmod": now,
            "changefreq": "monthly",
            "priority": "0.6",
        })

    all_pages = static_pages + dynamic_pages

    urlset = ET.Element("urlset")
    urlset.set("xmlns", "http://www.sitemaps.org/schemas/sitemap/0.9")

    for page in all_pages:
        url_el = ET.SubElement(urlset, "url")
        loc = ET.SubElement(url_el, "loc")
        loc.text = f"{BASE_URL}{page['loc']}"
        if page["lastmod"]:
            lastmod = ET.SubElement(url_el, "lastmod")
            lastmod.text = page["lastmod"]
        changefreq = ET.SubElement(url_el, "changefreq")
        changefreq.text = page["changefreq"]
        priority = ET.SubElement(url_el, "priority")
        priority.text = page["priority"]

    ET.indent(urlset, space="  ")
    import io
    buf = io.StringIO()
    ET.ElementTree(urlset).write(buf, encoding="unicode", xml_declaration=True)
    SITEMAP_PATH.write_text(buf.getvalue(), encoding="utf-8")

    print(f"  sitemap.xml written ({len(all_pages)} URLs)")


# ─── Deploy ────────────────────────────────────────────────────────────────

# Deploy targets
PERSONAL_REPO = "https://github.com/evanpanlabs-design/sparkiSeoPromptLibraryWebPage.git"
OFFICIAL_REPO = "https://github.com/sparki-ai/veo-prompt-station.git"
PERSONAL_BRANCH = "gh-pages"
OFFICIAL_BRANCH = "main"


def deploy_to_github(target: str = "official") -> None:
    """Deploy to GitHub.

    target: 'personal' → evanpanlabs-design/sparkiSeoPromptLibraryWebPage:gh-pages
            'official' → sparki-ai/veo-prompt-station:main
    """
    import subprocess
    import tempfile

    if target == "personal":
        repo_url = PERSONAL_REPO
        branch = PERSONAL_BRANCH
        label = "personal (evanpanlabs-design/sparkiSeoPromptLibraryWebPage)"
    else:
        repo_url = OFFICIAL_REPO
        branch = OFFICIAL_BRANCH
        label = "official (sparki-ai/veo-prompt-station)"

    print(f"  Deploying to {label}:{branch} ...")

    tmp = Path(tempfile.mkdtemp())
    repo_dir = tmp / "repo"
    repo_dir.mkdir()

    # Init temp repo
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", repo_url],
                    cwd=repo_dir, capture_output=True)
    subprocess.run(["git", "checkout", "--orphan", branch], cwd=repo_dir, capture_output=True)
    # Ensure git user identity is set (orphan branches start with no config)
    subprocess.run(["git", "config", "user.email", "deployer@sparki.local"], cwd=repo_dir, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Sparki Deployer"], cwd=repo_dir, capture_output=True)

    # Copy outputs
    for f in (PROJECT_ROOT / "outputs").iterdir():
        if f.is_dir():
            shutil.copytree(f, repo_dir / f.name)
        else:
            shutil.copy2(f, repo_dir / f.name)

    # Sanity check: sitemap.xml must exist before commit
    sitemap_local = PROJECT_ROOT / "outputs" / "sitemap.xml"
    if not sitemap_local.exists():
        print(f"  [ERROR] outputs/sitemap.xml missing — aborting deploy")
        print(f"           run: python scripts/generate_sitemap.py")
        return
    sitemap_size = sitemap_local.stat().st_size
    print(f"  [check] sitemap.xml present ({sitemap_size} bytes)")

    subprocess.run(["git", "add", "-A"], cwd=repo_dir, capture_output=True)
    commit_result = subprocess.run(
        ["git", "commit", "-m", f"Deploy {datetime.now().strftime('%Y-%m-%d')}"],
        cwd=repo_dir, capture_output=True, text=True
    )
    if commit_result.returncode != 0:
        print(f"  Commit failed: {commit_result.stderr}")
        # Clean up temp dir best-effort
        try:
            shutil.rmtree(tmp)
        except Exception:
            pass
        return
    result = subprocess.run(
        ["git", "push", "origin", branch, "--force"],
        cwd=repo_dir, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  Deploy failed: {result.stderr}")
    else:
        print(f"  Deploy complete: {repo_url.replace('.git', '')}  branch={branch}")

    # Best-effort cleanup (Windows file locks may prevent rmtree)
    try:
        shutil.rmtree(tmp)
    except Exception:
        pass


# ─── Main ───────────────────────────────────────────────────────────────────

def build(sync_images: bool = False, sync_gcs: bool = False,
          build_html: bool = True, generate_smap: bool = True,
          deploy: bool = False, category: str = None,
          min_score: float = None, limit: int = None) -> dict:

    prompts = fetch_all_prompts(category=category, min_score=min_score)
    if limit:
        prompts = prompts[:limit]

    if not prompts:
        return {"prompts": 0}

    stats = {"prompts": len(prompts)}

    # Image sync
    if sync_gcs:
        print("Syncing from GCS...")
        result = sync_from_gcs(prompts)
        print(f"  GCS: {result['downloaded']} downloaded, {result['skipped']} skipped, {result['errors']} errors")
        flat = result.get("flat", {})
        print(f"  Flat: {flat.get('copied', 0)} copied, {flat.get('skipped', 0)} skipped, {flat.get('errors', 0)} errors")
        stats["gcs"] = result
    elif sync_images:
        print("Syncing images to generated_images/...")
        result = sync_images_to_flat_dir(prompts)
        print(f"  {result['copied']} copied, {result['skipped']} skipped, {result['errors']} errors")
        stats["images"] = result

    # Build HTML
    if build_html:
        print("Building HTML...")
        build_index(prompts)
        detail_count = build_detail_pages(prompts)
        stats["index"] = 1
        stats["details"] = detail_count

    # Sitemap
    if generate_smap:
        print("Generating sitemap...")
        generate_sitemap(prompts)
        stats["sitemap"] = 1

    # Deploy
    if deploy:
        print("Deploying to GitHub...")
        deploy_to_github()
        stats["deployed"] = True

    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Unified site build tool")
    parser.add_argument("--sync-images", action="store_true", help="Sync images from local outputs/images/ to generated_images/")
    parser.add_argument("--sync-gcs", action="store_true", help="Download images from GCS first, then sync")
    parser.add_argument("--no-html", action="store_true", help="Skip HTML build")
    parser.add_argument("--no-sitemap", action="store_true", help="Skip sitemap generation")
    parser.add_argument("--no-deploy", action="store_true", help="Skip GitHub deploy")
    parser.add_argument("--deploy-only", action="store_true", help="Only deploy, skip all builds")
    parser.add_argument("--sync-only", action="store_true", help="Only sync images, skip HTML and sitemap")
    parser.add_argument("--target", choices=["personal", "official"], default="official",
                        help="Deploy target: 'personal' (gh-pages) or 'official' (main)")
    parser.add_argument("--category", default=None, help="Filter by category")
    parser.add_argument("--min-score", type=float, default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if args.deploy_only:
        deploy_to_github(target=args.target)
    elif args.sync_only:
        prompts = fetch_all_prompts()
        if args.sync_gcs:
            result = sync_from_gcs(prompts)
            print(f"GCS: {result}")
        else:
            result = sync_images_to_flat_dir(prompts)
            print(f"Images: {result}")
    else:
        stats = build(
            sync_images=args.sync_images or args.sync_gcs,
            sync_gcs=args.sync_gcs,
            build_html=not args.no_html,
            generate_smap=not args.no_sitemap,
            deploy=not args.no_deploy,
            category=args.category,
            min_score=args.min_score,
            limit=args.limit,
        )
        print(f"\nDone: {stats}")
