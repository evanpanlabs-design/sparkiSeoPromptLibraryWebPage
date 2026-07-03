"""Category-based style keyword system for image prompt enhancement."""

import random


def build_image_prompt(
    prompt_text: str,
    category: str,
    title: str = "",  # kept for signature compat, ignored
    style_keywords: dict[str, list[str]] | None = None,
) -> str:
    """Build a cover-image prompt with category style keywords.

    Randomly selects 3 style keywords from the category's list (or 'other')
    and injects them into the prompt to guide the visual style.

    The `title` parameter is accepted for signature compatibility but is no
    longer used — passing structured metadata to image models caused
    text/label artifacts to appear in the generated cover images.

    Args:
        prompt_text: The raw prompt text to generate an image for.
        category: The prompt category (e.g., "cinematic", "video-generation").
        title: Deprecated — ignored. Kept so callers don't break.
        style_keywords: Optional override dict; if None, falls back to hardcoded defaults.

    Returns:
        A styled prompt string ready to send to Gemini.
    """
    if style_keywords is None:
        style_keywords = _DEFAULT_STYLE_KEYWORDS

    style_kws = style_keywords.get(category, style_keywords.get("other", []))
    selected = random.sample(style_kws, min(3, len(style_kws)))
    style_str = ", ".join(selected)

    return (
        f"Generate a cover image for the following AI generation prompt. "
        f"The cover should visually represent this prompt in a compelling, marketable way.\n\n"
        f"IMPORTANT: Center the main subject/content in the middle of the image. "
        f"Do NOT place important elements near the top or bottom edges.\n"
        f"DO NOT include any text, words, numbers, labels, or watermarks in the image.\n"
        f"Style keywords: {style_str}\n\n"
        f"Prompt text: {prompt_text}"
    )


_DEFAULT_STYLE_KEYWORDS = {
    "cinematic-scene": [
        "cinematic lighting",
        "film grain",
        "anamorphic lens",
        "shallow depth of field",
        "35mm film stock",
        "f-stop",
        "lens flare",
        "aspect ratio 2.39:1",
        "kodak portra",
        "cinematic color grade",
    ],
    "sci-fi-fantasy": [
        "futuristic",
        "concept art",
        "CG environment",
        "Iridescent lighting",
        "digital matte painting",
        "8k resolution",
        "concept film style",
        "sci-fi atmosphere",
    ],
    "product-showcase": [
        "product shot",
        "studio lighting",
        "commercial photography",
        "high-key lighting",
        "white background",
        "advertising style",
        "reflective surface",
        "professional product photography",
    ],
    "character-portrait": [
        "character sheet",
        "consistent anatomy",
        "animation ready",
        "expressive portrait",
        "detailed face",
        "professional portrait lighting",
    ],
    "3d-render": [
        "3D render",
        "architectural visualization",
        "octane render",
        "CGI",
        "ray tracing",
        "detailed 3D",
        "cinematic render",
    ],
    "animation-clip": [
        "hand-drawn animation",
        "motion graphics",
        "stylized animation",
        "fluid motion",
        "frame-by-frame animation",
        "cartoon style",
        "vibrant colors",
    ],
    "nature-scene": [
        "nature photography",
        "golden hour lighting",
        "landscape photography",
        "outdoor cinematography",
        "natural lighting",
        "epic landscape",
        "environmental photography",
    ],
    "urban-scene": [
        "urban photography",
        "cityscape",
        "street photography",
        "architectural photography",
        "cinematic urban",
        "neon lighting",
        "street-level view",
    ],
    "food-beverage": [
        "food photography",
        "commercial food shot",
        "gourmet photography",
        "liquid cinematography",
        "food styling",
        "restaurant photography",
        "appetizing lighting",
    ],
    "fashion-apparel": [
        "fashion photography",
        "runway style",
        "editorial fashion",
        "clothing model",
        "fabric detail",
        "fashion editorial",
        "professional fashion shot",
    ],
    "sports-action": [
        "sports photography",
        "action shot",
        "dynamic pose",
        "motion blur",
        "athletic movement",
        "high speed capture",
        "cinematic action",
    ],
    "historical-period": [
        "period drama",
        "vintage aesthetics",
        "historical reenactment",
        "period cinematography",
        "vintage color grade",
        "retro film look",
        "historical setting",
    ],
    "abstract-motion": [
        "abstract art",
        "particle effects",
        "generative art",
        "audio-reactive visual",
        "shaders",
        "artistic motion",
        "abstract animation",
    ],
    "tutorial-demo": [
        "screen recording style",
        "product demo",
        "clean UI design",
        "professional presentation",
        "demo video style",
        "instructional visual",
        "clear demonstration",
    ],
    "social-media-content": [
        "vertical video",
        "reel-style",
        "phone-native framing",
        "engaging content",
        "social media aesthetic",
        "vertical format",
        "viral video style",
    ],
    "music-visualizer": [
        "music visualizer",
        "audio-reactive",
        "album art motion",
        "audio visual",
        "music video style",
        "rhythmic animation",
    ],
    "food": [
        "food photography",
        "gourmet styling",
        "appetizing lighting",
        "commercial food shot",
        "restaurant quality",
    ],
    "other": [
        "high quality",
        "detailed",
        "vibrant colors",
        "professional composition",
        "marketable",
        "compelling visual",
    ],
}