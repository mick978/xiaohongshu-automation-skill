#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xhs_llm_helper.py — Helper for LLM-driven xhs interaction.
  --search                          : Search keywords, dedup, check limits → output JSON candidates
  --check <note_id> [user_id]       : Check if note/user already interacted → safe_to_interact boolean
  --post <url> <note_id> <user_id> "<comment>"  : Like + comment + update history (with pre_check dedup guard)
  --status                          : Show daily count + cooldown status
  --image <url>                     : Download image to /tmp for vision_analyze (auto-tracked for cleanup)
  --cleanup                         : Manually delete all tracked downloaded images
  --publish --images <dir> --title "标题" [--body "正文"]  : Post a note, then delete local images on success
"""
import sys, os, json, subprocess, time, urllib.request
from pathlib import Path
from datetime import date
from typing import Optional, List, Dict, Any

# ── Paths ──
STATE_DIR = Path.home() / ".hermes" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_FILE = STATE_DIR / "xhs_interact_history.json"
DAILY_FILE = STATE_DIR / "xhs_daily_count.json"
COOLDOWN_FILE = STATE_DIR / "xhs_auto_interact_cooldown.json"
IMG_DIR = Path(os.environ.get("XHS_IMG_DIR", str(Path.home() / ".hermes" / "state" / "xhs_images")))
IMG_CLEANUP_FILE = STATE_DIR / "xhs_img_cleanup.json"  # tracks downloaded images for auto-cleanup

# ── Config ──
# Customize for your niche, or set XHS_KEYWORDS env var (comma-separated)
_DEFAULT_KW = ["成都爬山", "成都徒步", "成都骑行", "成都绿道骑行", "龙泉山徒步", "青城山徒步"]
KEYWORDS = os.environ.get("XHS_KEYWORDS", "").split(",") if os.environ.get("XHS_KEYWORDS") else _DEFAULT_KW
MAX_CANDIDATES = 6
DAILY_LIMIT = 30
COOLDOWN_SECONDS = 300
XHS_BIN = os.environ.get("XHS_BIN", os.path.expanduser("~/.local/bin/xhs"))

# ── State functions ──
def load_history() -> Dict:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return {"interacted_notes": [], "interacted_users": []}

def save_history(hist: Dict):
    HISTORY_FILE.write_text(json.dumps(hist, ensure_ascii=False, indent=2))

def is_interacted(hist: Dict, note_id: str, user_id: str) -> bool:
    return note_id in hist.get("interacted_notes", []) or user_id in hist.get("interacted_users", [])

def add_to_history(hist: Dict, note_id: str, user_id: str):
    hist.setdefault("interacted_notes", []).append(note_id)
    hist.setdefault("interacted_users", []).append(user_id)
    save_history(hist)

def get_daily_count() -> int:
    today = date.today().isoformat()
    if DAILY_FILE.exists():
        data = json.loads(DAILY_FILE.read_text())
        if data.get("date") == today:
            return data.get("count", 0)
    return 0

def increment_daily_count(n: int = 1):
    today = date.today().isoformat()
    count = get_daily_count()
    DAILY_FILE.write_text(json.dumps({"date": today, "count": count + n}))

def check_cooldown() -> bool:
    if not COOLDOWN_FILE.exists():
        return False
    data = json.loads(COOLDOWN_FILE.read_text())
    elapsed = time.time() - data.get("triggered_at", 0)
    if elapsed < data.get("cooldown_seconds", COOLDOWN_SECONDS):
        return True
    COOLDOWN_FILE.unlink()
    return False

def trigger_cooldown(reason: str):
    COOLDOWN_FILE.write_text(json.dumps({
        "triggered_at": time.time(),
        "reason": reason,
        "cooldown_seconds": COOLDOWN_SECONDS
    }))

# ── XHS CLI wrapper ──
def run_xhs(args: List[str]) -> tuple:
    cmd = [XHS_BIN] + args
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return r.stdout, r.stderr, r.returncode

def is_captcha_error(stdout: str, stderr: str, rc: int) -> bool:
    combined = (stdout + stderr).lower()
    signals = ["captcha", "验证码", "needverify", "频率限制", "rate limit", "too many requests", "429"]
    return any(s in combined for s in signals)

# ── Search mode ──
def do_search():
    if check_cooldown():
        print(json.dumps({"error": "cooldown_active"}))
        return

    daily = get_daily_count()
    if daily >= DAILY_LIMIT:
        print(json.dumps({"error": "daily_limit_reached", "count": daily}))
        return

    remaining = DAILY_LIMIT - daily
    max_out = min(MAX_CANDIDATES, remaining)

    hist = load_history()
    seen_ids = set()
    candidates = []

    for kw in KEYWORDS:
        if len(candidates) >= max_out:
            break
        try:
            stdout, stderr, rc = run_xhs(["search", kw, "--sort", "latest", "--json"])
            if rc != 0:
                continue
            data = json.loads(stdout)
            if not data.get("ok"):
                continue
            for item in data.get("data", {}).get("items", []):
                if len(candidates) >= max_out:
                    break
                nc = item.get("note_card", {})
                nid = item.get("id", "")
                uid = nc.get("user", {}).get("user_id", "")
                if not nid or nid in seen_ids:
                    continue
                if is_interacted(hist, nid, uid):
                    continue
                seen_ids.add(nid)
                xsec_token = item.get("xsec_token", "")
                url = f"https://www.xiaohongshu.com/explore/{nid}?xsec_token={xsec_token}"
                cover = nc.get("cover", {})
                image_url = cover.get("url_default", "") or cover.get("url", "") if isinstance(cover, dict) else ""
                candidates.append({
                    "note_id": nid,
                    "user_id": uid,
                    "title": nc.get("display_title", ""),
                    "desc": nc.get("desc", "")[:200],
                    "url": url,
                    "image_url": image_url,
                    "nickname": nc.get("user", {}).get("nickname", ""),
                    "liked_count": nc.get("interact_info", {}).get("liked_count", ""),
                    "keyword": kw
                })
        except Exception:
            continue
        time.sleep(2)

    print(json.dumps({"candidates": candidates, "daily_count": daily, "remaining": remaining}, ensure_ascii=False))

# ── Post mode ──
def do_post_with_url(url: str, note_id: str, user_id: str, comment: str):
    if check_cooldown():
        print(json.dumps({"error": "cooldown_active"}))
        return

    # ── 去重前置检查（防重复评论）──
    hist = load_history()
    if note_id in hist.get("interacted_notes", []):
        print(json.dumps({"error": "already_commented", "note_id": note_id, "stage": "pre_check"}))
        return
    if user_id and user_id in hist.get("interacted_users", []):
        print(json.dumps({"error": "already_interacted_user", "user_id": user_id, "stage": "pre_check"}))
        return

    # Like
    stdout, stderr, rc = run_xhs(["like", url, "--json"])
    if is_captcha_error(stdout, stderr, rc):
        trigger_cooldown("captcha during like")
        print(json.dumps({"error": "captcha", "stage": "like"}))
        return
    like_ok = False
    try:
        like_ok = json.loads(stdout).get("ok", False)
    except:
        pass

    time.sleep(3)

    # Comment
    stdout2, stderr2, rc2 = run_xhs(["comment", note_id, "-c", comment, "--json"])
    if is_captcha_error(stdout2, stderr2, rc2):
        trigger_cooldown("captcha during comment")
        print(json.dumps({"error": "captcha", "stage": "comment", "like_ok": like_ok}))
        return
    comment_ok = False
    try:
        comment_ok = json.loads(stdout2).get("ok", False)
    except:
        pass

    # Update history + daily count
    if like_ok or comment_ok:
        hist = load_history()
        add_to_history(hist, note_id, user_id)
        increment_daily_count(1)

    # Auto-cleanup downloaded images after interaction
    deleted = cleanup_images()
    if deleted:
        pass  # silent in JSON mode; could add to response if needed

    print(json.dumps({
        "like_ok": like_ok,
        "comment_ok": comment_ok,
        "note_id": note_id,
        "images_cleaned": deleted
    }, ensure_ascii=False))

# ── Check mode (query whether a note has been interacted) ──
def do_check(note_id: str, user_id: str = ""):
    hist = load_history()
    note_seen = note_id in hist.get("interacted_notes", [])
    user_seen = user_id and user_id in hist.get("interacted_users", [])
    print(json.dumps({
        "note_id": note_id,
        "user_id": user_id,
        "already_commented": note_seen,
        "already_interacted_user": user_seen,
        "safe_to_interact": not note_seen and not user_seen
    }, ensure_ascii=False))

# ── Status mode ──
def do_status():
    print(json.dumps({
        "daily_count": get_daily_count(),
        "daily_limit": DAILY_LIMIT,
        "cooldown_active": check_cooldown(),
        "history_count": len(load_history().get("interacted_notes", []))
    }, ensure_ascii=False))

# ── Image download mode ──
def do_image(url: str) -> Optional[str]:
    """Download image to IMG_DIR, register for auto-cleanup, return path."""
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    # Determine extension
    ext = ".jpg"
    for e in [".png", ".jpg", ".jpeg", ".webp"]:
        if e in url.lower():
            ext = e
            break
    fname = f"xhs_img_{int(time.time())}{ext}"
    fpath = IMG_DIR / fname
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.xiaohongshu.com/"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            fpath.write_bytes(resp.read())
        # Register for auto-cleanup
        cleanup_list: List[str] = []
        if IMG_CLEANUP_FILE.exists():
            try:
                cleanup_list = json.loads(IMG_CLEANUP_FILE.read_text())
            except:
                pass
        cleanup_list.append(str(fpath))
        IMG_CLEANUP_FILE.write_text(json.dumps(cleanup_list, ensure_ascii=False))
        print(json.dumps({"path": str(fpath), "ok": True}))
        return str(fpath)
    except Exception as e:
        print(json.dumps({"error": str(e), "ok": False}))
        return None

# ── Cleanup downloaded images ──
def cleanup_images():
    """Delete all tracked downloaded images. Called after interaction is done."""
    if not IMG_CLEANUP_FILE.exists():
        return 0
    try:
        cleanup_list = json.loads(IMG_CLEANUP_FILE.read_text())
    except:
        cleanup_list = []
    deleted = 0
    for fpath_str in cleanup_list:
        try:
            p = Path(fpath_str)
            if p.exists():
                p.unlink()
                deleted += 1
        except:
            pass
    IMG_CLEANUP_FILE.unlink()
    return deleted

# ── Main ──
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: xhs_llm_helper.py [--search|--post|--check|--status|--image|--cleanup|--publish]")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "--search":
        do_search()
    elif mode == "--status":
        do_status()
    elif mode == "--check":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "need: note_id [user_id]"}))
            sys.exit(1)
        nid = sys.argv[2]
        uid = sys.argv[3] if len(sys.argv) > 3 else ""
        do_check(nid, uid)
    elif mode == "--image":
        if len(sys.argv) < 3:
            print(json.dumps({"error": "need url"}))
            sys.exit(1)
        do_image(sys.argv[2])
    elif mode == "--cleanup":
        deleted = cleanup_images()
        print(json.dumps({"images_cleaned": deleted, "ok": True}))
    elif mode == "--publish":
        # --publish --images <dir> --title "标题" --body "正文"
        # Publishes a note, then deletes the local image files.
        import shutil
        title = ""
        body = ""
        img_dir = ""
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--title" and i + 1 < len(sys.argv):
                title = sys.argv[i + 1]; i += 2
            elif sys.argv[i] == "--body" and i + 1 < len(sys.argv):
                body = sys.argv[i + 1]; i += 2
            elif sys.argv[i] == "--images" and i + 1 < len(sys.argv):
                img_dir = sys.argv[i + 1]; i += 2
            else:
                i += 1
        if not title or not img_dir:
            print(json.dumps({"error": "need: --images <dir> --title \"标题\" [--body \"正文\"]"}))
            sys.exit(1)
        # Collect image files
        img_path = Path(img_dir)
        if not img_path.is_dir():
            print(json.dumps({"error": f"image dir not found: {img_dir}"}))
            sys.exit(1)
        img_files = sorted([f for f in img_path.iterdir()
                           if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")])
        if not img_files:
            print(json.dumps({"error": "no image files found"}))
            sys.exit(1)
        # Build xhs post command
        post_args = ["post"]
        for f in img_files:
            post_args += ["--images", str(f)]
        post_args += ["--title", title]
        if body:
            post_args += ["--body", body]
        stdout, stderr, rc = run_xhs(post_args)
        post_ok = False
        try:
            post_ok = json.loads(stdout).get("ok", False)
        except:
            pass
        # Delete local images after successful post
        files_deleted = 0
        if post_ok:
            for f in img_files:
                try:
                    f.unlink()
                    files_deleted += 1
                except:
                    pass
            # Also try to remove the directory if empty
            try:
                img_path.rmdir()
            except:
                pass
        print(json.dumps({
            "post_ok": post_ok,
            "files_deleted": files_deleted,
            "dir_removed": not img_path.exists(),
            "stderr": stderr[:200] if stderr else ""
        }, ensure_ascii=False))
    elif mode == "--post":
        # --post <url> <note_id> <user_id> "<comment>"
        if len(sys.argv) < 6:
            print(json.dumps({"error": "need: url note_id user_id comment"}))
            sys.exit(1)
        do_post_with_url(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)
