---
name: xiaohongshu-cli
description: "Operate Xiaohongshu (小红书, RedNote) via the `xhs` CLI — search notes/users/topics, read content + comments, follow, like, favorite, comment, post, and check notifications. Triggers: '小红书', 'xhs', 'redbook', 'rednote', 'xiaohongshu', '搜小红书', '看小红书', '发小红书', '点赞小红书', '评论小红书', '收藏小红书', '关注小红书'. Use `scripts/xhs.sh` (auto-installs on first use) and the `xhs` binary. Always check auth first via `xhs status --yaml`."
author: jackwener (upstream) + community packaging
version: "1.0.0"
tags: [xiaohongshu, xhs, redbook, rednote, 小红书, social-media, cli, browser-cookies, anti-detection]
metadata:
  hermes:
    tags: [xiaohongshu, xhs, 小红书, social-media, cli, browser-cookies]
    upstream: https://github.com/jackwener/xiaohongshu-cli
    license: Apache-2.0
    related_skills: [web-scraping-compliance, research, browser-automation]
---

# Xiaohongshu (小红书) CLI — Automation Skill

> **Upstream:** https://github.com/jackwener/xiaohongshu-cli (Apache-2.0, 2.1k+ stars)
> **License:** Apache-2.0 (commercial use allowed, copyright notice required)

## 概述

通过 `xhs` 命令行工具操控小红书。底层用 httpx + 反向工程的 XHS API，带 anti-detection（macOS Chrome 指纹、Gaussian jitter、captcha 冷却、指数退避）。

**核心功能**:
- 🔐 **认证** — 浏览器 cookie 自动提取，或 DevTools 导出注入，或 QR 码登录
- 🔍 **搜索** — 笔记/用户/话题
- 📖 **阅读** — 笔记详情、评论、子评论、用户主页
- 👍 **互动** — 点赞 / 收藏 / 评论 / 关注 / 取关（含自动批量+去重）
- ✍️ **发布** — 发图文笔记
- 🔔 **通知** — 未读 / @ / 点赞 / 新粉
- 📊 **结构化输出** — `--yaml` / `--json`（envelope: `{ok, schema_version, data, error}`）

## When to use

- 用户说"搜小红书 X"、"找小红书关于 X 的笔记"
- 用户说"看这条小红书"（给 note URL 或 ID）
- 用户说"发小红书"、"评论小红书"、"点赞小红书"、"收藏小红书"
- 用户说"我的小红书新消息"、"@ 谁了"、"谁赞了我"
- 任何涉及**小红书 / xhs / redbook / rednote** 的查询/操作

## When NOT to use

- **Twitter/X / Instagram / 微博 / 知乎 / B 站** — 各自有别的 CLI
- **微信公众号文章** — 用 article-to-markdown skill
- **大规模爬数据**（> 100 条/小时）— 风险高，需先看 rate-limit 文档

## 前置：认证检查（必走）

任何 xhs 命令执行前，先看认证：

```bash
# 自动安装 + 认证检查
scripts/xhs.sh status --yaml >/dev/null 2>&1 && echo "AUTH_OK" || echo "AUTH_NEEDED"
```

**AUTH_OK** → 直接做事
**AUTH_NEEDED** → 走登录流程

### 登录方式

```bash
# 选项 A: 自动从浏览器提 cookie（推荐）
scripts/xhs.sh login

# 选项 B: 浏览器辅助 QR 登录
scripts/xhs.sh login --qrcode

# 选项 C: DevTools cookie 注入（Chrome v20 AES-GCM 加密失败时用）
# Chrome DevTools → Application → Cookies → Copy as JSON
python3 scripts/xhs_inject_cookies.py --stdin < devtools-cookies.json

# 验证
scripts/xhs.sh status
scripts/xhs.sh whoami
```

### 登录失败处理

| 报错 | 解决 |
|------|------|
| `NoCookieError: No 'a1' cookie found` | 浏览器登录 xiaohongshu.com |
| `NeedVerifyError: Captcha required` | 浏览器完成验证码再试 |
| `IpBlockedError: IP blocked` | 换网络（切热点/VPN） |
| `SessionExpiredError` | 重跑 `xhs login` 刷新 cookie |
| Chrome AES-GCM 解密失败 | 用 `xhs_inject_cookies.py` 手动注入 |

## 搜索 + 读笔记 标准工作流

```bash
SCR="scripts/xhs.sh"

# 1. 搜（用 --json）
"$SCR" search "关键词" --sort popular --page 1 --json

# 2. 解析 → 列表（每条含 id, xsec_token, note_card）
#    过滤 model_type == "hot_query" 的广告位条目

# 3. 读详情（串行，sleep 2-3s）
"$SCR" read <id> --xsec-token <token> --json

# 4. 检查 stderr 有没有 "Captcha" — 有就停手 5min
# 5. 拿正文 desc + image_list
```

### Pitfall: 搜索结果顺序不稳

`xhs search` 的 sort 顺序不稳定，即使 `popular` 模式也会插广告/明星内容。**不要缓存位置编号，缓存 ID**。如果按位置挑，先 print 标题让用户确认。

### Pitfall: hot_query 广告位

`xhs search` 返回里有 1-2 条 `model_type: "hot_query"` 广告位（id 是 36 字符 UUID，note_card 为空 dict）。过滤：
```python
real = [it for it in items if (it.get("model_type") or "note") != "hot_query"]
```

## 自动互动工作流（LLM 驱动）

### 架构

```
Agent (LLM)                     Helper Script (机械逻辑)
    │                                    │
    ├─ xhs_llm_helper.py --search ──→ 搜索+去重+计数 → JSON candidates
    │                                    │
    ├─ 逐条 xhs read (全文) ──────────→ 拿 desc
    │                                    │
    ├─ vision_analyze (封面图) ────────→ 拿图片描述
    │                                    │
    ├─ 精写评论 (LLM) ─────────────────→ 引用笔记具体细节
    │                                    │
    └─ xhs_llm_helper.py --post ──────→ like + comment + dedup + count
```

### Helper 脚本

```bash
# 搜索候选（含去重+日限检查）
python3 scripts/xhs_llm_helper.py --search

# 查询是否已互动
python3 scripts/xhs_llm_helper.py --check <note_id> [user_id]

# 执行互动（like + comment + 自动清理下载的图片）
python3 scripts/xhs_llm_helper.py --post <url> <note_id> <user_id> "评论内容"

# 查看状态
python3 scripts/xhs_llm_helper.py --status

# 下载封面图（给 vision_analyze 用，自动注册清理）
python3 scripts/xhs_llm_helper.py --image <url>

# 手动清理所有已下载的图片
python3 scripts/xhs_llm_helper.py --cleanup

# 发帖（成功后自动删除本地图片）
python3 scripts/xhs_llm_helper.py --publish --images <dir> --title "标题" --body "正文"
```

### 自动清理机制

- **评论流程**：`--image` 下载的封面图注册到 cleanup 追踪文件，`--post` 完成互动后自动删除
- **发布流程**：`--publish` 发帖成功后自动删除 `--images` 目录下的图片文件，空目录也会删除
- **手动清理**：`--cleanup` 随时清理所有追踪中的下载图片
- **失败不删**：发帖失败时保留图片，方便重试

### 评论生成铁律

1. **必须 read 全文** — 禁止只用标题关键词生成评论
2. **必须看封面图** — `vision_analyze` 分析图片内容
3. **引用具体细节** — 从 desc+图片提取地点/活动/特征
4. **每条唯一** — 禁止跨笔记复用同一评论
5. **中性风格** — 像真人随口一句，不是 AI 空泛赞美
6. **禁止句式** — "太绝了！"/"收藏了！"/"学到了！"/"绝绝子"/"谁懂啊"

## 命令速查

| 任务 | 命令 |
|------|------|
| 看登录状态 | `scripts/xhs.sh status` |
| 看账号详情 | `scripts/xhs.sh whoami` |
| 登录 | `scripts/xhs.sh login` |
| 搜笔记 | `scripts/xhs.sh search "关键词" --sort popular --json` |
| 搜用户 | `scripts/xhs.sh search-user "用户名" --json` |
| 搜话题 | `scripts/xhs.sh topics "关键词" --json` |
| 读笔记 | `scripts/xhs.sh read <url_or_id> --xsec-token <token> --json` |
| 看评论 | `scripts/xhs.sh comments <id> --xsec-token <token> --json` |
| 点赞 | `scripts/xhs.sh like <url_or_id> --json` |
| 收藏 | `scripts/xhs.sh favorite <id> --json` |
| 评论 | `scripts/xhs.sh comment <id> --content "评论" --json` |
| 关注 | `scripts/xhs.sh follow <user_id> --json` |
| 发图文 | `scripts/xhs.sh post --images img1.png --images img2.png --title "标题" --body "正文" --json` |
| 我的笔记 | `scripts/xhs.sh my-notes --json` |
| 通知 | `scripts/xhs.sh notifications --json` |

## 数据结构

所有笔记数据在 `data.items[0].note_card.*`：

```json
{
  "ok": true,
  "data": {
    "items": [{
      "id": "<note_id>",
      "model_type": "note",
      "xsec_token": "...",
      "note_card": {
        "title": "...",
        "desc": "正文全文",
        "image_list": [...],
        "user": {"user_id", "nickname", "avatar"},
        "interact_info": {"liked_count", "collected_count", "comment_count", "liked", "collected"},
        "tag_list": [{"id", "name", "type": "topic"}]
      }
    }]
  }
}
```

**关键**：
- `id` + `xsec_token` 在 item 顶层，不在 note_card 里
- search 用 `display_title`，read 用 `title`
- cover 图片 URL 用 `url_default`（不是 `url`）
- `model_type: "hot_query"` = 广告位，需过滤

## Anti-detection 注意事项

1. **每条命令间隔 2-5 秒**，不要并发
2. **批量上限 ≤5-8 条/会话**（captcha 阈值）
3. **日累计 ≤30 条**（captcha 日阈值 ~50）
4. **遇到 captcha 立刻停手**，写 cooldown 锁，5-90min 后恢复
5. **先 read 判定内容 → 再互动**，不要反着来
6. **互动后不要立即 read**，等 5min 冷却
7. **评论前先读已有评论**，避免重复观点

## CAPTCHA 熔断锁

```python
from captcha_cooldown import check_cooldown, trigger_cooldown, is_captcha_error

def main():
    if check_cooldown() > 0:
        return 0  # 冷却中，正常退出（cron 不会重试风暴）
    # ... 正常流程 ...
    if is_captcha_error(stderr):
        trigger_cooldown(reason='search:关键词')
        return 0
```

锁文件：`~/.hermes/state/<script_name>_cooldown.json`
默认 90 分钟（cookie 自然解封时间）

## 三层互动去重

| 层 | 位置 | 机制 |
|----|------|------|
| L1 搜索 | `--search` | 过滤已互动的 note/user |
| L2 查询 | `--check <note_id>` | agent 评前必调 |
| L3 执行 | `--post` | 入口前置检查兜底 |

## 已知坑

- **macOS Chrome v20 AES-GCM 加密** — `browser-cookie3` 可能无法解密 → 用 `xhs_inject_cookies.py` 手动注入
- **Python 3.10+** — 系统 Python 3.9 不够，`uv` 自动管
- **search 结果顺序不稳** — 缓存 ID，不缓存位置
- **token 跨搜索不复用** — 同一次 search 的 ID+token 一起用
- **视频下不动** — `sns-video-qc` 走 403 防盗链，只下图片
- **comment flag 是 `--content`** — 不是位置参数
- **post flag 是 `--images`（多次）** — 逗号分隔会报错
- **无图发帖** — 用 PIL 生成文字卡片图（见 `references/text-card-generation.md`）
- **JSON envelope 静默失败** — cookie 过期时返回合法 JSON 到 stdout（`{ok: false}`），检查 `ok` 字段

## 发布工作流

### 实拍照片 → 发布

1. 逐张 `vision_analyze` 提取视觉细节
2. 提取共性+差异
3. 套爆款模板写文案
4. `xhs post --images img1 --images img2 --title "标题" --body "正文" --topic 话题`

### 爆款文案参考

搜同类关键词 → 按互动量排序取 top10 → 读 3-5 篇分析结构 → 参考爆款要素写新内容。关键指标：图文帖 9-15 张图、高收藏率内容是"实用清单型"、标题含实用关键词。

## References

- `references/content-aware-comments.md` — 内容感知评论生成算法
- `references/captcha-cooldown-lock.md` — CAPTCHA 熔断锁模式
- `references/interaction-deduplication.md` — 互动去重机制
- `references/llm-driven-interact-cron.md` — LLM 驱动 cron 架构
- `references/cookie-inject-workaround.md` — Cookie 注入方案
- `references/viral-caption-patterns.md` — 爆款文案套路
- `references/search-extraction-patterns.md` — 多关键词搜索提取模式

## 工具脚本

- `scripts/captcha_cooldown.py` — CAPTCHA 限流 cooldown 锁（可复用）
- `scripts/xhs.sh` — 智能 wrapper（懒加载）
- `scripts/xhs_inject_cookies.py` — Cookie DevTools 导出注入
- `scripts/xhs_workflow.py` — 一站式搜/读/下载
- `scripts/xhs_auto_interact.py` — 规则引擎自动互动（无 LLM）
- `scripts/xhs_llm_helper.py` — LLM 驱动 cron helper（主用）

## 升级

```bash
uv tool upgrade xiaohongshu-cli
```

## 安装说明

**`scripts/xhs.sh` 是智能 wrapper**：
- 检测到 `xhs` 没装 → 提示用户装
- 检测到装了 → 直接 exec 转发所有参数
- 第一次跑会慢 30-60 秒（装依赖），之后秒级
