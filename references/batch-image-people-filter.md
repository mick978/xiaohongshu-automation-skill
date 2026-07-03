# Batch Image People-Filtering via vision_analyze (2026-07-02)

## When to use

When sourcing XHS cover images for douyin/short-video content (or any use case requiring people-free landscape images). XHS covers ~70% contain people (selfies, group hiking, portrait overlays). Manual inspection doesn't scale; `vision_analyze` does.

## Workflow

### 1. Download covers from search results

```python
import urllib.request

def download_xhs_image(url, fpath):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Referer": "https://www.xiaohongshu.com/"
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        Path(fpath).write_bytes(resp.read())
```

**Gotcha**: ~20% of `url_default` CDN links return 403 even with Referer. Skip and continue.

### 2. Batch vision_analyze — one image at a time

`vision_analyze` cannot be called from `execute_code`. Must be called as a tool from the agent.

**Efficient prompt** (minimizes token usage):
```
question: "是否包含人物？纯风景回答'无人物'，有人物回答人数。一句话即可。"
```

### 3. Classification result patterns

| vision_analyze response | Classification |
|---|---|
| "无人物" | ✅ Keep |
| "1人" / "2人" / "5人" / "包含人物" | ❌ Reject |
| "纯文字设计图" / "地图" / "表格截图" | ✅ Keep (no people, but may not be visually appealing) |

### 4. Typical yield

- 29 images downloaded → 8 no-people (28%)
- People categories found: solo selfies, group hiking, first-person cycling POV, portrait overlays, background tourists
- No-people categories found: canyon/forest landscapes, route maps, text cards, sunset/sky, architecture

### 5. Map to content

Not all no-people images are good slide backgrounds:
- **Best**: Wide landscape (canyon, forest, mountain, sky) — covers full 1080×1920 beautifully
- **OK**: Route maps / text cards — use as-is, they're already designed content
- **Avoid**: Screenshots of app UI, tables, low-res thumbnails

## Integration with douyin_content_gen.py

After filtering, pass image paths to `generate_slideshow(bg_images=[...])`:
- `None` entries = solid color background (for text-heavy slides)
- Image path entries = real photo background with 45% dark overlay
- Partial lists OK: fewer images than slides → remaining slides use solid color

See `short-video-content-automation/references/real-image-sourcing-workflow.md` for the full pipeline.
