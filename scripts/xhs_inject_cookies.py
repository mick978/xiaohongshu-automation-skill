#!/usr/bin/env python3
"""
xhs_inject_cookies.py - 从 DevTools 复制的 cookie 字符串注入到 xhs-cli 的 cookies.json

支持的输入格式 (smart_parse 自动识别):
  模式 1: stdin kv 格式 (a1=xxx, 一行一对)
    xhs_inject_cookies.py <<EOF
    a1=19e97...
    web_session=030037ad...
    EOF

  模式 2: 剪贴板
    pbpaste | xhs_inject_cookies.py

  模式 3: 文件 (kv 或 JSON, 按内容自动判断)
    xhs_inject_cookies.py cookies.txt
    xhs_inject_cookies.py cookies.json   # 单层对象

  模式 4: 单层 JSON 字符串
    xhs_inject_cookies.py --json '{"a1":"...","web_session":"..."}'

  模式 5 (2026-06-27 新增): DevTools "Copy as JSON" 数组 (最常用)
    # Chrome DevTools → Application → Cookies → 右键 → Copy as JSON
    # 输出格式: [{name, value, domain, path, expires, ...}, ...]
    # 自动过滤: 只保留 domain 含 'xiaohongshu' / 'xhs' 的项
    xhs_inject_cookies.py --stdin < devtools-export.json

DevTools 获取步骤 (Chrome):
  1. 打开 https://www.xiaohongshu.com (确保已登录)
  2. F12 → Application → Cookies → https://www.xiaohongshu.com
  3. 右键 cookie 列表 → "Copy all as JSON" (或 "Copy as JSON")
  4. 粘到本脚本 (--stdin 或 pbpaste)

注入后会自动 chmod 0o600, 保存到 ~/.xiaohongshu-cli/cookies.json
然后跑 xhs whoami 验证。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

COOKIE_PATH = Path.home() / ".xiaohongshu-cli" / "cookies.json"

# xhs 后端验证必须的 cookie key(其他可选)
REQUIRED_KEYS = ["a1", "web_session"]


def parse_kv_text(text: str) -> dict[str, str]:
    """解析 'a1=xxx\nwebId=yyy' 格式"""
    cookies = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            print(f"⚠️  skip invalid line: {line[:50]}", file=sys.stderr)
            continue
        k, v = line.split("=", 1)
        cookies[k.strip()] = v.strip()
    return cookies


def parse_devtools_array(obj) -> dict[str, str]:
    """
    解析 Chrome DevTools 'Application → Cookies → Copy as JSON' 输出
    格式: [{name, value, domain, path, expires, httpOnly, secure, sameSite, ...}, ...]
    只取 xiaohongshu.com / xhs 域名下的 cookie, 过滤掉 chrome-extension:// 等
    """
    cookies = {}
    skipped_domains = set()
    for c in obj:
        name = c.get("name")
        value = c.get("value")
        domain = c.get("domain", "")
        if not name or value is None:
            continue
        if "xiaohongshu" not in domain and "xhs" not in domain:
            skipped_domains.add(domain)
            continue
        cookies[name] = value
    if skipped_domains:
        print(
            f"   ℹ️  skipped {len(skipped_domains)} non-xhs domains: {sorted(skipped_domains)[:3]}...",
            file=sys.stderr,
        )
    return cookies


def smart_parse(text: str) -> dict[str, str]:
    """
    智能识别输入格式:
    - JSON 数组 of {name, value, ...} (DevTools Copy as JSON) → parse_devtools_array
    - JSON 对象 {a1: ..., web_session: ...} → 直接用
    - name=value 行 (kv 格式) → parse_kv_text
    """
    stripped = text.lstrip()
    if stripped.startswith("["):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as e:
            print(f"❌ invalid JSON array: {e}", file=sys.stderr)
            sys.exit(1)
        if not isinstance(obj, list):
            print(f"❌ expected JSON array, got {type(obj).__name__}", file=sys.stderr)
            sys.exit(1)
        return parse_devtools_array(obj)
    elif stripped.startswith("{"):
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as e:
            print(f"❌ invalid JSON object: {e}", file=sys.stderr)
            sys.exit(1)
        if not isinstance(obj, dict):
            print(f"❌ expected JSON object, got {type(obj).__name__}", file=sys.stderr)
            sys.exit(1)
        return obj
    else:
        return parse_kv_text(text)


def main():
    ap = argparse.ArgumentParser(
        description="注入 cookie 到 xhs-cli (绕过 Chrome v20 AES-GCM 加密坑)"
    )
    ap.add_argument("file", nargs="?", help="cookie 文件 (kv 或 json)")
    ap.add_argument("--json", help="JSON 字符串: '{\"a1\":\"...\"}'")
    ap.add_argument("--stdin", action="store_true", help="强制从 stdin 读 kv 格式")
    ap.add_argument("--check", action="store_true", help="只看现有 cookies.json, 不写")
    ap.add_argument("--clear", action="store_true", help="清空 cookies.json (触发下次 xhs login)")
    args = ap.parse_args()

    if args.clear:
        if COOKIE_PATH.exists():
            COOKIE_PATH.unlink()
            print(f"🗑️  deleted {COOKIE_PATH}")
        else:
            print("no cookies.json to delete")
        return

    if args.check:
        if COOKIE_PATH.exists():
            data = json.loads(COOKIE_PATH.read_text())
            data.pop("saved_at", None)
            age_h = (time.time() - float(data.pop("saved_at", 0))) if "saved_at" in data else 0
            print(f"📄 {COOKIE_PATH}")
            print(f"   {len(data)} cookies, age {age_h/3600:.1f}h")
            for k in REQUIRED_KEYS:
                v = data.get(k, "")
                print(f"   {k}: {v[:20]}... ({len(v)} chars)" if v else f"   {k}: MISSING")
        else:
            print(f"❌ {COOKIE_PATH} not found")
        return

    # 读 cookie
    if args.json:
        try:
            new_cookies = smart_parse(args.json)
        except SystemExit:
            raise
        except Exception as e:
            print(f"❌ parse error: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.stdin or args.file is None or args.file == "-":
        text = sys.stdin.read()
        new_cookies = smart_parse(text)
    else:
        path = Path(args.file).expanduser()
        if not path.exists():
            print(f"❌ {path} not found", file=sys.stderr)
            sys.exit(1)
        text = path.read_text()
        new_cookies = smart_parse(text)

    # 必填检查
    missing = [k for k in REQUIRED_KEYS if k not in new_cookies or not new_cookies[k]]
    if missing:
        print(f"❌ missing required cookies: {missing}", file=sys.stderr)
        print(f"   required: {REQUIRED_KEYS}", file=sys.stderr)
        print(f"   got: {list(new_cookies.keys())}", file=sys.stderr)
        sys.exit(2)

    # 合并现有(保留 webId/gid 之类,即使没在本次传)
    existing = {}
    if COOKIE_PATH.exists():
        try:
            existing = json.loads(COOKIE_PATH.read_text())
            existing.pop("saved_at", None)
        except (OSError, json.JSONDecodeError):
            pass

    merged = {**existing, **new_cookies}
    merged["saved_at"] = time.time()

    # 写盘
    COOKIE_PATH.parent.mkdir(parents=True, exist_ok=True)
    COOKIE_PATH.write_text(json.dumps(merged, indent=2))
    COOKIE_PATH.chmod(0o600)

    print(f"✅ wrote {len(merged)-1} cookies to {COOKIE_PATH}")
    for k in REQUIRED_KEYS:
        v = merged.get(k, "")
        if v:
            print(f"   {k}: {v[:16]}...{v[-8:]} ({len(v)} chars)")

    print(f"\n下一步: 跑 xhs whoami --yaml 验证")


if __name__ == "__main__":
    main()
