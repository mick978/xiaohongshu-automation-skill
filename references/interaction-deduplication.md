# 互动去重机制：三层防护 (2026-07-03 升级)

## 问题
自动点赞+评论脚本每天跑，搜索结果会重复出现已互动过的笔记和同作者的其他笔记。
用户原话："评论之前检查一下是否评论过，已评论过不能再次评论，让别人识别到是AI工作"。

单层去重（只靠 search 阶段过滤）不够——cron agent 可能拿到旧候选 ID 直接调 `--post`，绕过搜索。升级为**三层冗余防护**。

## 防护层级

| 层级 | 机制 | 位置 | 说明 |
|------|------|------|------|
| L1 搜索层 | `is_interacted()` 过滤 | `do_search()` | 搜索候选时跳过已互动 note_id + user_id |
| L2 查询层 | `--check` 主动查 | cron agent 评前必调 | agent 在评论前 `--check <note_id> <user_id>`，只有 `safe_to_interact=true` 才执行 |
| L3 执行层 | `do_post_with_url()` 前置检查 | 代码兜底 | 即使 agent 忘了 --check，`--post` 入口也会拦住，返回 `already_commented` |

## 数据结构

```json
// ~/.hermes/state/xhs_interact_history.json
{
  "interacted_notes": ["note_id_1", "note_id_2", ...],
  "interacted_users": ["user_id_1", "user_id_2", ...]
}
```

## L1: 搜索层过滤（do_search 内置）

```python
hist = load_history()
for item in data["data"]["items"]:
    nid = item.get("id", "")
    uid = item.get("note_card", {}).get("user", {}).get("user_id", "")
    if is_interacted(hist, nid, uid):  # note_id 或 user_id 命中 → 跳过
        continue
```

## L2: 查询层（--check 模式）

```bash
# cron agent 在评论前必须先查
python3 xhs_llm_helper.py --check <note_id> [user_id]
# → {"note_id": "...", "user_id": "...", "already_commented": false, "already_interacted_user": false, "safe_to_interact": true}
# → safe_to_interact=false → 跳过，不点赞不评论
```

## L3: 执行层前置检查（do_post_with_url 兜底）

```python
def do_post_with_url(url, note_id, user_id, comment):
    # ── 去重前置检查（防重复评论）──
    hist = load_history()
    if note_id in hist.get("interacted_notes", []):
        print(json.dumps({"error": "already_commented", "note_id": note_id, "stage": "pre_check"}))
        return
    if user_id and user_id in hist.get("interacted_users", []):
        print(json.dumps({"error": "already_interacted_user", "user_id": user_id, "stage": "pre_check"}))
        return
    # ... 继续 like + comment ...
```

## 存储位置
`~/.hermes/state/xhs_interact_history.json`

## 注意事项
- `user_id` 从 `note_card.user.user_id` 获取，不是 nickname
- 历史文件会持续增长，建议定期清理（>30天的记录可删除）
- cron 任务每次运行都是独立 session，所以必须持久化到文件
- **三层冗余是关键**：即使 cron agent 忘了调 `--check`，`--post` 的前置检查也会兜底拦截
- `--check` 的 `safe_to_interact` 字段是 agent 判断的唯一入口，必须检查此字段为 `true` 才执行评论

## 验证 (2026-07-03)
18/18 ad-hoc 测试通过。覆盖: --check 已互动笔记/新笔记/已知用户/无参数、--post 拦截已评论笔记/已互动用户、--status 不受影响、源码关键字检查、py_compile 语法检查。
