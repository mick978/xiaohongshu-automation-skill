---
name: xhs-cookie-inject
description: "Use when xhs-cli reports 'session invalid / guest user' even though Chrome is logged in, or when the wrapper returns the fallback user '小红薯6A22ECF7' (id 6a22cca4...) instead of the real account. Root cause is browser-cookie3 unable to decrypt macOS Chrome v20 AES-GCM cookies in Profile 1. Workaround: paste a1/web_session from Chrome DevTools into ~/.xiaohongshu-cli/cookies.json via xhs_inject_cookies.py — the xhs_cli.cookies module reads this file first (saved_at TTL 7 days) and skips browser extraction entirely."
version: "0.1.0"
author: Hermes Agent
license: MIT
platforms: [macos]
metadata:
  hermes:
    tags: [xiaohongshu, xhs, cookies, chrome-decryption, browser-cookie3, devtools, workaround]
    related_skills: [xiaohongshu-cli, web-scraping-compliance]
---

# xhs Cookie Inject Workaround

## Overview

`xhs-cli` (and the Hermes skill wrapper `xhs.sh`) use `browser_cookie3` to read
Chrome's `Default/Cookies` SQLite. On macOS Chrome v20+, cookies are encrypted
with AES-GCM, and the decryption key lives in the user's keychain — bound to
the Chrome process. **`browser-cookie3` 0.19+ can decrypt, but only from the
`Default` profile.**

This Mac has Chrome set up with **Profile 1** as the active one (no `Default`
profile exists — confirmed via `ls ~/Library/Application Support/Google/Chrome/`).
`browser_cookie3` therefore finds zero xiaohongshu.com cookies, returns empty,
and `xhs_cli` falls back to a generic guest identity (`小红薯6A22ECF7`,
id `6a22cca4000000000103e002`) that fails every authenticated endpoint.

**Workaround**: bypass `browser-cookie3` entirely by writing cookies directly
to `~/.xiaohongshu-cli/cookies.json`. The `xhs_cli.cookies.get_cookies()`
function checks this file **first** (TTL: 7 days) before any browser extraction.
DevTools export → JSON file → `xhs_inject_cookies.py` → xhs uses it
immediately, no keychain/Chrome/restart needed.

## When to use

- `xhs status --yaml` returns `user.id: 6a22cca4...` and `nickname: Unknown`
- `xhs login` reports `Login verification failed: Browser cookies were extracted, but the session appears invalid`
- `xhs whoami` works but every read/post/like/comment returns 401/403
- You just need `xhs like <id>` to work for an automation job and don't want to QR-scan every restart
- The actual xhs account you want to use IS logged in Chrome Profile 1 (you can see the cookies via DevTools)

## When NOT to use

- Twitter/X, Instagram, Weibo, B站, etc. — each has its own CLI
- A brand-new xhs account that isn't logged in Chrome at all — use `xhs login --qrcode` instead
- A public/deployment use case where DevTools copy-paste is not feasible — re-login fresh via QR

## DevTools cookie extraction recipe

In Chrome, with the desired account logged in at https://www.xiaohongshu.com:

1. F12 → Application tab → Storage → Cookies → `https://www.xiaohongshu.com`
2. Copy these keys (the script's REQUIRED_KEYS = a1 + web_session; others are nice-to-have):

| Cookie | Why it matters | Length |
|--------|----------------|--------|
| `a1` | **Required.** User identity token. Server rejects requests without it. | 52 chars |
| `web_session` | **Required.** Session bearer. | 38 chars |
| `webId` | Device fingerprint cookie. | 32 chars |
| `gid` | Guest ID. | 64 chars |
| `id_token` | JWT-style auth. Optional but extends session life. | varies |
| `websectiga` | Anti-bot challenge response. Optional. | 64 chars |
| `x-user-id-creator.xiaohongshu.com` | Creator-portal user id. | 24 hex |

Format on clipboard: one `name=value` per line. The injector script accepts
that, JSON, or a file path.

3. Paste into the injector (see Usage below).
4. Run `xhs whoami --yaml` to verify — you should now see the real nickname
   (e.g. `清风`) and the real `red_id`, not the `小红薯6A22ECF7` fallback.

## Usage

### Quick path: stdin kv format

```bash
cat <<'EOF' | python3 ~/.hermes/skills/social-media/xiaohongshu-cli/scripts/xhs_inject_cookies.py --stdin
a1=19e97ef4cb8jk79dvmzhiw8qth0i28rc79d4e82f330000436552
web_session=030037ad1198d063a5758dfe522d4aba66d21e
webId=264d7d113a66fb59b8a14a918a75ed3e
gid=yjdjWdiW4iWdyjdjWdi4SjYJDYVTWjfh6ux3fiqEYA9x84q83JYFSd8884qK22J8j44WJYj8
EOF
```

### From clipboard (macOS)

```bash
pbpaste | python3 ~/.hermes/skills/social-media/xiaohongshu-cli/scripts/xhs_inject_cookies.py
```

### From a file

```bash
# cookies.txt format (one per line)
python3 ~/.hermes/skills/social-media/xiaohongshu-cli/scripts/xhs_inject_cookies.py ~/cookies.txt
```

### From JSON string

```bash
python3 ~/.hermes/skills/social-media/xiaohongshu-cli/scripts/xhs_inject_cookies.py --json '{"a1":"...","web_session":"..."}'
```

### From DevTools "Copy as JSON" array (2026-06-27 新增, user最常用)

Chrome DevTools → Application → Cookies → 右键 → "Copy as JSON" 输出的是**数组**格式:

```bash
# user直接从对话粘 DevTools 复制内容, 数组自动识别
cat <<'EOF' | python3 ~/.hermes/skills/social-media/xiaohongshu-cli/scripts/xhs_inject_cookies.py --stdin
[
  {"name": "a1", "value": "19cea3bc...", "domain": ".xiaohongshu.com", "path": "/"},
  {"name": "web_session", "value": "040069b3...", "domain": ".xiaohongshu.com", "path": "/"},
  {"name": "id_token", "value": "...", "domain": ".xiaohongshu.com", "path": "/"}
]
EOF
```

脚本的 `smart_parse()` 检测到 `[` 开头 → 走 `parse_devtools_array()` → **只保留 domain 含 `xiaohongshu` / `xhs` 的项**(过滤掉 `chrome-extension://` / 其他杂项)。

**为什么这个最常用**: 用户不需要手动从 DevTools 摘 a1/web_session, 全选 + Copy as JSON + 粘贴 一步到位。16 个 cookie 一次注入。

### Inspect / clear

```bash
# See current cookies.json
python3 ~/.hermes/skills/social-media/xiaohongshu-cli/scripts/xhs_inject_cookies.py --check

# Force clear (next xhs call will try browser extraction again)
python3 ~/.hermes/skills/social-media/xiaohongshu-cli/scripts/xhs_inject_cookies.py --clear
```

## Verification

```bash
# After injection
bash ~/.hermes/skills/social-media/xiaohongshu-cli/scripts/xhs.sh whoami --yaml
# Expected: real nickname + red_id, NOT "小红薯6A22ECF7"

# Test the like/comment path
bash ~/.hermes/skills/social-media/xiaohongshu-cli/scripts/xhs.sh like <note_id> --json
```

## Pitfalls

1. **Cookies expire.** `a1` typically lives 7-30 days; `web_session` 1-7 days.
   Injecting a stale cookie just gets you back to "session invalid". The injector
   prints the merged cookie count + first/last 8 chars of each required key, so
   you can sanity-check you're not injecting yesterday's expired `a1`. Re-extract
   from DevTools if `xhs whoami` still shows `guest: true` after injection.

2. **IP/location mismatch.** xhs server cross-checks the cookie's geo against
   the request IP. If Chrome is on home Wi-Fi but `xhs` runs through a VPN
   (Clash Verge `127.0.0.1:7897`), the request looks like a US/EU IP accessing
   a Chinese account, and XHS rejects it as "suspicious login". MEMORY rule:
   **default to no proxy when using xhs**. Run:
   ```bash
   env -u HTTPS_PROXY -u HTTP_PROXY -u ALL_PROXY \
     bash ~/.hermes/skills/social-media/xiaohongshu-cli/scripts/xhs.sh whoami --yaml
   ```
   If that succeeds but the proxied version fails, you've confirmed IP is the
   problem — unset the proxy in your shell or your terminal profile.

3. **`saved_at` TTL is 7 days.** After 7 days xhs will silently try to refresh
   from Chrome, fail (same AES-GCM issue), and then fall back to the saved file
   anyway. So leaving stale cookies in there for a week doesn't auto-clear
   them — you have to either re-inject or `--clear`.

4. **`scripts/xhs.sh` is the only safe entry point.** It does NOT install
   `xhs` binary on first run; it expects it to already exist via `uv tool
   install xiaohongshu-cli`. Don't try to install it through the wrapper —
   the wrapper's role is just to lazy-redirect to the existing `xhs` binary
   on PATH. If `which xhs` is empty, install it via `uv tool install
   xiaohongshu-cli` first.

5. **Don't symlink `Default/Cookies` to `Profile 1/Cookies` as a "fix".**
   Tested 2026-06-11 — symlink works, `browser-cookie3` reads the bytes
   fine, but Chrome AES-GCM decryption STILL fails because the keychain
   entry is bound to the running Chrome process. Result: `bc3` returns
   cookies that decrypt to garbage; `xhs_cli` rejects them as
   `session_invalid`. The only working path is to skip `bc3` entirely
   via this inject script.

6. **The `6a22cca4...` / `小红薯6A22ECF7` user is XHS's anonymous-fallback
   identity**, not a real account. If you see it in `whoami`, the cookie
   you sent was either empty, expired, or geo-mismatched. Don't post anything
   to that "user" — it'll either 401 or be attributed to no one.

7. **Don't share the script output.** `a1` + `web_session` together grant
   full account access. The script's `--check` mode prints the first 16 +
   last 8 chars of each required key, which is fine for visual confirmation
   but should not be screenshotted, sent over chat, or pasted into logs.

8. **`.env` 全局代理 = XHS 返 guest** (2026-06-11 实战踩坑). 即使 cookie 完美 (a1/web_session/id_token 22 个全有),xhs 走 `HTTPS_PROXY=http://127.0.0.1:7897` 出口 IP 是 `171.216.0.0/16` 美国 ASN,跟国内账号 geo 错位,XHS 返 `小红薯6A22ECF7` (id `6a22cca4...`). 修法: 跑 xhs 前 `unset HTTPS_PROXY HTTP_PROXY ALL_PROXY`,或显式 `env -u HTTPS_PROXY -u HTTP_PROXY -u ALL_PROXY bash xhs.sh whoami --yaml`. MEMORY 规则: **默认不开系统代理**;agent 跑任何 xhs 调用前先 `env | grep -i proxy` 自检,有就 unproxy。

9. **DevTools "Copy as JSON" 输出是数组,不是对象 (2026-06-27 踩坑)**. Chrome DevTools → Application → Cookies → 右键 → "Copy as JSON" 输出的是 `[{name, value, domain, path, expires, ...}, ...]` 数组格式,不是 `{name: value}` 单层对象。agent 看到这种粘贴**必须**先按数组解析再转 dict,不要傻傻当 dict 用。**新版本 `xhs_inject_cookies.py` 已加 `parse_devtools_array()` 自动识别**(`smart_parse()` 检测到 `[` 开头走数组分支,过滤 domain 含 `xiaohongshu`/`xhs` 的项)。如果用老脚本,需先在 agent 端 `cookies = {c["name"]: c["value"] for c in json.loads(input) if "xiaohongshu" in c.get("domain","")}` 转一下。验证:粘完跑 `xhs_inject_cookies.py --check` 看 `N cookies` 数量,16 个 DevTools 数组 → 期望 14-16 个(过滤 chrome-extension 项)

## Reference

- `xhs_cli/cookies.py` (in the `uv tool` venv) — `load_saved_cookies` and
  `save_cookies` define the on-disk JSON schema: `{cookie_name: value, ...,
  "saved_at": <unix_ts>}`. The injector mirrors this exactly.
- `xhs_cli/cookies.py:get_cookies()` line ~481 — first strategy is
  `load_saved_cookies()`, before any browser extraction. The 7-day TTL
  (`_COOKIE_TTL_SECONDS = 604800`) is what determines when browser refresh
  gets retried.
- `~/.hermes/skills/social-media/xiaohongshu-cli/SKILL.md` — full xhs-cli
  command surface (search, read, like, comment, post, etc.).
