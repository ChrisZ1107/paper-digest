#!/usr/bin/env python3
"""Monitor AIPaperSlop videos and publish papers found in public descriptions."""
import argparse
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
import time
import urllib.request
import xml.etree.ElementTree as ET

CHANNEL_URL = "https://www.youtube.com/@AIPaperSlop/videos"
FEED_URL = "https://www.youtube.com/@AIPaperSlop/videos"
VIDEO_RE = re.compile(r'"videoId":"([\w-]{11})"')
ARXIV_RE = re.compile(r'arxiv\.org/(?:abs|pdf)/([0-9]{4}\.\d{4,5})(?:v\d+)?', re.I)
CONTENT = "http://purl.org/rss/1.0/modules/content/"
ET.register_namespace("content", CONTENT)


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 PaperDigest/1.0"})
    with urllib.request.urlopen(req, timeout=45) as response:
        return response.read().decode("utf-8", "replace")


def player(html_text):
    match = re.search(r'var ytInitialPlayerResponse\s*=\s*(\{.*?\});', html_text, re.S)
    if not match:
        raise ValueError("YouTube player data not found")
    return json.loads(match.group(1))


def parse_video(video_id):
    data = player(fetch("https://www.youtube.com/watch?v=" + video_id))
    details = data.get("videoDetails", {})
    description = details.get("shortDescription", "")
    ids = list(dict.fromkeys(ARXIV_RE.findall(description)))
    if not ids:
        return None
    titles = re.findall(r'(?im)^Title:\s*(.+?)\s*$', description)
    papers = []
    for index, identifier in enumerate(ids):
        papers.append({"id": identifier, "title": titles[index] if index < len(titles) else identifier,
                       "url": f"https://arxiv.org/abs/{identifier}"})
    return {"video_id": video_id, "video_title": details.get("title", "AIPaperSlop 新视频"),
            "published": details.get("publishDate", "") or datetime.now(timezone.utc).date().isoformat(),
            "video_url": "https://www.youtube.com/watch?v=" + video_id, "papers": papers}


def render(items):
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    for tag, value in (("title", "AIPaperSlop 视频论文"), ("link", CHANNEL_URL),
                       ("description", "从 AIPaperSlop 新视频描述中提取的 arXiv 论文"),
                       ("language", "zh-CN"), ("ttl", "60")):
        ET.SubElement(channel, tag).text = value
    for item in items:
        entry = ET.SubElement(channel, "item")
        ET.SubElement(entry, "title").text = "AIPaperSlop：" + item["video_title"]
        ET.SubElement(entry, "link").text = item["video_url"]
        ET.SubElement(entry, "guid", isPermaLink="false").text = "urn:aipaperslop:" + item["video_id"]
        try:
            stamp = datetime.fromisoformat(item["published"].replace("Z", "+00:00"))
        except ValueError:
            stamp = datetime.now(timezone.utc)
        ET.SubElement(entry, "pubDate").text = stamp.strftime("%a, %d %b %Y %H:%M:%S +0000")
        parts = [f'<h1>{html.escape(item["video_title"])}</h1>',
                 f'<p>来源：<a href="{html.escape(item["video_url"], quote=True)}">AIPaperSlop YouTube 视频</a></p>',
                 "<p>从视频公开描述中提取的论文：</p><ul>"]
        for paper in item["papers"]:
            parts.append(f'<li><a href="{paper["url"]}">{html.escape(paper["title"])}</a>（arXiv {paper["id"]}）</li>')
        parts.append("</ul><p>论文链接来自视频描述，建议打开原文核对。</p>")
        body = "\n".join(parts)
        ET.SubElement(entry, "description").text = body
        ET.SubElement(entry, f"{{{CONTENT}}}encoded").text = body
        ET.SubElement(entry, "category").text = "AIPaperSlop"
        ET.SubElement(entry, "category").text = "论文视频"
    return ET.tostring(rss, encoding="unicode", xml_declaration=True)


def run(root):
    state_path = root / "state" / "youtube.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"videos": {}}
    seen = state.setdefault("videos", {})
    page = fetch(CHANNEL_URL)
    ids = list(dict.fromkeys(VIDEO_RE.findall(page)))[:30]
    for video_id in ids:
        if video_id in seen:
            continue
        try:
            item = parse_video(video_id)
        except Exception as exc:
            print(f"AIPaperSlop video {video_id} skipped: {type(exc).__name__}")
            continue
        seen[video_id] = item or {"video_id": video_id, "papers": []}
        time.sleep(0.2)
    all_items = [item for item in seen.values() if item.get("papers")]
    all_items.sort(key=lambda item: item.get("published", ""), reverse=True)
    atomic_write(state_path, json.dumps({"videos": seen}, ensure_ascii=False, indent=2))
    atomic_write(root / "public" / "youtube-feed.xml", render(all_items[:50]))
    print(f"AIPaperSlop: {len(ids)} videos checked, {len(all_items)} videos with papers")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    run(parser.parse_args().root)
