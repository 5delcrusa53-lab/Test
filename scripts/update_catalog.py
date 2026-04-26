#!/usr/bin/env python3
"""
Aether catalog updater.

Reads a list of YouTube channel handles/URLs/IDs from `scripts/channels.txt`,
fetches each channel's public RSS feed (no API key needed), and writes
`catalog.json` at the repo root.
"""

import json
import re
import sys
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANNELS_FILE = REPO_ROOT / 'scripts' / 'channels.txt'
OUTPUT_FILE = REPO_ROOT / 'catalog.json'

USER_AGENT = 'Mozilla/5.0 (compatible; AetherBot/1.0)'
TIMEOUT = 20

NS = {
    'atom': 'http://www.w3.org/2005/Atom',
    'yt':   'http://www.youtube.com/xml/schemas/2015',
    'media': 'http://search.yahoo.com/mrss/',
}


def http_get(url):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode('utf-8', errors='ignore')


def http_get_bytes(url):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def resolve_channel_id(token):
    token = token.strip()
    if not token or token.startswith('#'):
        return None
    if re.fullmatch(r'UC[\w-]{20,}', token):
        return token
    if token.startswith('@'):
        url = f'https://www.youtube.com/{token}'
    elif token.startswith('http'):
        url = token
    else:
        url = f'https://www.youtube.com/@{token}'
    try:
        html = http_get(url)
    except Exception as e:
        print(f'  ! Could not fetch {url}: {e}', file=sys.stderr)
        return None
    m = re.search(r'"channelId"\s*:\s*"(UC[\w-]{20,})"', html)
    if m:
        return m.group(1)
    m = re.search(r'/channel/(UC[\w-]{20,})', html)
    if m:
        return m.group(1)
    print(f'  ! No channelId found on {url}', file=sys.stderr)
    return None


def fetch_channel_videos(channel_id):
    rss_url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'
    try:
        body = http_get_bytes(rss_url)
    except Exception as e:
        print(f'  ! RSS fetch failed for {channel_id}: {e}', file=sys.stderr)
        return []
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        print(f'  ! Bad XML from {channel_id}: {e}', file=sys.stderr)
        return []
    chan_name_el = root.find('atom:author/atom:name', NS)
    channel_name = chan_name_el.text if chan_name_el is not None else channel_id
    videos = []
    for entry in root.findall('atom:entry', NS):
        vid_el = entry.find('yt:videoId', NS)
        title_el = entry.find('atom:title', NS)
        published_el = entry.find('atom:published', NS)
        if vid_el is None or title_el is None:
            continue
        views = None
        stats = entry.find('media:group/media:community/media:statistics', NS)
        if stats is not None:
            views_attr = stats.get('views')
            if views_attr and views_attr.isdigit():
                views = int(views_attr)
        videos.append({
            'id': vid_el.text,
            'title': title_el.text,
            'channel': channel_name,
            'channelId': channel_id,
            'published': published_el.text if published_el is not None else None,
            'views': views,
        })
    return videos


def read_channel_list():
    if not CHANNELS_FILE.exists():
        print(f'channels.txt not found at {CHANNELS_FILE}', file=sys.stderr)
        return []
    out = []
    for raw_line in CHANNELS_FILE.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith(';'):
            continue
        if '#' in line:
            token, _, category = line.partition('#')
            token = token.strip()
            category = category.strip().lower() or 'general'
        else:
            token = line
            category = 'general'
        if token:
            out.append((token, category))
    return out


def main():
    print('=' * 60)
    print(f'Aether catalog update — {datetime.now(timezone.utc).isoformat()}')
    print('=' * 60)
    channels = read_channel_list()
    if not channels:
        print('No channels to fetch.', file=sys.stderr)
        return 1
    print(f'Channels to process: {len(channels)}')
    all_videos = []
    seen_ids = set()
    for token, category in channels:
        print(f'\n-> {token}  [{category}]')
        cid = resolve_channel_id(token)
        if not cid:
            continue
        if cid != token:
            print(f'  resolved to: {cid}')
        videos = fetch_channel_videos(cid)
        added = 0
        for v in videos:
            if v['id'] in seen_ids:
                continue
            seen_ids.add(v['id'])
            v['category'] = category
            all_videos.append(v)
            added += 1
        print(f'  + {added} new videos')
    all_videos.sort(key=lambda v: v.get('published') or '', reverse=True)
    MAX_VIDEOS = 2500
    if len(all_videos) > MAX_VIDEOS:
        all_videos = all_videos[:MAX_VIDEOS]
    output = {
        'updated': datetime.now(timezone.utc).isoformat(),
        'count': len(all_videos),
        'videos': all_videos,
    }
    OUTPUT_FILE.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    print(f'\nWrote {len(all_videos)} videos to {OUTPUT_FILE.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
