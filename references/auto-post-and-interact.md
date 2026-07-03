# 自动互动 + 自动发文脚本模式

> **2026-07-02 user明牌恢复自动互动**（覆盖 07-01 禁令）。新脚本、新 cron、新规则。
> 旧 cron `bbe9b897ad09` / `81e3bfa27a61` 不恢复，新建 3 个全新 cron。
> 07-01 的 `auto-interact-disable-policy-2026-07-01.md` 已归档为历史记录，不再作为约束。

## 自动互动脚本 (xhs_auto_interact.py)

### 脚本位置
- 运行路径: `~/HermesAgentProject/xhs_auto_interact.py`
- Skill 拷贝: `scripts/xhs_auto_interact.py`

### 核心参数（2026-07-02 版）

| 参数 | 值 | 说明 |
|---|---|---|
| MAX_INTERACT | 8 | 单次 cron 上限 |
| DAILY_LIMIT | 30 | 每日总互动上限（跨 cron 共享） |
| 间隔 | 5-9s 随机 | user偏好比 3-5s 更稳 |
| 关键词 | 6 个 | 成都爬山/徒步/骑行/绿道骑行/龙泉山骑行/青城山徒步 |
| 过滤 | 广告/搭子群/约人 | SKIP_KW 列表 |
| 去重 | note_id + user_id | `~/.hermes/state/xhs_interact_history.json` |
| 每日计数 | `xhs_daily_count.json` | 跨 cron 共享，到达上限静默退出 |
| Cooldown | 5 min 熔断 | `xhs_auto_interact_cooldown.json` |

### 评论生成：规则引擎版（cron 模式）

cron 无 LLM 可用，用 14 维规则引擎生成评论：
- 提取维度：瀑布/森林/湖/绿道/山/夕阳/咖啡/雨/松鼠/难度/距离/攻略/幽默/装备
- 按维度组合生成，引用笔记具体细节
- **已知局限**：规则引擎偶尔不够精准（装备帖可能匹配到通用评论），主 agent 手动调用时有 LLM + vision_analyze 质量更高
- 详细算法见 `references/content-aware-comments.md`「升级：全文+图片感知评论」节

### cron 配置（2026-07-02 v2 — LLM 驱动，已替换规则引擎 cron）

| Cron | 时间 | job_id | 单次上限 | 类型 |
|------|------|--------|---------|------|
| 早场 | `0 10 * * *` | `4ac20c7b4b93` | 6 条 | LLM 驱动 (terminal+vision) |
| 晚场 | `0 19 * * *` | `a50b0754a0e6` | 6 条 | LLM 驱动 (terminal+vision) |
| **日合计** | | | **≤12 条** | (< 30 安全线) |

- 旧规则引擎 cron（`32c7ffe5b6fe`/`dbfcb17fe4b5`/`bee3ed61476f`）已删除
- LLM cron 的 agent 每次运行: search → read 全文 → vision_analyze 封面图 → 精写评论 → like+comment
- helper 脚本 `xhs_llm_helper.py` 处理机械逻辑，agent 处理认知逻辑
- `deliver: all` — 结果推送到飞书等已连接 channel
- 详见 `references/llm-driven-interact-cron.md`

### cron 配置（2026-07-02 v1 — 规则引擎，已废弃）

<details>
<summary>旧规则引擎 cron（已删除）</summary>

| Cron | 时间 | job_id |
|---|---|---|
| 早场 | `30 9 * * *` | `32c7ffe5b6fe` |
| 午场 | `30 14 * * *` | `dbfcb17fe4b5` |
| 晚场 | `0 20 * * *` | `bee3ed61476f` |

- 3 频次非匀速（9:30 / 14:30 / 20:00），日合计 ≤24 条
- cron prompt 只跑 `python3 xhs_auto_interact.py`，无 LLM
- **废弃原因**: 规则引擎无法做 vision_analyze，评论质量达不到用户要求
- 脚本 `xhs_auto_interact.py` 保留作为规则引擎参考实现

</details>

### 流程
1. **Cooldown check** — 有锁则静默退出
2. **Daily count check** — 到上限静默退出
3. **多关键词搜索** — 6 个关键词 × latest 排序，合并去重
4. **过滤+排序** — 主题相关 + 时效新 + 跳广告/搭子 + 去重历史
5. **Read 全文** — `xhs read` 拿 desc 完整正文
6. **生成评论** — 规则引擎 14 维提取 → 组合生成
7. **点赞+评论** — 间隔 5-9s
8. **写历史+日计数** — 持久化

### 安全机制
- captcha 检测：`captcha` / `验证码` / `NeedVerify` / `IpBlocked` / `频率限制` 任一命中 → 触发 5min cooldown
- JSON envelope 静默失败：`ok: false` + `not_authenticated` → 静默退出（cookie 过期不会自恢复）
- 互动去重：note_id + user_id 双重去重，历史保留最近 500 条

### 评论质量铁律（2026-07-02 user强纠正）

**用户原话**: "评论请看好标题和文案内容。识别图片内容，在精心构思进行评论。不要太随意，牛头不对马嘴"

**两套评论路径**:
1. **主 agent 手动调用**（有 LLM）: `xhs read` 全文 → `vision_analyze` 封面图 → 综合 desc+图片精写评论 → 每条唯一
2. **cron 自动调用**（无 LLM）: `xhs read` 全文 → 规则引擎 14 维提取 → 组合生成评论

**禁止的做法**:
- ❌ 随机模板评论（"好看"、"666"、"已收藏"）
- ❌ 不读内容直接评论
- ❌ 通用评论用于所有笔记
- ❌ 评论内容与笔记主题完全无关（"牛头不对马嘴"）
- ❌ 跨笔记复用同一评论
- ❌ 反讽/幽默文案不接梗（当真话回复）

**必须的做法**:
- ✅ 评论引用笔记中的具体细节（正文 desc 中的地点/活动/特征/梗）
- ✅ 反讽文案要接梗（"有什么好炫耀的" → "嘴上说没什么好炫耀的，结果时间地点全程交代"）
- ✅ 攻略型笔记要夸结构（双环线/公交直达/避雷tips）
- ✅ 图片有信息量时要用上（品牌/地点/光线/天气）

### 旧版（已废弃，仅存档）

<details>
<summary>旧 3 频次 cron 模式（2026-06-16 ~ 06-27，已废弃）</summary>

- 旧 cron: `bbe9b897ad09`(09:00) / `81e3bfa27a61`(14:00) / `952fe9aaee5c`(20:00) — 07-01 全删
- 旧 MAX_INTERACT=3 → 07-02 改为 8
- 旧 user 验证 → 07-02 移除（不绑特定账号）
- 旧脚本路径 `apt-threat-intel/scripts/xhs_auto_interact.py` → 07-02 改为 `HermesAgentProject/xhs_auto_interact.py`
- 旧评论风格"中性" → 07-02 升级为"全文+图片感知精写"（见 content-aware-comments.md）
- 旧 prompt 模板含 `xhs whoami` 账号验证 → 07-02 移除（cron 只跑脚本）

</details>

<details>
<summary>更早的旧版（2026-06-14，已废弃）</summary>

- 旧 cron: `f7290e133b70` xhs-chengdu-hiking-daily，每天 10:00 一次，5 条/次 → 已删
- 旧安全阈值: 每次 ≤5 条，点赞间隔 4s，评论间隔 5s
- 旧评论风格: "中性"（2026-06-14 用户强纠正）
  - ❌ "蟠龙谷避暑绝了！光看温度就想去🧊"（太夸张）
  - ✅ "蟠龙谷这个温度确实舒服，夏天去刚好"（像真人随口一句）

</details>

## 自动发文脚本 (xhs_auto_post.py)

### 流程
1. **按星期轮换主题** — 8 篇循环（day_of_year % 8）
2. **生成封面大图** — 1080×1440 3:4 竖版（山脉/星月剪影+大字标题）
3. **生成内容卡** — 1080×1440 统一尺寸（渐变背景+结构化文字）
4. **发布** — 封面+内容卡一起上传
5. **记录日志** — post_log.jsonl

### 图片规范
- 所有图片统一 1080×1440（3:4）
- 封面：暗色渐变+山脉/城市剪影+居中大标题+装饰分隔线
- 内容卡：暗色渐变+彩色侧边条+emoji圆点+呼吸留白
- 4 种主题色：forest(绿)/sunset(橙)/midnight(蓝)/arctic(冰蓝)

### cron 配置
- 时间：每天 10:30（互动后 30 分钟）
- 账号验证：先 `xhs whoami` 确认是目标账号
- 推送：飞书日报

## 爆款内容参考流程
1. 搜同类关键词（--sort popular）
2. 按互动量排序取 top 10
3. 读 3-5 篇分析结构（图数/排版/标签/正文）
4. 参考爆款要素写新内容

### 爆款规律（成都户外类）
- 图文帖 9-15 张图
- 高收藏 = 实用清单型（路线合集/装备清单/避坑指南）
- 标题含"公交直达/免费/抄作业/不花钱"
- 话题标签 5-8 个
