# 小红书自动化 Skill

[English](README.md) | 简体中文

> 通过 `xhs` 命令行工具自动搜索、点赞、评论、发布小红书笔记 — 带反检测、验证码熔断、LLM 驱动的内容感知评论。

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Platform: macOS](https://img.shields.io/badge/Platform-macOS-lightgrey.svg)]()
[![xhs CLI](https://img.shields.io/badge/Upstream-xhs%20CLI-orange.svg)](https://github.com/jackwener/xiaohongshu-cli)

## 功能概览

这是一个 **Hermes Agent skill**，将 [xiaohongshu-cli](https://github.com/jackwener/xiaohongshu-cli) Python 包封装为完整的自动化工具链：

| 功能 | 说明 |
|------|------|
| 搜索 | 按关键词搜索笔记，支持按热度/时间排序 |
| 阅读 | 读取笔记全文、评论、用户主页 |
| 自动点赞+评论 | 批量互动，评论由 LLM 根据内容生成 |
| 发布 | 发布图文笔记（标题+正文+话题+多图） |
| 通知 | 查看未读 @、点赞、新粉丝 |
| 反检测 | 验证码熔断锁、日限、去重、高斯随机延迟 |
| LLM 驱动 | Agent 先读全文+分析封面图，再写评论 |

## 架构图

```
+-----------------------------------------------------------+
|                 Hermes Agent (LLM)                        |
|  +-----------+  +------------+  +------------+           |
|  | xhs search|->|  xhs read  |->| vision_anlz|           |
|  | (helper)  |  | (full text)|  | (cover img)|           |
|  +-----------+  +------------+  +------------+           |
|         |              |              |                  |
|         +--------------+--------------+                  |
|                        |                                 |
|                 写评论 (LLM)                             |
|                        |                                 |
|  +----------------------------------------------+       |
|  |       xhs_llm_helper.py --post               |       |
|  |  (点赞 + 评论 + 去重 + 日计数)                |       |
|  +----------------------------------------------+       |
+-----------------------------------------------------------+
                         |
                         v
                 小红书 API
```

## 快速开始

### 1. 安装 xhs CLI

```bash
# 推荐：uv
uv tool install xiaohongshu-cli

# 备选：pipx
pipx install xiaohongshu-cli
```

### 2. 登录认证

```bash
# 方式 A：自动从浏览器提取 cookie
xhs login

# 方式 B：扫码登录
xhs login --qrcode

# 方式 C：DevTools cookie 注入（浏览器提取失败时用）
python3 scripts/xhs_inject_cookies.py --stdin < devtools-cookies.json

# 验证
xhs whoami
xhs status --yaml
```

### 3. 配合 Hermes Agent 使用

将本 skill 安装到 `~/.hermes/skills/social-media/xiaohongshu-cli/`，然后对 Agent 说：

- "搜小红书 成都徒步"
- "给搜索结果前5条点赞+评论"
- "发一篇小红书，标题是'成都周末好去处'"

### 4. 设置定时互动 Cron（可选）

```bash
python3 scripts/xhs_llm_helper.py --search    # 搜索候选
python3 scripts/xhs_llm_helper.py --status    # 查看日计数
python3 scripts/xhs_llm_helper.py --check <note_id>  # 去重检查
python3 scripts/xhs_llm_helper.py --post <url> <note_id> <user_id> "评论内容"
```

## 脚本说明

| 脚本 | 用途 |
|------|------|
| `xhs.sh` | 智能封装 — 首次使用自动安装 xhs CLI |
| `xhs_llm_helper.py` | **主 helper**：搜索、互动、去重、计数、图片下载 |
| `xhs_auto_interact.py` | 独立规则引擎互动（无需 LLM） |
| `xhs_workflow.py` | 一站式工作流：搜索→列表→批量阅读→下载图片 |
| `xhs_inject_cookies.py` | DevTools cookie 注入 |
| `captcha_cooldown.py` | 可复用的验证码/限流熔断锁模块 |

## 核心特性

### 内容感知评论

评论**不是模板生成**。Agent 流程：
1. 读取笔记全文（`xhs read`）
2. 分析封面图片（`vision_analyze`）
3. 引用笔记中的具体细节写评论
4. 先读已有评论，避免重复观点

### 三层互动去重

| 层级 | 位置 | 机制 |
|------|------|------|
| L1 搜索 | `--search` 模式 | 过滤已互动过的笔记/用户 |
| L2 查询 | `--check <note_id>` | Agent 评论前必调 |
| L3 执行 | `--post` 模式 | 发帖前兜底检查 |

### 验证码熔断锁

触发反爬检测时：
- 写入冷却锁文件（`~/.hermes/state/xhs_auto_interact_cooldown.json`）
- 后续所有操作检查锁状态，激活中则跳过
- 锁自动过期（默认 5-90 分钟）
- cron 返回 0，防止重试风暴

### 日互动上限

- 默认：30 次/天
- 单次运行：最多 6-8 次
- 计数器每天午夜重置
- 防止触发小红书日验证码阈值（约 50 次）

## 配置

通过环境变量自定义：

```bash
export XHS_KEYWORDS="徒步,骑行,爬山"  # 搜索关键词（逗号分隔）
export XHS_IMG_DIR="/tmp/xhs_images"  # 图片下载目录
export XHS_BIN="$(which xhs)"         # xhs 二进制路径
```

## 目录结构

```
xiaohongshu-automation-skill/
├── SKILL.md                    # Hermes Agent skill 定义
├── README.md                   # 英文文档
├── README_zh.md                # 中文文档
├── LICENSE                     # Apache-2.0
├── scripts/
│   ├── xhs.sh                  # CLI 封装
│   ├── xhs_llm_helper.py       # LLM 驱动 helper（主用）
│   ├── xhs_auto_interact.py    # 规则引擎互动
│   ├── xhs_workflow.py         # 搜索/阅读/下载工作流
│   ├── xhs_inject_cookies.py   # Cookie 注入
│   └── captcha_cooldown.py     # 熔断锁模块
└── references/
    ├── README.md               # xhs CLI 完整命令参考
    ├── SCHEMA.md               # JSON 输出规范
    ├── content-aware-comments.md
    ├── captcha-cooldown-lock.md
    ├── interaction-deduplication.md
    ├── llm-driven-interact-cron.md
    ├── auto-post-and-interact.md
    ├── cookie-inject-workaround.md
    ├── viral-caption-patterns.md
    ├── photo-to-post-workflow.md
    ├── batch-image-people-filter.md
    ├── search-extraction-patterns.md
    ├── premium-card-design.md
    ├── text-card-generation.md
    └── targeted-user-interaction.md
```

## 上游

本 skill 封装了 [@jackwener](https://github.com/jackwener) 的 [xiaohongshu-cli](https://github.com/jackwener/xiaohongshu-cli)（Apache-2.0, 2.1k+ stars）。

## 许可证

Apache-2.0 — 与上游一致，允许商业使用，需保留版权声明。

## 免责声明

本工具仅供学习和个人自动化使用。小红书的服务条款可能限制自动化操作，请自行评估风险，谨慎使用。
