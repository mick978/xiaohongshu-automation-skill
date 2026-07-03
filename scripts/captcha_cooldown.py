#!/usr/bin/env python3
"""
CAPTCHA / 限流 cooldown 锁模块 — 可被任何自动脚本复用

提供两个 helper：
  - check_cooldown()    → 闸门：返回剩余分钟数；过期/不存在返回 0
  - trigger_cooldown()  → 触发：写锁文件，下次脚本自动跳过

适用场景：任何有 anti-bot 风控或 rate-limit 的自动 cron
  - 小红书 xhs (Captcha / 验证码 / session invalid)
  - 抖音 douyin-cli
  - GitHub API 429
  - Twitter/X rate limit
  - 任何 web scraping

用法：
    from captcha_cooldown import check_cooldown, trigger_cooldown

    def main():
        if check_cooldown() > 0:
            return 0  # 闸门：冷却中直接退出
        # ...正常流程...
        try:
            r = some_api_call()
        except Exception as e:
            if is_rate_limit(e):
                trigger_cooldown(reason='search:关键词')
                return 0

约定：
  - 锁文件: ~/.hermes/state/<script_name>_cooldown.json
  - 默认 90 分钟（cookie 自然解封时间）
  - return 0 让 cron 视为"正常完成"，避免重试风暴
  - 过期自动删锁，无需手动清理
"""
import json
import os
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
STATE_DIR = os.path.expanduser('~/.hermes/state')


def _lock_path(script_name: str) -> str:
    """生成锁文件路径。script_name 用文件名 stem（如 'xhs_auto_interact'）。"""
    return os.path.join(STATE_DIR, f'{script_name}_cooldown.json')


def check_cooldown(script_name: str = 'default') -> int:
    """
    检查 cooldown 锁。返回剩余分钟数；过期/不存在返回 0。
    用作 main() 入口闸门。
    """
    path = _lock_path(script_name)
    if not os.path.exists(path):
        return 0
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        until = datetime.fromisoformat(data['until'])
        now = datetime.now(CST)
        if until > now:
            return int((until - now).total_seconds() // 60) + 1
        # 过期自动删锁
        os.remove(path)
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
    return 0


def trigger_cooldown(script_name: str = 'default',
                     minutes: int = 90,
                     reason: str = 'unknown') -> None:
    """
    写入 cooldown 锁，minutes 分钟内 check_cooldown() 都会拦截。
    reason 字段记录触发位置（search:关键词 / like:note_id / comment:note_id）。
    """
    path = _lock_path(script_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    now = datetime.now(CST)
    until = now + timedelta(minutes=minutes)
    payload = {
        'triggered_at': now.isoformat(),
        'until': until.isoformat(),
        'minutes': minutes,
        'reason': reason,
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"  🔒 [{script_name}] 熔断触发: 暂停 {minutes} 分钟 "
          f"(至 {until.strftime('%H:%M')}, reason={reason})")


def clear_cooldown(script_name: str = 'default') -> bool:
    """手动解锁。返回是否真的删了文件。"""
    path = _lock_path(script_name)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


# === 常用 CAPTCHA / 限流信号（多模式匹配） ===
CAPTCHA_SIGNALS = [
    'Captcha', '验证码', 'NeedVerify', 'IpBlocked',
    'SessionExpired', 'session invalid', 'rate limit',
    '429', 'too many requests', '风控拦截',
]


def is_captcha_error(stderr_text: str) -> bool:
    """判断 stderr 是否命中风控/限流信号。多模式宽容匹配。"""
    if not stderr_text:
        return False
    s = stderr_text.lower()
    return any(sig.lower() in s for sig in CAPTCHA_SIGNALS)


# === CLI 入口（手动调试用） ===
if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("用法:")
        print("  captcha_cooldown check [script_name]   # 看剩余分钟")
        print("  captcha_cooldown trigger [script_name] [minutes] [reason]")
        print("  captcha_cooldown clear [script_name]   # 手动解锁")
        sys.exit(0)

    cmd = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else 'default'

    if cmd == 'check':
        m = check_cooldown(name)
        print(f"[{name}] cooldown 剩余 {m} 分钟" if m else f"[{name}] 无 cooldown")
    elif cmd == 'trigger':
        mins = int(sys.argv[3]) if len(sys.argv) > 3 else 90
        reason = sys.argv[4] if len(sys.argv) > 4 else 'manual'
        trigger_cooldown(name, mins, reason)
    elif cmd == 'clear':
        if clear_cooldown(name):
            print(f"[{name}] 已手动解锁")
        else:
            print(f"[{name}] 无锁可解")
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)
