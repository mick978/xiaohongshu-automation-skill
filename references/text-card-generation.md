# PIL 文字卡片生成（无图发帖方案）

小红书发帖 `--images` 是必填。没有照片时，用 PIL 生成文字卡片图。

## 中文字体路径

```python
# macOS 按优先级
font_paths = [
    '/System/Library/Fonts/STHeiti Medium.ttc',  # 最稳
    '/System/Library/Fonts/PingFang.ttc',
    '/System/Library/Fonts/STHeiti Light.ttc',
    '/System/Library/Fonts/Hiragino Sans GB.ttc',
]
```

## 模板函数

```python
from PIL import Image, ImageDraw, ImageFont
import os

def make_card(text_lines, filename, bg_color=(25, 25, 35), width=1080, padding=80):
    """
    text_lines: [(text, style), ...]  style: 'title'|'h2'|'accent'|'dim'|'body'
    """
    FONT_PATH = '/System/Library/Fonts/STHeiti Medium.ttc'
    font_title = ImageFont.truetype(FONT_PATH, 48)
    font_body = ImageFont.truetype(FONT_PATH, 34)
    font_small = ImageFont.truetype(FONT_PATH, 28)

    img = Image.new('RGB', (width, 2000), bg_color)
    draw = ImageDraw.Draw(img)

    y = padding
    for text, style in text_lines:
        font = {'title': font_title, 'h2': font_body, 'accent': font_body,
                'dim': font_small}.get(style, font_body)
        color = {'title': (255, 255, 255), 'h2': (124, 92, 255),
                 'accent': (255, 165, 2), 'dim': (160, 160, 180)
                }.get(style, (230, 230, 240))

        # 自动换行
        max_chars = (width - padding * 2) // (font.size // 2 + 2)
        while text:
            draw.text((padding, y), text[:max_chars], fill=color, font=font)
            y += font.size + 12
            text = text[max_chars:]

    y += padding
    img = img.crop((0, 0, width, y))
    path = os.path.join(OUT_DIR, filename)
    img.save(path, quality=95)
    return path
```

## 发帖调用

```bash
xhs post --images card1.png --images card2.png \
  --title "标题" --body "正文" --topic 话题名 --json
```

## 内容轮换（每日定时发文）

```python
from datetime import datetime, timezone, timedelta
CST = timezone(timedelta(hours=8))
day_of_year = datetime.now(CST).timetuple().tm_yday
post_index = day_of_year % len(POSTS)  # 8篇循环
```

## 话题标签

`--topic` 会自动搜索并关联话题，比在正文里手写 `#话题` 效果好（官方推荐格式）。
可多次使用：`--topic 成都徒步 --topic 户外运动`
