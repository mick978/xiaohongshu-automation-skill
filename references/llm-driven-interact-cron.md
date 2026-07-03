# LLM 驱动 cron 互动架构 (2026-07-03 更新)

## 背景

规则引擎 cron（`xhs_auto_interact.py`）无法做 `vision_analyze`，评论质量达不到用户要求（"评论请看好标题和文案内容，识别图片内容，在精心构思进行评论"）。2026-07-02 架构升级：规则引擎 cron 全部删除，替换为 LLM 驱动 cron。

## 架构对比

| 维度 | 规则引擎 cron（已废弃） | LLM 驱动 cron（当前） |
|------|----------------------|---------------------|
| 评论生成 | 14 维关键词提取 + 模板组合 | agent 逐条读全文 + 看图 + 精写 |
| 图片感知 | ❌ 无 vision_analyze | ✅ 每条笔记 vision_analyze 封面图 |
| 评论质量 | 中等（偶尔牛头不对马嘴） | 高（引用具体细节，接梗，看图说话） |
| Token 成本 | 零 | 每次 cron ~2-5k tokens |
| 速度 | ~30s 跑完 8 条 | ~3-5min 跑完 6 条 |
| 互动上限 | 8 条/次 | 6 条/次 |
| 频次 | 3 次/天 | 2 次/天 |
| 日合计 | ≤24 条 | ≤12 条 |
| 去重 | 单层（search 过滤） | 三层（search + --check + --post 兜底） |

## Cron 配置

| Cron | 时间 | job_id | 单次上限 | toolsets |
|------|------|--------|---------|----------|
| 早场 | `0 10 * * *` | `4ac20c7b4b93` | 6 条 | terminal, vision |
| 晚场 | `0 19 * * *` | `a50b0754a0e6` | 6 条 | terminal, vision |
| **日合计** | | | **≤12 条** | (< 30 安全线) |

- `deliver: all` — 结果推送到所有已连接 channel（飞书等）
- `enabled_toolsets: ["terminal", "vision"]` — agent 需要 terminal 跑 xhs CLI + vision 看图
- 2 频次（10:00 / 19:00），避开机器节奏，日合计 ≤12 条

## Cron Prompt 核心规则（2026-07-03 更新）

```
## 硬性规则
1. 每次运行最多互动 6 条笔记，间隔 5-9 秒
2. 每日上限 30 条（helper --status 查剩余额度）
3. **评论前必须先去重检查**：对每条候选笔记，先运行
   `python3 xhs_llm_helper.py --check <note_id> <user_id>`，
   只有返回 `safe_to_interact: true` 才能评论。
   已评论过的笔记跳过，不点赞不评论。
4. 评论必须基于笔记全文内容+封面图细节
5. 互动完成后推飞书
```

## Helper 脚本: xhs_llm_helper.py

**运行路径**: `~/HermesAgentProject/xhs_llm_helper.py`
**Skill 拷贝**: `scripts/xhs_llm_helper.py`

### CLI 接口

```bash
# 搜索候选笔记（去重 + 日限检查 + cooldown 检查）
python3 xhs_llm_helper.py --search
# → {"candidates": [...], "daily_count": N, "remaining": M}

# 查询是否已互动（2026-07-03 新增，评论前必调）
python3 xhs_llm_helper.py --check <note_id> [user_id]
# → {"note_id": "...", "already_commented": false, "already_interacted_user": false, "safe_to_interact": true}
# → safe_to_interact=false → 跳过

# 执行点赞+评论（单条，内含 L3 前置去重检查）
python3 xhs_llm_helper.py --post "<url>" "<note_id>" "<user_id>" "<comment>"
# → {"like_ok": true, "comment_ok": true, "note_id": "..."}
# → {"error": "already_commented", "stage": "pre_check"} — 已评论过，兜底拦截

# 下载封面图到本地（供 vision_analyze 用）
python3 xhs_llm_helper.py --image "<image_url>"

# 查看状态
python3 xhs_llm_helper.py --status
```

### 职责分离

| 组件 | 职责 |
|------|------|
| `xhs_llm_helper.py` | 搜索/去重/计数/cooldown/发帖/下载图/去重查询 — 纯机械逻辑 |
| Cron agent（LLM） | 读全文 + vision_analyze 看图 + 精写评论 + --check 去重确认 — 认知逻辑 |

### 安全机制（2026-07-03 三层去重升级）

- **Cooldown**: 5 min 熔断（captcha / 验证码 / NeedVerify / IpBlocked / 频率限制）
- **Daily limit**: 30 条/天（跨 cron 共享 `~/.hermes/state/xhs_daily_count.json`）
- **去重: 三层防护**:
  - L1 搜索层: `do_search()` 内置 `is_interacted()` 过滤已互动 note_id + user_id
  - L2 查询层: `--check <note_id> [user_id]` 模式，agent 评前必调，返回 `safe_to_interact: true/false`
  - L3 执行层: `do_post_with_url()` 入口前置检查兜底，返回 `already_commented` / `already_interacted_user`
  - 持久化: `~/.hermes/state/xhs_interact_history.json`
- **Captcha 日累计阈值**: 单日总互动 >50 条 → search 也会被 captcha 拦截

## Cron Prompt 完整模板

```
你是小红书互动 agent。任务：搜索成都户外笔记 → 逐条阅读全文 + 看封面图 → 精心写评论 → 点赞+评论。

## 硬性规则
1. 每次运行最多互动 6 条笔记，间隔 5-9 秒
2. 每日上限 30 条（helper --status 查剩余额度）
3. **评论前必须先去重检查**：对每条候选笔记，先运行
   `python3 ~/HermesAgentProject/xhs_llm_helper.py --check <note_id> <user_id>`，
   只有返回 `safe_to_interact: true` 才能评论。
   已评论过的笔记跳过，不点赞不评论。
4. 评论必须基于笔记全文内容+封面图细节，引用具体信息（路线名/景点名/装备/费用等），禁止模板化/通用化/AI口语
5. 评论长度 30-80 字，自然口语，像真人口气
6. 如果 --search 返回 0 候选或 cooldown_active，直接结束不操作
7. 互动完成后，运行 `hermes send --to feishu:user`
   推送结果摘要（包含每条笔记标题、评论内容、成功/跳过状态）

## 流程
1. `python3 xhs_llm_helper.py --status` 查额度
2. `python3 xhs_llm_helper.py --search "成都徒步" --limit 8` 搜笔记（helper 已内置去重过滤）
3. 对每条候选：
   a. `python3 xhs_llm_helper.py --check <note_id> <user_id>` 二次确认未互动
   b. 如果 safe_to_interact=true：
      - `xhs read "<url>" --json` 读全文
      - `python3 xhs_llm_helper.py --image "<image_url>"` 下载封面图
      - vision_analyze 看封面图内容
      - 根据全文+图片细节写评论
      - `python3 xhs_llm_helper.py --post "<url>" <note_id> <user_id> "<comment>"` 执行点赞+评论
   c. 如果 safe_to_interact=false：跳过，记录"已互动跳过"
4. 汇总结果推飞书
```

## 关键设计决策

1. **为什么不用 `no_agent=True`（纯脚本 cron）**: 纯脚本无法做 `vision_analyze`，无法达到用户评论质量要求
2. **为什么 2 频次不是 3**: LLM cron 每次跑 ~3-5min + 消耗 token，2 次/天（≤12 条）比 3 次/天（≤18 条）更稳
3. **为什么 helper 脚本不直接调 xhs CLI 的 like/comment**: 机械逻辑封装在 helper 里，agent 只管认知逻辑，减少 agent 出错概率
4. **为什么三层去重**: 用户原话"让别人识别到是AI工作"——重复评论同一篇笔记是最容易被识别为 bot 的行为。单靠 search 过滤不够（agent 可能缓存旧候选 ID 直接 --post），必须三层冗余

## Captcha 日累计阈值（2026-07-02 实战发现）

单日手动互动 ~54 条后，`xhs search` 连续 3 次返回 captcha（`xhs my-notes` 仍正常）。

**结论**: captcha 不只看单次频率，还看**日累计**。

**建议**:
- 单日总互动（手动 + cron）≤ 30 条
- 如果当天已手动互动 >20 条，cron 当天应跳过
- captcha 触发后 search 也会被拦，不只是 like/comment
- 冷却时间可能 >5min（实测 2-6 小时才恢复）

## 验证

### 三层去重 ad-hoc 测试 (2026-07-03)
18/18 通过。覆盖:
- `--check` 已互动笔记 → `already_commented=True`, `safe_to_interact=False`
- `--check` 新笔记 → `safe_to_interact=True`
- `--check` 已互动用户 → `already_interacted_user=True`
- `--check` 无参数 → error
- `--post` 已评论笔记 → 拦截 `already_commented` + `stage=pre_check`
- `--post` 已互动用户 → 拦截 `already_interacted_user`
- `--status` 不受影响
- 源码关键字 + py_compile

### Live API 全流程验证 (2026-07-02)
6/6 真实互动全部成功。每条评论引用笔记具体细节，无模板化、无牛头不对马嘴。

### Search API 结构修复 (2026-07-02)
`xhs_llm_helper.py` 旧版用 `note.get("note_id")` → 永远拿到 None → 0 candidates 静默失败。
修复: `item.get("id")` + `item.get("note_card", {})` + `cover.get("url_default", "") or cover.get("url", "")`
