# CAPTCHA 熔断：Cooldown Lock 模式 (2026-06-15 实战沉淀)

## 问题

自动互动 cron 撞到小红书 CAPTCHA（搜索/点赞/评论任何环节触发）时：

- 当前脚本的应对：**只 `break` 退出本轮**，但**不阻止下一次 cron 触发**
- 后果：明天 10:00 cron 又准时撞同一个 cookie / IP，**每次 0/0/0 还加重风控**
- 用户症状：`扫描 0 / 过滤 0 / 互动 0` 持续多日

**单纯的"再跑一次"是自杀行为**——刚撞完 CAPTCHA 立刻重跑 = 100% 撞墙 + 风险升级。

## 解决方案：Cooldown Lock File

在 `~/.hermes/state/` 写一个 JSON 锁文件，**主入口闸门 + 触发点都检查/写入这个锁**。

### 数据结构

```json
{
  "triggered_at": "2026-06-15T10:01:39.305018+08:00",
  "until": "2026-06-15T11:36:13.918467+08:00",
  "minutes": 90,
  "reason": "search:成都爬山徒步"
}
```

### 三处必须改

1. **main() 入口闸门** — `check_cooldown()` 返回剩余分钟数 > 0 → 直接 `return 0`，不撞库
2. **每个可能触发 CAPTCHA 的点** — search/like/comment 失败时调 `trigger_cooldown(reason=...)` 写锁
3. **CAPTCHA 检测要更宽容** — stderr 不只 `Captcha`，还有：
   - `Captcha triggered`
   - `验证码`
   - `NeedVerifyError`
   - `session invalid` / `IpBlockedError` / `SessionExpiredError`
   - exit code 非 0 且 stdout 为空
   - **🆕 `xhs whoami` / `xhs status` / `xhs search` 在 session expired 时返回 `{ok: false, error: {code: not_authenticated, ...}}` 这种**JSON envelope 到 stdout**（不是 stderr），exit code 0/1 都有可能**。见下面「JSON envelope 静默失败陷阱」

### 🆕 JSON envelope 静默失败陷阱 (2026-06-27 实战踩坑)

`xhs whoami` / `xhs status` 在 session expired 时**不是抛异常**，而是返回合法 JSON envelope：

```json
{"ok": false, "schema_version": "1", "error": {"code": "not_authenticated", "message": "Session expired — please re-login with: xhs login"}}
```

**两个反直觉细节**:
- `xhs whoami --json` → **exit_code 1**（无 stdout 错版） 或 **exit_code 0**（有 envelope）
- `xhs status --yaml` → **exit_code 0**（同一种错，exit 不同！）

**老 `xhs()` helper 的问题代码**（`xhs_auto_interact.py` 早期版本，实测 2026-06-27 仍在用）：

```python
def xhs(*args):
    cmd = [SCR] + list(args) + ['--json']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if 'Captcha' in r.stderr or '验证码' in r.stderr:
        raise RuntimeError('CAPTCHA')
    if r.returncode != 0 and not r.stdout.strip():
        if 'session' in r.stderr.lower() or 'invalid' in r.stderr.lower():
            raise RuntimeError('CAPTCHA')
        raise RuntimeError(f'xhs exit {r.returncode}: {r.stderr[:200]}')
    try:
        return json.loads(r.stdout)   # ⚠️ 这里把 {ok:false} envelope 当成功数据返回
    except json.JSONDecodeError:
        raise RuntimeError(f'JSON parse error: {r.stdout[:200]}')
```

**后果**（2026-06-27 14:00 槽实测）:
- `xhs whoami` 返回 `{ok:false, error.code=not_authenticated}` envelope → helper 直接 `json.loads` 出来 → 返回 dict → **无任何异常**
- 上层 `if not data.get('ok'): ...` 检查缺失（老 search 循环只 `data.get('data', {}).get('items', [])`）
- 搜索循环拿到 0 items → 3 个关键词都 "搜了 0 条" → 没有 CAPTCHA 抛错 → **cooldown 锁不会写**
- 全程 0 报错退出，crontab 写"ok"，但实际 **0/0/0 互动 + 加重风控风险**（无意义的 3 次无效 API 调用 + 后续 6h、13h 还会重撞）

**正确修复**（helper 必须验 envelope `ok` 字段）：

```python
def xhs(*args):
    cmd = [SCR] + list(args) + ['--json']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    stderr_l = r.stderr.lower()
    # 1) stderr 检测（Captcha / session invalid 等老信号）
    if any(sig in stderr_l for sig in ['captcha', '验证码', 'needverify',
                                        'ipblocked', 'sessionexpired',
                                        'session invalid']):
        raise RuntimeError('CAPTCHA')
    # 2) exit 非 0 且 stdout 为空 → 也算 captcha 风控
    if r.returncode != 0 and not r.stdout.strip():
        raise RuntimeError(f'CAPTCHA (exit {r.returncode}, stderr empty)')
    # 3) 解析 JSON 后**必须**验 ok 字段
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f'JSON parse error: {r.stdout[:200]}')
    if not data.get('ok', False):
        err = data.get('error', {}) or {}
        code = err.get('code', 'unknown')
        msg = (err.get('message') or '')[:120]
        if code in ('not_authenticated', 'session_expired',
                    'login_required', 'SessionExpiredError'):
            raise RuntimeError(f'NOT_AUTHENTICATED: {msg}')
        # 其他 error code 也当风控处理（保守）
        raise RuntimeError(f'CAPTCHA (envelope error: {code}: {msg})')
    return data
```

**关键升级**:
- 在 `json.loads` 之后**立刻**检查 `data['ok']`，不只依赖 stderr / exit code
- `not_authenticated` 用单独异常名（`NOT_AUTHENTICATED`）便于上层区分「账号死了」vs「撞 captcha」——前者**不要**写 cooldown 锁（写 cooldown 会让后续 cron 误以为"冷却中"而闷声跳过，但根本问题是账号挂了，cookie 不会自己恢复，得用户手动 `xhs login`）
- 上层调用点按异常名分别处理：
  - `CAPTCHA` → `trigger_cooldown(reason=...)` + `return 0`
  - `NOT_AUTHENTICATED` → `print` 告警 + **`return 0`**（不写 cooldown），让 cron 视为"正常完成"避免重试风暴

### cron 账号验证 prompt 模板

3 频次 cron 的 prompt 现在应该这样写 Step 0（2026-06-27 user明确要求）：

```bash
# Step 0: 必查 — 验证账号身份
~/.hermes/skills/social-media/xiaohongshu-cli/scripts/xhs.sh whoami --json
# 必须返回 user（小红薯683E95CD，运营号）
# 否则直接 abort 推飞书告警，不要碰其他号
```

**user 2026-06-27 强红线**："必须是 user（运营号），否则直接 abort 推飞书告警，不要碰其他号"——`xhs whoami` 的 `data.user.red_id` 字段才是权威。

或者用 Python helper 一行搞定（推荐，可被 `xhs_auto_interact.py` 直接 import）：

```python
import subprocess, json
r = subprocess.run(['~/.hermes/skills/social-media/xiaohongshu-cli/scripts/xhs.sh',
                    'whoami', '--json'], capture_output=True, text=True, timeout=10)
data = json.loads(r.stdout)
if not data.get('ok'):
    print(f"⛔ whoami failed: {data.get('error', {})}")
    raise SystemExit(0)  # return 0，cron 视为"正常完成"
red_id = (data.get('data', {}).get('user', {}) or {}).get('red_id', '')
if red_id != '18951523495':
    print(f"⛔ red_id mismatch: got {red_id}, expected 18951523495 (运营号)")
    raise SystemExit(0)
```

### 完整 Python 实现（可直接复用）

```python
import json
import os
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
COOLDOWN_FILE = os.path.expanduser('~/.hermes/state/xhs_captcha_cooldown.json')
COOLDOWN_MINUTES = 90  # 1.5 小时 = cookie 自然解封时间


def check_cooldown():
    """检查 cooldown 锁。返回剩余分钟数；过期/不存在返回 0。"""
    if not os.path.exists(COOLDOWN_FILE):
        return 0
    try:
        with open(COOLDOWN_FILE, encoding='utf-8') as f:
            data = json.load(f)
        until = datetime.fromisoformat(data['until'])
        now = datetime.now(CST)
        if until > now:
            return int((until - now).total_seconds() // 60) + 1
        os.remove(COOLDOWN_FILE)  # 过期自动删锁
    except Exception:
        try:
            os.remove(COOLDOWN_FILE)
        except OSError:
            pass
    return 0


def trigger_cooldown(reason='unknown'):
    """写入 cooldown 锁，COOLDOWN_MINUTES 分钟内不再尝试。"""
    os.makedirs(os.path.dirname(COOLDOWN_FILE), exist_ok=True)
    now = datetime.now(CST)
    until = now + timedelta(minutes=COOLDOWN_MINUTES)
    payload = {
        'triggered_at': now.isoformat(),
        'until': until.isoformat(),
        'minutes': COOLDOWN_MINUTES,
        'reason': reason,
    }
    with open(COOLDOWN_FILE, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"  🔒 CAPTCHA 熔断触发: 暂停 {COOLDOWN_MINUTES} 分钟 (至 {until.strftime('%H:%M')})")


# === xhs() wrapper 的 CAPTCHA 检测要更宽容 ===
def xhs(*args):
    cmd = [XHS_SCR] + list(args) + ['--json']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    # 多模式 CAPTCHA 检测（不是只匹配 "Captcha"）
    captcha_signals = ['Captcha', '验证码', 'NeedVerify', 'IpBlocked',
                       'SessionExpired', 'session invalid']
    stderr_lower = r.stderr.lower()
    if any(sig.lower() in stderr_lower for sig in captcha_signals):
        raise RuntimeError('CAPTCHA')

    if r.returncode != 0 and not r.stdout.strip():
        raise RuntimeError(f'xhs exit {r.returncode}: {r.stderr[:200]}')

    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f'JSON parse error: {r.stdout[:200]}')


# === main() 入口闸门 ===
def main():
    remaining = check_cooldown()
    if remaining > 0:
        print(f"🛑 CAPTCHA 冷却中，还剩 {remaining} 分钟 → 本次跳过")
        print(f"   手动解除: rm {COOLDOWN_FILE}")
        return 0  # ⚠️ 关键：必须 return 0，cron 会认为"正常完成"，不会重试风暴

    # ... 正常流程 ...
```

### 调用点改造（Step 1 搜索示例）

```python
# ❌ 旧代码：只 print，CAPTCHA 不熔断
for query in SEARCH_QUERIES:
    try:
        data = xhs('search', query, '--sort', 'latest', '--page', '1')
        # ...
    except Exception as e:
        print(f"  搜索「{query}」失败: {e}")
    time.sleep(2)

# ✅ 新代码：CAPTCHA → 写锁 + 立即退出
for query in SEARCH_QUERIES:
    try:
        data = xhs('search', query, '--sort', 'latest', '--page', '1')
        # ...
    except Exception as e:
        err = str(e)
        print(f"  搜索「{query}」失败: {err}")
        if 'CAPTCHA' in err:
            trigger_cooldown(reason=f'search:{query}')
            print(f"🛑 熔断触发 → 本轮结束，避免加重风控")
            return 0  # 不继续下一关键词、不继续整个 cron
    time.sleep(2)
```

## 设计要点

1. **闸门 return 0（不是 1）** — 让 cron 视为"正常完成"，避免重试风暴
2. **过期自动删锁** — 下次正常 cron 触发时自然解锁
3. **reason 字段** — 记录触发位置（`search:关键词` / `like:note_id` / `comment:note_id`），事后分析
4. **手动解锁** — `rm ~/.hermes/state/xhs_captcha_cooldown.json`（user手动介入用）
5. **状态目录** — `~/.hermes/state/`（不是 `data/`），表明是运行期状态而非业务数据

## 适用场景（可推广）

任何"高频调用外部服务 + 有 anti-bot 风控"的自动 cron：

- 小红书 search/like/comment
- 抖音 douyin-cli（如果有）
- GitHub API（429 限流）
- Twitter/X API（rate limit）
- 任何 web scraping 任务

模式统一：**主入口闸门 + 触发点写锁 + JSON 状态文件**。

## 验收清单

补完 cooldown 锁后必跑：

```bash
# 1. 模拟"刚撞过 CAPTCHA" → 验证闸门拦截
python3 -c "
import json, os
from datetime import datetime, timezone, timedelta
CST = timezone(timedelta(hours=8))
now = datetime.now(CST)
os.makedirs(os.path.expanduser('~/.hermes/state'), exist_ok=True)
payload = {
    'triggered_at': now.isoformat(),
    'until': (now + timedelta(minutes=90)).isoformat(),
    'minutes': 90,
    'reason': 'manual_test',
}
with open(os.path.expanduser('~/.hermes/state/xhs_captcha_cooldown.json'), 'w') as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
"
python3 your_script.py  # 应该看到 "🛑 CAPTCHA 冷却中..." 然后 return 0

# 2. 模拟解锁
rm ~/.hermes/state/xhs_captcha_cooldown.json
python3 your_script.py  # 正常执行
```

## 决策原则（user偏好）

- 用户说"再跑一次"（撞墙后）→ **不要直接照做**。先说为什么不安全、给 ABCD 选项（手动解封/脚本打补丁/直接重跑赌博），让用户选
- 单字母回复 = 选最优解，不是"无条件执行"
- "全做/全改" 才是无条件执行
- 见 user.md "规则" 段

## 诊断流程（用户问"X cron 还在跑吗 / 怎么不工作了"）

**正确顺序（2026-06-16 验证）**：

```bash
# 1. 先查 cooldown 锁（不要先跑脚本）
cat ~/.hermes/state/xhs_captcha_cooldown.json 2>/dev/null
# 三个有用字段:
#   - until: 锁到期时间，没到期 = 熔断中
#   - triggered_at: 什么时候触发的
#   - reason: 撞墙的具体动作（"search:关键词" / "manual_test" / "like:note_id"）
# reason="manual_test" = user手动触发的，reason="search:成都爬山" = 自然 cron 撞的

# 2. 看 cron 的 last_run_at + last_status（jobs.json）
#    区分 "脚本退出 0 但锁存在" = 闸门拦截了
#    vs  "脚本退出非 0" = 真正的代码错误

# 3. 看脚本自己的输出日志（不是 agent.log）
ls -lat ~/HermesAgentProject/apt-threat-intel/logs/ 2>/dev/null

# 4. 现在才能决定:
#    - 锁还在 + reason 已知 → 告诉用户"正在冷却，还剩 X 分钟"
#    - 锁不存在 + last_status=ok + last_run_at<几小时前 → 脚本可能跑成功了但 0 互动（看池子）
#    - 锁不存在 + last_status=error → 看真实日志找代码错
```

**反例（2026-06-16 错误示范）**：用户问"自动评论点赞还在跑吗" → 直接 `python3 xhs_auto_interact.py` 验证 → **再次撞 CAPTCHA + 加重风控**。即使 cron 报"ok"，cooldown 锁的 `reason` 字段 + `until` 时间才是真相。**永远先读锁，再决定要不要触发脚本**。

**适用同类场景**（cooldown lock 模式的脚本都适用）：douyin-cli、github API、twitter API、web scraping 任何有 anti-bot 限流的自动 cron。**别再问"它跑没跑"，看 `~/.hermes/state/*_cooldown.json` 就知道了。**
