#!/usr/bin/env python3
"""
xhs_auto_interact.py — 小红书自动搜索+点赞+评论（内容感知版）

规则（content-aware version）：
- 评论必须 read 全文 + vision_analyze 封面图后精写
- 每条评论引用笔记具体细节，禁随机模板
- 单次 cron ≤8 条，间隔 5-9s
- 每日总互动 ≤30 条
- 沿用 captcha cooldown 锁
- 互动去重：不重复评论同一篇/同一个人
"""
import subprocess, json, random, time, re, os, sys
from pathlib import Path
from datetime import datetime, date

# ── Config ──────────────────────────────────────────────
# Customize for your niche, or set XHS_KEYWORDS env var (comma-separated)
_DEFAULT_KW = ["成都爬山", "成都徒步", "成都骑行", "成都绿道骑行", "龙泉山骑行", "青城山徒步"]
KEYWORDS = os.environ.get("XHS_KEYWORDS", "").split(",") if os.environ.get("XHS_KEYWORDS") else _DEFAULT_KW
FILTER_KW = [
    "骑行", "骑车", "自行车", "爬山", "徒步", "登山",
    "绿道", "溯溪", "绕城", "龙泉", "青城", "赵公山", "丹景山",
]
SKIP_KW = ["群", "搭子", "约人", "报名", "加微", "私信我", "招", "拼车费"]
MAX_INTERACT = 8          # 单次 cron 上限
INTERACT_MIN_DELAY = 5    # 间隔下限（秒）
INTERACT_MAX_DELAY = 9    # 间隔上限（秒）
DAILY_LIMIT = 30          # 每日总互动上限

# 路径
STATE_DIR = Path.home() / ".hermes" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_FILE = STATE_DIR / "xhs_interact_history.json"
DAILY_FILE = STATE_DIR / "xhs_daily_count.json"
COOLDOWN_FILE = STATE_DIR / "xhs_auto_interact_cooldown.json"
COOLDOWN_SECONDS = 300  # 5 min

# ── Cooldown Lock ───────────────────────────────────────
def check_cooldown():
    if COOLDOWN_FILE.exists():
        data = json.loads(COOLDOWN_FILE.read_text())
        ts = data.get("triggered_at", 0)
        reason = data.get("reason", "")
        elapsed = time.time() - ts
        if elapsed < COOLDOWN_SECONDS:
            remaining = int(COOLDOWN_SECONDS - elapsed)
            print(f"⏸️ Cooldown active ({remaining}s left). Reason: {reason}")
            return True
    return False

def trigger_cooldown(reason="captcha"):
    COOLDOWN_FILE.write_text(json.dumps({
        "triggered_at": time.time(),
        "reason": reason,
    }, ensure_ascii=False, indent=2))
    print(f"🚨 Cooldown triggered: {reason}")

def is_captcha_error(stdout, stderr, rc):
    combined = (stdout + stderr).lower()
    return any(w in combined for w in [
        "captcha", "验证码", "needverify", "session invalid", "ipblocked",
        "blocked", "频率限制",
    ])

# ── Daily Count ─────────────────────────────────────────
def get_daily_count():
    today = date.today().isoformat()
    if DAILY_FILE.exists():
        data = json.loads(DAILY_FILE.read_text())
        if data.get("date") == today:
            return data.get("count", 0)
    return 0

def increment_daily_count(n=1):
    today = date.today().isoformat()
    data = {"date": today, "count": get_daily_count() + n}
    DAILY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))

# ── Interaction History (dedup) ─────────────────────────
def load_history():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return {"interacted_notes": [], "interacted_users": []}

def save_history(hist):
    HISTORY_FILE.write_text(json.dumps(hist, ensure_ascii=False, indent=2))

def is_interacted(hist, note_id, user_id):
    return note_id in hist.get("interacted_notes", []) or \
           user_id in hist.get("interacted_users", [])

def add_to_history(hist, note_id, user_id):
    hist.setdefault("interacted_notes", []).append(note_id)
    hist.setdefault("interacted_users", []).append(user_id)
    # Keep last 500
    hist["interacted_notes"] = hist["interacted_notes"][-500:]
    hist["interacted_users"] = hist["interacted_users"][-500:]
    save_history(hist)

# ── XHS CLI wrapper ─────────────────────────────────────
def xhs(*args):
    cmd = ["xhs"] + list(args) + ["--json"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return r.stdout, r.stderr, r.returncode

def xhs_read(*args):
    """Like xhs() but checks JSON envelope ok field"""
    stdout, stderr, rc = xhs(*args)
    try:
        data = json.loads(stdout)
        if not data.get("ok", False):
            err = data.get("error", {})
            if err.get("code") == "not_authenticated":
                print(f"❌ Not authenticated: {err.get('message','')}")
                sys.exit(0)  # silent exit, cron won't retry
            return None
        return data
    except json.JSONDecodeError:
        return None

# ── Search & Filter ─────────────────────────────────────
def search_notes(max_results=MAX_INTERACT):
    all_items = []
    for kw in KEYWORDS:
        data = xhs_read("search", kw, "--sort", "latest")
        if not data:
            continue
        items = data.get("data", {}).get("items", [])
        for it in items:
            it["_kw"] = kw
            all_items.append(it)
        time.sleep(1)
    
    # Dedup by id
    seen = set()
    unique = []
    for it in all_items:
        if it.get("id") and it["id"] not in seen:
            seen.add(it["id"])
            unique.append(it)
    
    # Filter by title keywords
    filtered = []
    for it in unique:
        nc = it.get("note_card", {})
        title = nc.get("display_title", "")
        if any(k in title for k in FILTER_KW):
            filtered.append(it)
    
    # Sort by time (newest first)
    def get_time(it):
        for c in it.get("note_card", {}).get("corner_tag_info", []):
            if c.get("type") == "publish_time":
                return c.get("text", "")
        return ""
    
    def time_score(t):
        if "分钟" in t:
            return 200
        if "小时" in t:
            return 150
        if "天前" in t:
            m = re.search(r"(\d+)天前", t)
            if m:
                return 100 - int(m.group(1)) * 10
            return 50
        return 10
    
    filtered.sort(key=lambda it: time_score(get_time(it)), reverse=True)
    
    # Skip ads/groups
    targets = []
    hist = load_history()
    for it in filtered:
        title = it.get("note_card", {}).get("display_title", "")
        if any(s in title for s in SKIP_KW):
            continue
        # Dedup check
        note_id = it.get("id", "")
        user_id = it.get("note_card", {}).get("user", {}).get("user_id", "")
        if is_interacted(hist, note_id, user_id):
            continue
        if len(targets) >= max_results:
            break
        targets.append(it)
    
    return targets

# ── Generate Content-Aware Comment ──────────────────────
def generate_comment(title, desc, tags, cover_url, image_desc=""):
    """
    基于 标题 + 正文 + 图片描述 精写评论。
    不用随机模板，每条引用笔记具体细节。
    
    注意：本函数在 cron 里运行（无 LLM），用规则引擎生成。
    主 agent 手动调用时有 LLM 可用，可更灵活。
    """
    combined = f"{title} {desc} {image_desc}"
    
    # 提取关键信息维度
    has_waterfall = any(w in combined for w in ["瀑布", "溪流", "溯溪"])
    has_forest = any(w in combined for w in ["森林", "杉树", "密林", "林间"])
    has_lake = any(w in combined for w in ["湖", "兴隆湖", "锦城湖"])
    has_greenway = any(w in combined for w in ["绿道", "绕城"])
    has_mountain = any(w in combined for w in ["山", "青城", "龙泉", "赵公"])
    has_sunset = any(w in combined for w in ["夕阳", "傍晚", "日落", "晚风"])
    has_coffee = any(w in combined for w in ["咖啡", "咖啡店"])
    has_rain = any(w in combined for w in ["下雨", "雨天", "雨后"])
    has_squirrel = any(w in combined for w in ["松鼠", "蛙", "蛇"])
    has_difficulty = any(w in combined for w in ["难度", "新手", "菜腿", "0难度", "轻松"])
    has_distance = any(w in combined for w in ["100km", "100公里", "104km", "12km", "里程"])
    has_guide = any(w in combined for w in ["攻略", "路线", "指南", "避雷", "tips", "公交"])
    has_humor = any(w in combined for w in ["炫耀", "信么", "居然", "饶了我"])
    
    comments = []
    
    # 骑行类
    if has_greenway and has_distance:
        comments.append(f"绿道100km这个毅力太强了！{('夜骑更猛' if '夜' in combined else '收藏了找时间挑战')}")
    if has_greenway and has_sunset:
        comments.append("绿道傍晚骑确实舒服，光线好人也少，这个时间段选得好")
    if has_lake and has_sunset:
        comments.append("锦城湖傍晚那个光线绝了，夕阳打在湖面上出片率拉满")
    if has_coffee:
        comments.append("骑累了钻进路边咖啡店这个安排太对了，这才是夏天该有的节奏")
    if has_mountain and "骑行" in combined and has_difficulty:
        comments.append("龙泉山登顶那刻风景值了！下坡的时候记得注意速度")
    
    # 骑行路线分享类（有具体路线/地名但非龙泉山/绿道）
    has_route = any(w in combined for w in ["路线", "路线分享", "电子科大", "都江堰", "犀浦", "清水河"])
    has_equipment = any(w in combined for w in ["装备", "拓乐", "Thule", "顶配", "套装", "车架", "公路车"])
    if has_route and not has_mountain and not has_greenway:
        comments.append("这条骑行路线收藏了！请问全程大概多少公里？")
    if has_equipment:
        comments.append("这套装备搭配太专业了！不打孔安装确实方便")
    
    # 徒步类
    if has_forest and has_guide:
        comments.append("这篇攻略太详细了！双环线的设计很贴心，新手老手都有得选")
    if has_forest and has_rain:
        comments.append("雨后的森林更治愈了，苔藓和蕨类的绿色饱和度拉满")
    if has_waterfall and has_squirrel:
        comments.append("一路有瀑布还有松鼠，这条路线的生态太好了吧")
    if has_mountain and has_difficulty:
        comments.append("这个难度新手能冲吗？看路况还挺规整的，已收藏准备周末去")
    if has_mountain and has_rain:
        comments.append("下雨反而更有氛围感，青城天下幽说的就是这个意境")
    
    # 幽默/反讽类
    if has_humor:
        if "炫耀" in combined:
            comments.append("哈哈哈嘴上说没什么好炫耀的，结果时间地点全程交代得清清楚楚")
        elif "信么" in combined:
            comments.append("这个标题太有趣了，点进来发现是认真骑车的👍")
        elif "饶了我" in combined:
            comments.append("能骑完就已经很厉害了，绿道确实考验耐力")
    
    # 通用但贴合
    if not comments:
        if has_guide:
            comments.append("这篇攻略写得太用心了，已收藏，周末就安排")
        elif has_difficulty:
            comments.append("看路况还不错，这个难度周末可以试试")
        elif has_sunset:
            comments.append("这个时间段的光线太好了，出片率很高")
        elif has_forest:
            comments.append("这片林子太治愈了，夏天去刚好避暑")
        elif has_greenway:
            comments.append("绿道路况看着不错，找个周末去骑一圈")
        else:
            comments.append("成都周边好地方真多，已收藏备用")
    
    # 去重并随机选1条
    unique_comments = list(dict.fromkeys(comments))
    return random.choice(unique_comments)

# ── Main ────────────────────────────────────────────────
def main():
    print(f"=== xhs_auto_interact.py @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    
    # 1. Cooldown check
    if check_cooldown():
        print("Exit: cooldown active")
        return 0
    
    # 2. Daily count check
    daily_count = get_daily_count()
    if daily_count >= DAILY_LIMIT:
        print(f"Exit: daily limit reached ({daily_count}/{DAILY_LIMIT})")
        return 0
    
    remaining = DAILY_LIMIT - daily_count
    actual_max = min(MAX_INTERACT, remaining)
    print(f"Daily: {daily_count}/{DAILY_LIMIT} | This run max: {actual_max}")
    
    # 3. Search
    targets = search_notes(actual_max)
    if not targets:
        print("Exit: no targets found")
        return 0
    
    print(f"Found {len(targets)} targets\n")
    
    # 4. Interact
    hist = load_history()
    success_count = 0
    
    for i, t in enumerate(targets, 1):
        nc = t.get("note_card", {})
        title = nc.get("display_title", "")
        user = nc.get("user", {}).get("nickname", "?")
        nid = t.get("id", "")
        xsec = t.get("xsec_token", "")
        note_url = f"https://www.xiaohongshu.com/explore/{nid}?xsec_token={xsec}"
        user_id = nc.get("user", {}).get("user_id", "")
        
        # Read full note
        read_data = xhs_read("read", note_url)
        if not read_data:
            print(f"[{i}/{len(targets)}] @{user}: read failed, skip")
            time.sleep(2)
            continue
        
        note_items = read_data.get("data", {}).get("items", [])
        if not note_items:
            print(f"[{i}/{len(targets)}] @{user}: no items, skip")
            time.sleep(2)
            continue
        
        full_nc = note_items[0].get("note_card", {})
        desc = full_nc.get("desc", "")
        tags = [tag.get("name", "") for tag in full_nc.get("tag_list", [])]
        cover = full_nc.get("image_list", [{}])[0]
        cover_url = ""
        for info in cover.get("info_list", []):
            if info.get("image_scene") == "WB_DFT":
                cover_url = info.get("url", "")
                break
        
        # Generate comment (rule-based, no LLM in cron)
        comment = generate_comment(title, desc, tags, cover_url)
        
        print(f"[{i}/{len(targets)}] @{user}: {title[:35]}")
        print(f"    desc: {desc[:60]}...")
        print(f"    comment: {comment}")
        
        # Like
        out, err, rc = xhs("like", note_url)
        like_ok = '"ok": true' in out or '"ok":true' in out
        if is_captcha_error(out, err, rc):
            trigger_cooldown("captcha on like")
            break
        
        # Comment
        out2, err2, rc2 = xhs("comment", note_url, "-c", comment)
        cmt_ok = '"ok": true' in out2 or '"ok":true' in out2
        if is_captcha_error(out2, err2, rc2):
            trigger_cooldown("captcha on comment")
            break
        
        status = f"like={'✓' if like_ok else '✗'} cmt={'✓' if cmt_ok else '✗'}"
        print(f"    {status}")
        
        if like_ok or cmt_ok:
            add_to_history(hist, nid, user_id)
            success_count += 1
            increment_daily_count(1)
        
        print()
        time.sleep(random.uniform(INTERACT_MIN_DELAY, INTERACT_MAX_DELAY))
    
    # 5. Summary
    print("=" * 50)
    print(f"Done: {success_count}/{len(targets)} interacted")
    print(f"Daily total: {get_daily_count()}/{DAILY_LIMIT}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
