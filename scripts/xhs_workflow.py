#!/usr/bin/env python3
"""
xhs-cli 一站式工作流: 搜 → 列 → 批量读 → 下载图片到本地.

用法:
    xhs_workflow.py search "关键词" [--sort popular] [--page 1] [--download-ids id1,id2,...]
    xhs_workflow.py read <id> --xsec-token <token> [--download]
    xhs_workflow.py topics "关键词"

环境:
    PATH 中有 xhs (用 ~/.hermes/skills/social-media/xiaohongshu-cli/scripts/xhs.sh 也行)
    或直接通过 wrapper 跑

实测: 2026-06-07 session 搜 "爬山徒步" 验证.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

DEFAULT_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xhs.sh")
SCR = os.environ.get('XHS_SCRIPT', DEFAULT_SCRIPT)


def xhs(*args, timeout=30):
    """Run xhs CLI with --json, raise on captcha."""
    cmd = [SCR] + list(args) + ['--json']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if 'Captcha' in r.stderr or 'WARNING' in r.stderr:
        raise RuntimeError(f'captcha cooldown: {r.stderr.strip()[:200]}')
    if r.returncode != 0:
        raise RuntimeError(f'xhs exit {r.returncode}: stderr={r.stderr[:200]}')
    return json.loads(r.stdout)


def search(keyword, sort='popular', page=1):
    data = xhs('search', keyword, '--sort', sort, '--page', str(page))
    items = data['data']['items']
    print(f"\n搜索 '{keyword}' ({sort}, page {page}) → {len(items)} 条\n")
    print(f"{'#':<3} {'标题':<30} {'👤':<12} {'💗':<6} {'⭐':<5} {'💬':<5} {'ID':<26}")
    print('-' * 95)
    for i, item in enumerate(items, 1):
        card = item['note_card']
        title = (card.get('display_title') or card.get('title') or '无')[:28]
        nickname = card.get('user', {}).get('nickname', '?')[:10]
        info = card.get('interact_info', {})
        print(f"{i:<3} {title:<30} {nickname:<12} "
              f"{info.get('liked_count', '0'):<6} {info.get('collected_count', '0'):<5} "
              f"{info.get('comment_count', '0'):<5} {item['id']}")
    return items


def read_note(note_id, xsec_token, download_to=None):
    data = xhs('read', note_id, '--xsec-token', xsec_token)
    items = data['data']['items']
    if not items:
        print(f'⚠️  {note_id} 无内容')
        return None
    card = items[0]['note_card']
    title = card.get('title', '?')
    author = card.get('user', {}).get('nickname', '?')
    desc = card.get('desc', '')
    n_imgs = len(card.get('image_list', []))
    n_videos = sum(1 for img in card.get('image_list', []) if img.get('stream', {}).get('h264'))
    interact = card.get('interact_info', {})

    print(f"\n=== {title} ===")
    print(f"作者: {author} | 💗 {interact.get('liked_count')} ⭐ {interact.get('collected_count')} 💬 {interact.get('comment_count')}")
    print(f"媒体: {n_imgs} 张 ({n_videos} 视频)")
    print(f"\n{desc[:500]}{'...' if len(desc) > 500 else ''}\n")

    if download_to:
        os.makedirs(download_to, exist_ok=True)
        dl_images(card, download_to)
    return card


def dl_images(card, out_dir):
    """Download images from a note_card. Skip videos (403)."""
    images = card.get('image_list', [])
    n_ok, n_skip = 0, 0
    for i, img in enumerate(images, 1):
        is_video = bool(img.get('stream', {}).get('h264'))
        if is_video:
            n_skip += 1
            continue
        url = (img.get('url_default') or
               (img.get('info_list', [{}])[-1].get('url', '') if img.get('info_list') else ''))
        if not url:
            continue
        url = url.split('?')[0]
        ext = 'webp'  # 小红书图片都是 webp
        path = os.path.join(out_dir, f'{i:02d}.{ext}')
        ok, info = _download(url, path)
        marker = '✅' if ok else '❌'
        print(f"  {marker} {i:02d}.{ext} ({info}{' bytes' if ok else ''})")
        if ok:
            n_ok += 1
    print(f"\n下载: {n_ok} 张图, 跳过 {n_skip} 视频 (防盗链 403)")


def _download(url, path):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer': 'https://www.xiaohongshu.com/',
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            with open(path, 'wb') as f:
                f.write(resp.read())
        return True, os.path.getsize(path)
    except Exception as e:
        return False, str(e)[:80]


def main():
    p = argparse.ArgumentParser(description='xhs-cli 实战工作流 (搜/读/下载)')
    sub = p.add_subparsers(dest='cmd', required=True)

    ps = sub.add_parser('search', help='搜笔记 + 列表展示')
    ps.add_argument('keyword')
    ps.add_argument('--sort', default='popular', choices=['general', 'popular', 'latest'])
    ps.add_argument('--page', type=int, default=1)
    ps.add_argument('--read-ids', help='逗号分隔,搜完自动 read 这些位置(1-indexed)')
    ps.add_argument('--download-to', help='下载 read 到的笔记图片到此目录')

    pr = sub.add_parser('read', help='读单条笔记')
    pr.add_argument('note_id')
    pr.add_argument('--xsec-token', required=True)
    pr.add_argument('--download-to', help='下载图片到此目录')

    pt = sub.add_parser('topics', help='搜话题')
    pt.add_argument('keyword')

    args = p.parse_args()

    if args.cmd == 'search':
        items = search(args.keyword, args.sort, args.page)
        if args.read_ids:
            targets = [int(x) for x in args.read_ids.split(',')]
            for pos in targets:
                if not 1 <= pos <= len(items):
                    print(f'⚠️  位置 {pos} 超出范围 (1-{len(items)})')
                    continue
                item = items[pos - 1]
                sub_dir = None
                if args.download_to:
                    sub = (item['note_card'].get('display_title') or 'note')[:20].replace('/', '_')
                    sub_dir = os.path.join(args.download_to, f'#{pos}-{sub}')
                read_note(item['id'], item['xsec_token'], download_to=sub_dir)
                time.sleep(2)  # 避免 captcha

    elif args.cmd == 'read':
        read_note(args.note_id, args.xsec_token, download_to=args.download_to)

    elif args.cmd == 'topics':
        data = xhs('topics', args.keyword)
        for t in data['data'].get('topic_info_dtos', []):
            print(f"  #{t['name']:<30} 浏览 {t.get('view_num', 0):>10}  id={t['id']}")


if __name__ == '__main__':
    main()
