#!/usr/bin/env bash
# xiaohongshu-cli wrapper — 懒加载版
# 设计: 不自动装(避免 camoufox 几百 MB 拖慢首次体验), 只在首次调用时
#       检测到未装 → 提示用户装, 不阻塞当前命令

set -e

XHS_BIN="$(command -v xhs 2>/dev/null || true)"

# === 1. 未装 → 引导用户 ===
if [ -z "$XHS_BIN" ]; then
  cat >&2 <<'EOF'
⚠️  xhs CLI 未安装。

本 skill 需要 xiaohongshu-cli Python 包(2.1k stars 反向工程版 XHS API)。

请选择安装方式(任选一条, 推荐 uv):

  uv tool install xiaohongshu-cli      # 优选: 快, 隔离
  pipx install xiaohongshu-cli        # 备选
  python3 -m pip install --user xiaohongshu-cli   # 不推荐

装完后再次运行当前命令即可。

EOF
  exit 127
fi

# === 2. 已装 → 转发所有参数 ===
exec "$XHS_BIN" "$@"
