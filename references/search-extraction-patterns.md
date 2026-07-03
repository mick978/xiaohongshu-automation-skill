# Search 候选池抽取 — 标准化模式

从 `xhs search --sort popular --page 1 --json` 返回的 envelope 里抽取 top-N 真实笔记的标准化流程。
**适用场景**: 任何"搜多个关键词 → 拼成候选池 → 后续 read/like/comment/下载"的工作流(单关键词也适用)。

## 核心坑: hot_query 广告位

`xhs search` 的 22 条返回里**通常有 1-2 条**是 `model_type: "hot_query"` 热搜词广告位:

```json
{
  "id": "0eaf933d-faac-4004-aae0-ec0927fae3c3#1783065617039",
  "model_type": "hot_query",
  "note_card": {}          // ← 完全空,没有 user/cover/display_title
}
```

**特征**:
- `id` 是 36 字符 UUID 格式(`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` + `#timestamp`),**不是** 24 位 hex
- `note_card` 是空 dict
- 出现位置: 多数情况在 rank 7(可能因小红书调整而变)

**错误做法**:
```python
# ❌ 用 items[:10] → rank 7 是 hot_query 空壳,后续 read 会报 invalid id
for rank, item in enumerate(items[:10], 1):
    note_id = item["id"]  # 拿到 36 字符 UUID,read 时报"笔记不存在"
```

**正确做法**:
```python
real = [it for it in items if (it.get("model_type") or "note") != "hot_query"]
for rank, item in enumerate(real[:10], 1):  # ← 用 real[:10] 不是 items[:10]
    ...
```

**rank 编号规则**: 用过滤后的列表重新编号 1-10,让每关键词的 rank 1 都是真实笔记。

## 字段抽取清单(每个 item 的字段来源)

| 目标字段 | 字段路径 | 备选路径 | 备注 |
|---------|---------|---------|------|
| note_id | `item["id"]` | — | **顶层**,note_card 里**没有** note_id 字段 |
| xsec_token | `item["xsec_token"]` | — | **顶层**,不在 note_card 里 |
| title | `note_card["display_title"]` | `note_card["title"]` | search 用 display_title;视频笔记**可能都没有** |
| author | `note_card["user"]["nickname"]` | `note_card["user"]["nick_name"]` | 两个字段都存在,优先 nickname |
| liked_count | `note_card["interact_info"]["liked_count"]` | — | **字符串**,需 `int()` |
| collected_count | `note_card["interact_info"]["collected_count"]` | — | **字符串** |
| comment_count | `note_card["interact_info"]["comment_count"]` | — | **字符串** |
| cover_url | `note_card["cover"]["url_default"]` | `note_card["cover"]["url"]` | url 字段可能为空,优先 url_default |

## 视频笔记的边界 case

视频笔记的 `note_card` 经常**没有** `display_title` 和 `title` 字段(不是字段存在但为空,是字段缺失):

```json
{
  "note_card": {
    "type": "video",
    "user": {...},
    "interact_info": {...},
    "cover": {...},
    "image_list": [...],
    "corner_tag_info": [...]
    // ← 没有 display_title / title
  }
}
```

**处理**: 保留空字符串(`""`)输出,**不要** fall back 到 `desc`(那会是正文,不是标题;且 desc 可能很长)。**也不要**编造标题。

## 跨关键词 dedup

多关键词搜索时,同一篇笔记常被多个关键词命中(尤其长尾词重叠多)。
**30 篇候选里 4-5 篇重复很常见**(本次「阿尔沟/阿坝阿尔沟/阿尔沟徒步」实测: 至少 5 篇三关键词全中)。

**下游操作前必做 dedup**,推荐按 `note_id` 去重,保留首次出现位置:

```python
seen = set()
deduped = []
for entry in candidates:  # candidates 是按关键词顺序拼成的列表
    if entry["note_id"] in seen:
        continue
    seen.add(entry["note_id"])
    deduped.append(entry)
```

## 验证清单(写文件前必跑)

```python
import re
hex24 = re.compile(r"^[0-9a-f]{24}$")
errors = []
for x in candidates:
    if not hex24.match(x["note_id"]):
        errors.append(f"BAD_ID: {x['keyword']}#{x['rank']} {x['note_id']}")
    if not x["xsec_token"]:
        errors.append(f"NO_TOKEN: {x['keyword']}#{x['rank']}")
    if not x["cover_url"]:
        errors.append(f"NO_COVER: {x['keyword']}#{x['rank']}")
    # title 可空(视频笔记),不校验
assert not errors, "\n".join(errors)
```

## 写文件: heredoc 的坑

用户要求 `cat > ... <<'JSON_EOF'` 风格时,**带引号的 heredoc 禁止变量展开**:

```bash
# ❌ 字面量写入文件,JSON 是 "'$JSON_PAYLOAD'" 这个字符串
cat > out.json <<'JSON_EOF'
"$JSON_PAYLOAD"
JSON_EOF

# ✅ 正确:不引号 → 变量展开
cat > out.json <<JSON_EOF
$JSON_PAYLOAD
JSON_EOF
```

**或者直接用 Python**:
```python
import json
Path("out.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
```

## 完整可复用脚本

```python
import json, re, subprocess
from pathlib import Path

SCR = "~/.hermes/skills/social-media/xiaohongshu-cli/scripts/xhs.sh"

def xhs_search(kw, sort="popular", page=1):
    r = subprocess.run([SCR, "search", kw, "--sort", sort, "--page", str(page), "--json"],
                       capture_output=True, text=True, timeout=30)
    if "Captcha" in r.stderr or "验证码" in r.stderr:
        raise RuntimeError(f"captcha on kw={kw}")
    data = json.loads(r.stdout)
    if not data.get("ok"):
        raise RuntimeError(f"xhs error: {data.get('error')}")
    return data["data"]["items"]

def extract(item, keyword, rank):
    card = item.get("note_card") or {}
    ii = card.get("interact_info") or {}
    cover = card.get("cover") or {}
    return {
        "keyword": keyword,
        "rank": rank,
        "note_id": item.get("id", ""),
        "xsec_token": item.get("xsec_token", ""),
        "title": card.get("display_title") or card.get("title") or "",  # 视频笔记为空
        "author": (card.get("user") or {}).get("nickname") or "",
        "liked": int(ii.get("liked_count") or 0),
        "collected": int(ii.get("collected_count") or 0),
        "comments": int(ii.get("comment_count") or 0),
        "cover_url": cover.get("url_default") or cover.get("url") or "",
    }

def search_pool(keywords, top_n=10):
    """多关键词 → 去重候选池(按 note_id)"""
    out, seen = [], set()
    for kw in keywords:
        items = xhs_search(kw)
        real = [it for it in items if (it.get("model_type") or "note") != "hot_query"]
        for rank, item in enumerate(real[:top_n], 1):
            entry = extract(item, kw, rank)
            if entry["note_id"] in seen:
                continue  # dedup
            seen.add(entry["note_id"])
            out.append(entry)
    return out

# 使用
candidates = search_pool(["阿尔沟", "阿坝阿尔沟", "阿尔沟徒步"], top_n=10)
Path("search_results.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2))
print(f"DONE: {len(candidates)} 篇候选")
```

## 已知限制

- **搜索顺序不稳**: `popular` 模式跨次请求 `#N` 不一定对应同一篇笔记。**绝不缓存 rank 位置,只缓存 note_id + xsec_token**。
- **跨搜索 token 不复用** (2026-06-14 踩坑): 同一次 search 返回的 ID+token 才匹配;如果先搜 ID 列表再单独搜 token,会大量 404。**正确**: search 一次 → 立刻用返回的 (id, token) 对。
- **未读笔记数 = 0 不代表没结果**: 可能是 cookie 过期,检查 `data["ok"]` 字段(SKILL.md「JSON envelope 静默失败陷阱」节)。
