# HTML Template Structure

The `build-html` skill writes **two kinds** of HTML files. They use **two different
template strategies**.

## 1. Index page — `outputs/index.html`

### Source template

`outputs/templates/index.html` (1504 lines, single self-contained file)

### What's templated

A **single JavaScript array** is spliced into the template. Everything else —
CSS, navigation, modal markup, JS rendering logic, search box — is fixed.

```javascript
// outputs/templates/index.html line 1130
const prompts = [
    {
        "id": 1,
        "tweet_id": "2044440575009771536",
        "url": "https://x.com/Strength04_X/status/2044440575009771536",
        "category": "video-generation",
        "title": "Lipton Mountain Volcano",
        "prompt_text": "...",
        "notes": "...",
        "author": { "name": "𝐌", "screen_name": "Strength04_X", "followers": 14500 },
        "engagement": { "likes": 79, "retweets": 4, "replies": 42 }
    },
    // ... seed data lives here in the template, replaced at build time ...
] // PROMPTS_ARRAY_SENTINEL;  // line 1285
```

### Splice algorithm (`build_index()` at `scripts/build_html.py:139`)

1. Read template as UTF-8 string.
2. Find `si = tmpl.find("const prompts = [")` — start sentinel.
3. Find `ei = tmpl.find("] // PROMPTS_ARRAY_SENTINEL;")` — end sentinel.
4. If either is `-1`, raise `ValueError("Sentinel markers not found in index template")`.
5. `json.dumps(prompts, ensure_ascii=False, indent=4)` → strip outer `[...]` → get `inner`.
6. Write `tmpl[:si + len("const prompts = [")] + "\n" + inner + "\n" + tmpl[ei:]` to `outputs/index.html`.

**Critical**: both sentinel substrings must be **unique** in the template. Adding
`const prompts = [` anywhere else (a JS comment, a docstring) will break the splice.
Currently the only occurrence is at line 1130 / 1285.

### CSS / JS in the index template

- Embedded `<style>` block (no external CSS file).
- Inter + JetBrains Mono fonts from Google Fonts.
- Vanilla JS — no React, no Vue, no bundler.
- Renders prompt cards in a grid; opens a modal on click; client-side filter + sort.
- Bottom of file: modal HTML, search box, category chips, footer.

### Fields the index UI consumes from each prompt

| JS property | DB source | Used for |
|---|---|---|
| `id` | `prompts.id` | Cover image src (`generated_images/{id}.png`) |
| `tweet_id` | `prompts.tweet_id` | Picsum fallback seed, detail page link |
| `url` | `prompts.url` | "View on X" link |
| `category` | `prompts.category` | Category chip filter |
| `title` | `prompts.title` | Card heading |
| `prompt_text` | `prompts.prompt_text` | Modal body |
| `notes` | `prompts.notes` | Modal "Notes" section |
| `author.{name,screen_name,followers}` | `prompts.author_*` | Byline |
| `engagement.{likes,retweets,replies}` | `prompts.likes_count` etc. | Stats panel |

The mapper at `fetch_all_prompts()` line 73-93 builds the nested `author` /
`engagement` shape — the DB columns are flat.

## 2. Detail pages — `outputs/prompts/{slug}.html`

### Source template

**Inline string constant** at `scripts/build_html.py:163-421` — variable name
`_DETAIL_HTML`. There is **no separate file** in `outputs/templates/`. About
260 lines of HTML + embedded CSS + JS.

### Placeholders (Mustache-ish)

`_build_detail_static()` at line 441 does a plain `str.replace()` pass — not
a real Mustache engine. The placeholders are:

| Placeholder | Source |
|---|---|
| `{{db_id}}` | `prompt['id']` — image src |
| `{{tweet_id}}` | `prompt['tweet_id']` |
| `{{x_url}}` | `prompt['url']` |
| `{{title}}` | `prompt['title']` |
| `{{category}}` | `prompt['category']` (raw) |
| `{{category_display}}` | `prompt['category'].replace('-', ' ')` |
| `{{author_name}}` | `prompt['author']['name']` |
| `{{author_screen}}` | `prompt['author']['screen_name']` |
| `{{followers}}` | `_format_number(prompt['author']['followers'])` |
| `{{likes}}` | `_format_number(prompt['engagement']['likes'])` |
| `{{retweets}}` | `_format_number(prompt['engagement']['retweets'])` |
| `{{replies}}` | `_format_number(prompt['engagement']['replies'])` |
| `{{prompt_text}}` | `prompt['prompt_text']` (HTML body) |
| `{{prompt_text_json}}` | `json.dumps(prompt['prompt_text'])` (clipboard JS arg) |
| `{{published_at}}` | `_format_date(prompt.get('created_at'))` (YYYY-MM-DD or `""`) |

### Conditional block — Notes

```html
{{#notes}}
<div class="detail-section">
    <div class="section-label">Notes</div>
    ...{{notes}}...
</div>
{{/notes}}
```

Rendered via a regex `re.compile(r'\{\{#notes\}\}.*?\{\{/notes\}\}', re.DOTALL)`
substitution at `scripts/build_html.py:483`. If `prompt['notes']` is truthy,
the inner block is inserted; otherwise the whole block is stripped.

### Same-Category recommendation cards

Up to **3** sibling prompts from the same `category` (excluding self),
inserted at the `{{same_category_cards}}` marker (line 505 of build_html.py).
The card links use the **slug**: `<a href="{rp['slug']}.html">`.

### CSS / JS in the detail template

- Embedded `<style>` block — same color palette as the index page, separate copy.
- Vanilla JS for: copy-to-clipboard, share popover, toast notifications.
- "Try on Veo" button opens `https://aistudio.google.com/`.

## File-naming rules

### Detail page filename

```python
# scripts/build_html.py:38
def make_slug(prompt: dict) -> str:
    base = slugify(prompt.get('title') or '')   # lowercase, [\w\s-] only, hyphenated, max 80 chars
    tid = str(prompt.get('tweet_id') or '')
    return f"{base}-{tid}" if tid else base
```

Example: title `"Cyberpunk City"` + tweet_id `"2050000000000"` → slug
`"cyberpunk-city-2050000000000"` → file `outputs/prompts/cyberpunk-city-2050000000000.html`.

The wiki (`docs/11_ToolInterface.md` line 249) incorrectly says `prompts/{tweet_id}.html`.

### Image filename

```
outputs/generated_images/{prompts.id}.png
```

Keyed by the **DB primary key**, not `tweet_id`. The image filename **never**
contains the slug or title.

### Image fallback

If the file doesn't exist on disk at render time, the browser's `onerror`
handler swaps to `https://picsum.photos/seed/{tweet_id}/1100/618` (detail
page) or `.../550/307` (recommendation card / index card). The build does
not validate file presence — only the optional `sync_images=True` step
copies files into place.

## V3.3 template migration TODOs

1. **Externalize `_DETAIL_HTML`** into `outputs/templates/detail.html` so the
   template is editable without touching Python. Current `detail_page_demo.html`
   in the templates dir is a manual mockup, **not** wired into the build.
2. **Replace the string-replace logic with a real templating engine** (Jinja2)
   to avoid the regex-based `{{#notes}}` conditional and the manual JSON-escape
   for `{{prompt_text_json}}`.
3. **Add a per-prompt manifest** (`outputs/manifest.json`) listing slug →
   `prompts.id` → cover image path, so external sitemaps don't need to guess
   the slug format.
4. **Cleanup pass**: delete `outputs/prompts/*.html` that no longer correspond
   to a current `prompts.id`, otherwise renamed titles leave orphans.
