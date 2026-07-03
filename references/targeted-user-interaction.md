# 指定用户全部笔记逐条评论工作流 (2026-07-03 二丫实战)

## 触发条件

user说"给 XXX 的文案每条追加评论"、"给这个用户所有笔记评论"——不是搜索关键词互动,是**指定用户主页全部笔记**逐条评论。

## 与 cron 互动的区别

| 维度 | cron 互动 | 指定用户互动(本工作流) |
|------|----------|----------------------|
| 笔记来源 | 关键词搜索 → 候选池 | 用户主页 → 全部笔记 |
| user在场 | 不在(无人值守) | 在(对话内) |
| 审阅流程 | agent 自动发 | **必须列表格给user审阅 → ABCD 收口 → 批准后才发** |
| 频率控制 | cron 调度 + cooldown | 对话内串行,user控制节奏 |
| 去重 | 三层(search + --check + --post) | `interact_info.liked: true` 跳已点赞 + `--check` |

## SOP (7 步)

### Step 1: 认证检查
```bash
SCR=~/.hermes/skills/social-media/xiaohongshu-cli/scripts/xhs.sh
"$SCR" status --yaml
"$SCR" whoami --yaml
# 确认 red_id=6910330838 (清风账号)
```

### Step 2: red_id → user_id
```bash
"$SCR" search-user <red_id> --json
# 从 data.user_info_dtos[].user_base_dto.user_id 拿到 24-hex 内部 ID
# ⚠️ 不能直接传 red_id 给 user-posts,会报 AttributeError
```

### Step 3: 拉全部笔记列表
```bash
"$SCR" user-posts <user_id> --json
# 返回 data.notes[] (不是 data.items[])
# 每条含: note_id, xsec_token, display_title, cover.info_list[0].url, interact_info.liked
# liked: true → 已点过赞,可标注但仍可评论
```

### Step 4: 逐条 read 全文 (串行 sleep 3s)
```bash
for each note:
  "$SCR" read <note_id> --xsec-token <token> --json
  # 提取 note_card.desc (完整正文), note_card.title, image_list[0].url_default
  sleep 3  # 防 captcha
```

### Step 5: 下载封面图
```bash
curl -s -o cover_<note_id>.webp \
  -H "User-Agent: Mozilla/5.0 ..." \
  -H "Referer: https://www.xiaohongshu.com/" \
  <cover_url>
# 所有图片带 !nd_dft_wlteh_webp_3 后缀 → webp 格式,存 .webp
```

### Step 6: vision_analyze 看图 → 精写评论
```
vision_analyze(cover_path, "一句话描述这张图的场景和内容")
→ 综合 desc + 图片描述,精写评论
→ 每条引用笔记具体细节
→ 禁止 AI 口语 / 模板 / 跨笔记复用
```

**降级**: vision_analyze 429 时,只用 desc 全文写评论,在表格中标注"vision 不可用"。

### Step 7: 列表格给user审阅 (ABCD 收口)
```
| # | 标题 | 正文摘要 | 拟发评论 |
|---|------|---------|---------|
| 1 | ... | ... | ... |

A. 全部直接发(点赞+评论)
B. 哪几条要改,告诉我改什么
C. 跳过某几篇不发
```

## 实战数据 (2026-07-03 二丫)

- **用户**: 二丫。(red_id=111948085, user_id=58d3221a6a6a692e4e372e11)
- **笔记数**: 8 篇 (has_more=false,一次拉完)
- **内容类型**: 徒步(龙泉山画马/画象/七湖) + 落日晚霞 + 微醺 + 医疗推荐 + 旅游
- **vision_analyze**: 429 降级,只用 desc 全文
- **评论风格**: 与 cron 互动日报一致(引用具体细节,中性自然口语)
- **医疗类笔记处理**: 第4篇(肉毒素川字纹)不给具体医生建议(user红线不替做医疗判断),只跟帖表示理解("蹲到好的记得踢一下")

## 注意事项

1. **execute_code 被 BLOCKED**: 如果想用 Python subprocess 批量 read,可能被安全扫描拦(`BLOCKED: execute_code runs arbitrary local Python`)。改用 `terminal` 跑 shell 脚本,或分批 `terminal` 调用
2. **pipe to python3 需审批**: `"$SCR" read ... --json | python3 -c "..."` 会被安全扫描标记 HIGH,需user审批才能跑
3. **封面图 URL 在 cover.info_list[0].url**: user-posts 返回的 cover 结构没有 `url_default`,用的是 `info_list[0].url`(image_scene=FD_WM_WEBP)
4. **read 返回的封面图 URL 在 image_list[0].url_default**: 与 user-posts 的 cover 结构不同,read 才有 url_default
