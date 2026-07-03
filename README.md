# Xiaohongshu Automation Skill

> Auto like, comment, and post on Xiaohongshu (小红书/RedNote) via the `xhs` CLI — with anti-detection, CAPTCHA cooldown, and LLM-driven content-aware comments.

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Platform: macOS](https://img.shields.io/badge/Platform-macOS-lightgrey.svg)]()
[![xhs CLI](https://img.shields.io/badge/Upstream-xhs%20CLI-orange.svg)](https://github.com/jackwener/xiaohongshu-cli)

## What This Does

This is a **Hermes Agent skill** that wraps the [xiaohongshu-cli](https://github.com/jackwener/xiaohongshu-cli) Python package into a complete automation toolkit:

| Feature | Description |
|---------|-------------|
| Search | Search notes by keywords, filter by popularity/recency |
| Read | Read full note content, comments, user profiles |
| Auto Like + Comment | Batch like & comment with content-aware comment generation |
| Post | Publish image notes with title, body, and topics |
| Notifications | Check unread mentions, likes, new followers |
| Anti-Detection | CAPTCHA cooldown lock, daily limits, interaction dedup, Gaussian jitter |
| LLM-Driven | Agent reads full note text + analyzes cover image before writing comments |

## Architecture

```
+-----------------------------------------------------------+
|                 Hermes Agent (LLM)                        |
|  +-----------+  +------------+  +------------+           |
|  | xhs search|->|  xhs read  |->| vision_anlz|           |
|  | (helper)  |  | (full text)|  | (cover img)|           |
|  +-----------+  +------------+  +------------+           |
|         |              |              |                  |
|         +--------------+--------------+                  |
|                        |                                 |
|                 Write comment (LLM)                      |
|                        |                                 |
|  +----------------------------------------------+       |
|  |       xhs_llm_helper.py --post               |       |
|  |  (like + comment + dedup + daily count)      |       |
|  +----------------------------------------------+       |
+-----------------------------------------------------------+
                         |
                         v
                 Xiaohongshu API
```

## Quick Start

### 1. Install xhs CLI

```bash
# Recommended: uv
uv tool install xiaohongshu-cli

# Alternative: pipx
pipx install xiaohongshu-cli
```

### 2. Authenticate

```bash
# Option A: Auto-extract from browser
xhs login

# Option B: QR code login
xhs login --qrcode

# Option C: DevTools cookie injection (if browser extraction fails)
python3 scripts/xhs_inject_cookies.py --stdin < devtools-cookies.json

# Verify
xhs whoami
xhs status --yaml
```

### 3. Use with Hermes Agent

Install this skill to `~/.hermes/skills/social-media/xiaohongshu-cli/`, then ask your agent:

- "搜小红书 成都徒步"
- "给搜索结果前5条点赞+评论"
- "发一篇小红书，标题是'成都周末好去处'"

### 4. Set Up Auto-Interaction Cron (Optional)

```bash
python3 scripts/xhs_llm_helper.py --search    # Find candidates
python3 scripts/xhs_llm_helper.py --status    # Check daily count
python3 scripts/xhs_llm_helper.py --check <note_id>  # Dedup check
python3 scripts/xhs_llm_helper.py --post <url> <note_id> <user_id> "comment text"
```

## Scripts

| Script | Purpose |
|--------|---------|
| `xhs.sh` | Smart wrapper — lazy-installs xhs CLI on first use |
| `xhs_llm_helper.py` | **Main helper** for LLM-driven cron: search, post, check, status, image download |
| `xhs_auto_interact.py` | Standalone rule-based auto-interact (no LLM needed) |
| `xhs_workflow.py` | One-shot workflow: search, list, batch read, download images |
| `xhs_inject_cookies.py` | Cookie injection from DevTools export |
| `captcha_cooldown.py` | Reusable CAPTCHA/rate-limit cooldown lock module |

## Key Features

### Content-Aware Comments

Comments are NOT template-based. The agent:
1. Reads the full note text (`xhs read`)
2. Analyzes the cover image (`vision_analyze`)
3. Writes a unique comment referencing specific details
4. Checks existing comments to avoid repeating points

### Three-Layer Interaction Dedup

| Layer | Where | What |
|-------|-------|------|
| L1 Search | `--search` mode | Filters already-interacted notes/users |
| L2 Query | `--check <note_id>` | Agent calls before commenting |
| L3 Execute | `--post` mode | Pre-post guard catches anything missed |

### CAPTCHA Cooldown Lock

When XHS anti-bot triggers:
- Writes cooldown lock file (`~/.hermes/state/xhs_auto_interact_cooldown.json`)
- All subsequent operations check the lock and skip if active
- Lock auto-expires after configurable timeout (default 5-90 min)
- Returns 0 from cron to prevent retry storms

### Daily Interaction Limit

- Default: 30 interactions/day
- Per-run: max 6-8 interactions
- Counter resets at midnight
- Prevents triggering XHS daily captcha threshold (~50)

## Configuration

Customize `xhs_llm_helper.py` or set environment variables:

```bash
export XHS_KEYWORDS="徒步,骑行,爬山"  # Comma-separated search keywords
export XHS_IMG_DIR="/tmp/xhs_images"  # Image download directory
export XHS_BIN="$(which xhs)"         # Path to xhs binary
```

## File Structure

```
xiaohongshu-automation-skill/
├── SKILL.md                    # Hermes Agent skill definition
├── README.md                   # This file
├── LICENSE                     # Apache-2.0
├── scripts/
│   ├── xhs.sh                  # CLI wrapper
│   ├── xhs_llm_helper.py       # LLM-driven helper (main)
│   ├── xhs_auto_interact.py    # Rule-based auto-interact
│   ├── xhs_workflow.py         # Search/read/download workflow
│   ├── xhs_inject_cookies.py   # Cookie injection
│   └── captcha_cooldown.py     # Reusable cooldown module
└── references/
    ├── README.md               # Full xhs CLI command reference
    ├── SCHEMA.md               # JSON output schema
    ├── content-aware-comments.md
    ├── captcha-cooldown-lock.md
    ├── interaction-deduplication.md
    ├── llm-driven-interact-cron.md
    ├── auto-post-and-interact.md
    ├── cookie-inject-workaround.md
    ├── viral-caption-patterns.md
    ├── photo-to-post-workflow.md
    ├── batch-image-people-filter.md
    ├── search-extraction-patterns.md
    ├── premium-card-design.md
    ├── text-card-generation.md
    └── targeted-user-interaction.md
```

## Upstream

This skill wraps [xiaohongshu-cli](https://github.com/jackwener/xiaohongshu-cli) by [@jackwener](https://github.com/jackwener) (Apache-2.0, 2.1k+ stars).

## License

Apache-2.0 — same as upstream. Commercial use allowed, copyright notice required.

## Disclaimer

This tool is for educational and personal automation purposes. Xiaohongshu's Terms of Service may restrict automated interactions. Use responsibly and at your own risk.
