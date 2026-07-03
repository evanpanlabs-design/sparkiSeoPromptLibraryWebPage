"""Generate sitemap.xml for the Veo prompt library.

Strategy:
  1. Fetch live sitemap.xml from https://veo.sparki.io/sitemap.xml
  2. Merge with locally-known pages (from outputs/prompts/*.html and index)
  3. Write merged result to outputs/sitemap.xml
  4. Then the user can git push the merged file to deploy

This way we never lose online entries that aren't in the local output dir
(e.g. old prompts whose detail pages were deleted locally).
"""

import io
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://veo.sparki.io"
PROMPTS_DIR = Path("outputs/prompts")
OUTPUT_PATH = Path("outputs/sitemap.xml")
LIVE_SITEMAP_URL = f"{BASE_URL}/sitemap.xml"

NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"


def _local_page(slug: str, today: str) -> dict:
    """Build a page dict for a locally-known prompt page."""
    return {
        "loc": f"/prompts/{slug}.html",
        "lastmod": today,
        "changefreq": "weekly",
        "priority": "0.7",
    }


def scan_local_pages() -> list[dict]:
    """Scan outputs/prompts/ directory for locally-known pages."""
    if not PROMPTS_DIR.exists():
        raise FileNotFoundError(f"Prompts directory not found: {PROMPTS_DIR}")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pages = []
    for html_file in sorted(PROMPTS_DIR.glob("*.html")):
        slug = html_file.stem
        pages.append(_local_page(slug, today))
    return pages


def fetch_live_pages() -> list[dict]:
    """Fetch live sitemap.xml and return its pages (excluding index).

    Returns empty list on any error (offline, 404, parse error).
    """
    try:
        req = urllib.request.Request(
            LIVE_SITEMAP_URL,
            headers={"User-Agent": "Sparki-Sitemap-Merger/1.0 (+https://veo.sparki.io)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_bytes = resp.read()
    except Exception as e:
        print(f"  [warn] Could not fetch live sitemap: {e}")
        return []

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        print(f"  [warn] Live sitemap XML parse error: {e}")
        return []

    pages = []
    for url_el in root.findall(f"{{{NAMESPACE}}}url"):
        loc_el = url_el.find(f"{{{NAMESPACE}}}loc")
        if loc_el is None or not loc_el.text:
            continue
        # Extract path from URL
        loc = loc_el.text.strip()
        path = loc.replace(BASE_URL, "").rstrip("/")
        if not path or path == "/":
            # Skip the static index — we always rewrite it
            continue

        lastmod_el = url_el.find(f"{{{NAMESPACE}}}lastmod")
        lastmod = lastmod_el.text.strip() if lastmod_el is not None and lastmod_el.text else None

        changefreq_el = url_el.find(f"{{{NAMESPACE}}}changefreq")
        changefreq = changefreq_el.text.strip() if changefreq_el is not None and changefreq_el.text else "weekly"

        priority_el = url_el.find(f"{{{NAMESPACE}}}priority")
        priority = priority_el.text.strip() if priority_el is not None and priority_el.text else "0.7"

        pages.append({
            "loc": path,
            "lastmod": lastmod,
            "changefreq": changefreq,
            "priority": priority,
        })

    print(f"  [info] Fetched {len(pages)} entries from live sitemap")
    return pages


def merge_pages(local_pages: list[dict], live_pages: list[dict]) -> list[dict]:
    """Merge: local wins (with fresh lastmod) for matching paths, live-only pages are preserved.

    Normalizes paths so that /prompts/foo.html and /prompts/foo are treated as the same entry.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    by_path: dict[str, dict] = {}

    # Normalize a path: drop .html suffix for comparison
    def _normalize(path: str) -> str:
        if path.startswith("/prompts/") and path.endswith(".html"):
            return path[:-5]
        return path

    # Add live pages first (will be overridden by local if exists)
    for p in live_pages:
        key = _normalize(p["loc"])
        by_path[key] = p

    # Add local pages (override live, refresh lastmod). Local pages now always have .html suffix.
    for p in local_pages:
        key = _normalize(p["loc"])
        merged = dict(p)
        merged["lastmod"] = today
        merged["changefreq"] = "weekly"
        merged["priority"] = "0.7"
        by_path[key] = merged

    return sorted(by_path.values(), key=lambda x: x["loc"])


def build_sitemap_xml(pages: list[dict]) -> str:
    """Build sitemap XML string from page list."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    urlset = ET.Element("urlset")
    urlset.set("xmlns", NAMESPACE)

    # Always put the static index first
    idx = ET.SubElement(urlset, "url")
    loc = ET.SubElement(idx, "loc")
    loc.text = f"{BASE_URL}/"
    lastmod = ET.SubElement(idx, "lastmod")
    lastmod.text = today
    cfreq = ET.SubElement(idx, "changefreq")
    cfreq.text = "daily"
    pri = ET.SubElement(idx, "priority")
    pri.text = "1.0"

    for page in pages:
        url_el = ET.SubElement(urlset, "url")
        loc = ET.SubElement(url_el, "loc")
        loc.text = f"{BASE_URL}{page['loc']}"
        if page.get("lastmod"):
            lastmod_el = ET.SubElement(url_el, "lastmod")
            lastmod_el.text = page["lastmod"]
        changefreq_el = ET.SubElement(url_el, "changefreq")
        changefreq_el.text = page.get("changefreq", "weekly")
        priority_el = ET.SubElement(url_el, "priority")
        priority_el.text = page.get("priority", "0.7")

    ET.indent(urlset, space="  ")
    buf = io.StringIO()
    ET.ElementTree(urlset).write(buf, encoding="unicode", xml_declaration=True)
    return buf.getvalue()


def generate() -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1. Scan local
    local_pages = scan_local_pages()
    print(f"  Local pages: {len(local_pages)}")

    # 2. Fetch live
    live_pages = fetch_live_pages()

    # 3. Merge
    merged = merge_pages(local_pages, live_pages)
    print(f"  Merged total: {len(merged)}")

    # 4. Write
    xml = build_sitemap_xml(merged)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(xml, encoding="utf-8")

    print(f"\nSitemap written to {OUTPUT_PATH}")
    print(f"  Index: 1 (static)")
    print(f"  Local-only: {len(local_pages)}")
    print(f"  Live-only: {len(live_pages) - sum(1 for p in local_pages if any(l['loc']==p['loc'] for l in live_pages))}")
    print(f"  Total: {1 + len(merged)}")

    return {
        "local": len(local_pages),
        "live": len(live_pages),
        "merged": len(merged),
    }


if __name__ == "__main__":
    generate()
