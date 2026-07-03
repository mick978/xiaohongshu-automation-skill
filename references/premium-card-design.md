# PIL 文字卡片+封面大图生成 (2026-06-14)

## 核心规则：所有图片统一 1080×1440

小红书 feed 流最佳比例 3:4 (1080×1440)。封面+内容卡**全部**用固定 1080×1440，不要自动高度。统一尺寸在 feed 流里更整齐。

## 设计要素

1. **渐变背景** — 逐行像素绘制渐变（top_color → bottom_color）
2. **彩色侧边条** — `draw.rectangle([pad, y, pad+4, y+48], fill=accent)` 标记标题
3. **圆点标记** — `draw.ellipse([pad+2, y+12, pad+12, y+22], fill=accent)` 标记小标题
4. **呼吸留白** — 大量 spacer 和 divider，不要挤在一起
5. **角点装饰** — 四角画小圆点增加精致感
6. **底部收尾** — `draw.rectangle([pad, y, w-pad, y+2], fill=accent_dim)` 细线

## 封面大图 (3:4 竖版 1080×1440)

小红书 feed 流最佳展示比例是 **3:4**。封面图比纯文字内容卡更容易吸引点击。

**封面设计要素**：
- 暗色渐变天空背景（与内容主题色匹配）
- 山脉/城市/冰山剪影（`draw.polygon` + random seed）
- 星光点缀（`draw.ellipse` 小圆点，70个左右）
- 大字居中标题（72px 白色）
- accent 色装饰线（标题上下各一条短横线）
- 底部标签/emoji 摘要

```python
# 山脉剪影通用方法
import random
random.seed(100)  # 固定种子 = 每次生成相同形状
pts = [(0, h*65//100)]
x = 0
while x < w:
    ph = random.randint(60, 200)   # 峰高
    pw = random.randint(50, 130)   # 峰宽
    pts.append((x + pw//2, h*65//100 - ph))
    x += pw
    pts.append((x, h*65//100 - random.randint(10, 40)))
pts += [(w, h*65//100), (w, h), (0, h)]
draw.polygon(pts, fill=mountain_color)
```

**封面 + 内容卡组合**：封面作为第一张图，后面跟 3-5 张内容卡，总图数 4-6 张。

完整 `make_cover()` 函数见 `~/HermesAgentProject/apt-threat-intel/scripts/xhs_auto_post.py`。

## 4 种主题色

```python
THEMES = {
    'forest':   {'bg_top':(12,18,15),  'bg_bot':(18,28,22),  'accent':(72,199,142)},   # 森林绿
    'midnight': {'bg_top':(12,14,28),  'bg_bot':(20,24,42),  'accent':(100,140,255)},  # 午夜蓝
    'sunset':   {'bg_top':(28,15,12),  'bg_bot':(42,22,18),  'accent':(255,160,80)},   # 日落橙
    'arctic':   {'bg_top':(15,20,30),  'bg_bot':(22,30,45),  'accent':(120,210,235)},  # 极地蓝
}
```

## Section 类型

| 类型 | 用途 | 视觉效果 |
|------|------|----------|
| `title` | 大标题 | 左侧 accent 竖条 + 56px 白色字 |
| `subtitle` | 副标题 | 缩进 + 40px dim 色字 |
| `h2` | 小标题 | accent 圆点 + accent 色字 + 底部分割线 |
| `item` | 普通内容 | 32px body 色字 |
| `item_accent` | 强调内容 | 32px accent 色字 |
| `divider` | 分割线 | 水平细线 |
| `spacer` | 留白 | 20px 空白 |
| `footer` | 底部文字 | dim 色收尾 |

## 字体选择

macOS 优先级: `STHeiti Medium.ttc` > `PingFang.ttc`
尺寸: title=56, subtitle=40, h2=36, body/item=32, dim=26

## 注意事项

- **所有图片统一 1080×1440**（封面+内容卡全部相同尺寸，feed 流更整齐）
- 内容卡不足 1440 高度时，底部留渐变背景色空白（不裁剪）
- 中文字符宽度约 font_size/2，换行用 `max_ch = (w - pad*2) // (font_size // 2 + 1)`
- 保存 quality=95，单张 30-100KB
- 内容卡函数签名: `make_premium_card(sections, fname, theme, w=1080, h=1440, pad=65)`
