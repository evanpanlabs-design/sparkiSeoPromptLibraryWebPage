# Image Generation Prompt

**File:** `src/image_gen/style.py` (line ~33)  
**Used in:** `generate_images` skill + `RateLimitSafeGenerator`  
**Model:** `gemini-3.1-flash-image-preview` (image generation model)  
**Purpose:** Generate a cover image for an extracted Veo/Gemini prompt

## Prompt Builder

```python
def build_image_prompt(
    prompt_text: str,
    category: str,
    title: str,
    style_keywords: dict[str, list[str]] | None = None,
) -> str:
```

**Template:**
```
Generate a cover image for the following AI generation prompt.
The cover should visually represent this prompt in a compelling, marketable way.

IMPORTANT: Center the main subject/content in the middle of the image.
Do NOT place important elements near the top or bottom edges.
Style keywords: {style_str}

Prompt title: {title}
Prompt text: {prompt_text}
```

**Injected fields:**
- `style_str` — 3 randomly selected style keywords from the category's list
- `title` — the short title of the extracted prompt
- `prompt_text` — the raw Veo/Gemini prompt text

---

## Style Keywords by Category

**File:** `src/image_gen/style.py` (line ~44)

| Category | Keywords |
|---|---|
| `cinematic` | film grain, anamorphic, shallow depth of field, f-stop, lens flare, 35mm, kodak portra, cinematic lighting, aspect ratio 2.39:1, film stock |
| `character-design` | character sheet, turnaround, expression sheet, clean lineart, flat color, conceptual design |
| `product-photography` | product shot, white background, studio lighting, commercial photography, soft box, 85mm lens |
| `video-generation` | cinematic composition, dynamic camera movement, motion blur, wide shot, natural lighting, volumetric lighting |
| `other` | high detail, 4K, award-winning photography, professional composition, dramatic lighting |

---

## Example Output

For a prompt titled "Cinematic Mountain Product Shot" in category "product-photography":

```
Generate a cover image for the following AI generation prompt.
The cover should visually represent this prompt in a compelling, marketable way.

IMPORTANT: Center the main subject/content in the middle of the image.
Do NOT place important elements near the top or bottom edges.
Style keywords: product shot, studio lighting, 85mm lens

Prompt title: Cinematic Mountain Product Shot
Prompt text: A luxury watch on a granite stone surface, soft studio lighting from upper left, slight reflection, shallow depth of field, watch face clearly visible
```