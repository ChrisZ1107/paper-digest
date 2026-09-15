#!/usr/bin/env python3
"""Generate one daily research digest as RSS. Python 3.11+, standard library only."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import fcntl
import html
import json
import logging
import math
from pathlib import Path
import re
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
API = "https://huggingface.co/api/daily_papers"
CONTENT = "http://purl.org/rss/1.0/modules/content/"
ET.register_namespace("content", CONTENT)
ROBOTICS = re.compile(r"\b(robot\w*|humanoid\w*|locomotion|legged|quadruped\w*|embodied|sim[- ]to[- ]real|dexterous|grasping|vision[- ]language[- ]action)\b", re.I)
RL = re.compile(r"\b(reinforcement learning|reinforcement fine[- ]?tuning|rlhf|rlvr|grpo|ppo|policy gradient|actor[- ]critic|reward model\w*|markov decision|offline rl|online rl|q[- ]learning)\b", re.I)


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as f:
        temporary = Path(f.name)
        f.write(text)
    temporary.chmod(0o644)
    temporary.replace(path)


def read_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def iso_date(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def fetch(sort, config):
    proxy = config.get("proxy")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy})) if proxy else urllib.request.build_opener()
    url = API + "?" + urllib.parse.urlencode({"sort": sort, "limit": 100})
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "PersonalPaperDigest/1.0", "Accept": "application/json"})
            with opener.open(request, timeout=45) as response:
                result = json.load(response)
            if not isinstance(result, list) or not result:
                raise ValueError("Empty or invalid paper API response")
            return result
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def normalize(latest, trending, now, config):
    ranks = {entry["paper"]["id"]: rank for rank, entry in enumerate(trending, 1)}
    papers = {}
    for entry in trending + latest:
        paper = entry.get("paper", {})
        identifier = paper.get("id", "")
        if not re.fullmatch(r"\d{4}\.\d{4,5}", identifier):
            continue
        title = paper.get("title") or entry.get("title", "")
        summary = paper.get("summary") or entry.get("summary", "")
        try:
            published = iso_date(paper["publishedAt"])
        except (KeyError, ValueError, TypeError):
            continue
        age = (now - published).total_seconds() / 86400
        if not title or not 0 <= age <= config["max_age_days"]:
            continue
        text = title + " " + summary + " " + " ".join(paper.get("ai_keywords") or [])
        topics = []
        if ROBOTICS.search(text):
            topics.append("机器人")
        if RL.search(text):
            topics.append("强化学习")
        repo = paper.get("githubRepo") or ""
        if urllib.parse.urlsplit(repo).hostname != "github.com":
            repo = ""
        papers[identifier] = {
            "id": identifier, "title": " ".join(title.split()),
            "abstract": " ".join(summary.split()),
            "topics": topics or ["通用 AI"], "published": published.date().isoformat(),
            "age_days": age, "upvotes": max(0, int(paper.get("upvotes") or 0)),
            "comments": max(0, int(entry.get("numComments") or 0)),
            "stars": int(paper["githubStars"]) if paper.get("githubStars") is not None else None,
            "repo": repo, "trending_rank": ranks.get(identifier),
        }
    return list(papers.values())


def rank_and_select(papers, previous, now, config):
    old_papers = previous.get("papers", {})
    elapsed = (now - iso_date(previous["timestamp"])).total_seconds() / 86400 if previous.get("timestamp") else 0
    for paper in papers:
        old = old_papers.get(paper["id"])
        paper["growth"] = None
        growth_score = 0
        if old and 0.25 <= elapsed <= 7:
            growth = {"days": round(elapsed, 2)}
            for key in ("upvotes", "comments", "stars"):
                if paper.get(key) is not None and old.get(key) is not None:
                    growth[key] = paper[key] - old[key]
            paper["growth"] = growth
            growth_score = 2 * math.log1p(max(0, growth.get("upvotes", 0)) / elapsed)
            growth_score += math.log1p(max(0, growth.get("comments", 0)) / elapsed)
            growth_score += 0.5 * math.log1p(max(0, growth.get("stars", 0)) / elapsed)
        trend_score = 4 / math.log2(paper["trending_rank"] + 1) if paper["trending_rank"] else 0
        popularity = math.log1p(paper["upvotes"]) + 0.6 * math.log1p(paper["comments"])
        paper["score"] = round((trend_score + popularity + growth_score) / (1 + paper["age_days"] / 14), 3)
    ordered = sorted(papers, key=lambda p: (-p["score"], p["id"]))
    selected = []
    ids = set()
    for topic, slots in (("机器人", config["robotics_slots"]), ("强化学习", config["reinforcement_learning_slots"])):
        eligible = [p for p in ordered if topic in p["topics"] and p["id"] not in ids]
        for paper in eligible[:slots]:
            selected.append(paper)
            ids.add(paper["id"])
    for paper in ordered:
        if len(selected) >= config["top_n"]:
            break
        if paper["id"] not in ids:
            selected.append(paper)
            ids.add(paper["id"])
    return sorted(selected[:config["top_n"]], key=lambda p: (-p["score"], p["id"]))


def digest_html(selected, now, count):
    e = html.escape
    parts = [f"<h1>{now.date()} 热门论文 Top {len(selected)}</h1>",
             "<p>机器人 · 强化学习 · 通用 AI</p>",
             f"<p>生成时间：{now:%Y-%m-%d %H:%M %Z}。从 {count} 篇近 30 天的候选论文中筛选。优先保留机器人与强化学习各最多 3 篇，再按分数补齐；最终按分数排列。领域由标题、摘要和关键词自动识别，可能有误差。</p>",
             '<p>数据来源：<a href="https://huggingface.co/papers">Hugging Face Papers</a>。分数结合热榜位置、点赞、讨论、发表时间衰减及已观测到的增长；不代表学术质量，也不覆盖全部 arXiv 论文。</p>']
    if len(selected) < 10:
        parts.append(f"<p>本次合格候选不足 10 篇，实际收录 {len(selected)} 篇。</p>")
    for n, paper in enumerate(selected, 1):
        identifier = paper["id"]
        parts.extend([f'<h2>{n}. {e(paper["title"])}</h2>',
                      f'<p><strong>{" / ".join(paper["topics"])}</strong> · 发表 {paper["published"]} · 综合分 {paper["score"]:.2f}</p>'])
        evidence = f'HF 点赞 {paper["upvotes"]} · 讨论 {paper["comments"]}'
        if paper["trending_rank"]:
            evidence += f' · 本次 HF 热榜第 {paper["trending_rank"]} 位'
        if paper["stars"] is not None:
            evidence += f' · 仓库累计 Star {paper["stars"]}（仓库可能包含多篇论文）'
        parts.append(f"<p>{e(evidence)}</p>")
        growth = paper["growth"]
        if growth:
            changes = " · ".join(f'{label} {growth[key]:+d}' for key, label in (("upvotes", "点赞"), ("comments", "讨论"), ("stars", "Star")) if key in growth)
            parts.append(f'<p>较上次观测（{growth["days"]} 天前）：{changes}。</p>')
        else:
            parts.append("<p>暂无可比较的历史快照；本次根据当前热度和新鲜度排序，未使用增长分。</p>")
        excerpt = paper["abstract"][:800]
        if len(paper["abstract"]) > 800:
            excerpt = excerpt.rsplit(" ", 1)[0] + "…"
        parts.append(f'<p><strong>原文摘要节选：</strong>{e(excerpt)}</p>')
        links = [f'<a href="https://arxiv.org/abs/{identifier}">论文原文</a>',
                 f'<a href="https://arxiv.org/pdf/{identifier}">PDF</a>',
                 f'<a href="https://huggingface.co/papers/{identifier}">讨论与热度</a>']
        if paper["repo"]:
            links.append(f'<a href="{e(paper["repo"], quote=True)}">代码</a>')
        parts.append("<p>" + " · ".join(links) + "</p><hr>")
    return "\n".join(parts)


def render_feed(records, config):
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    base = config.get("public_base_url", "").rstrip("/")
    for tag, value in (("title", "每日热门论文 Top 10｜机器人·强化学习·AI"),
                       ("link", base + "/" if base else "https://huggingface.co/papers"),
                       ("description", "每天一篇论文热度榜，优先机器人与强化学习，兼顾通用 AI。"),
                       ("language", "zh-CN"), ("ttl", "60")):
        ET.SubElement(channel, tag).text = value
    for record in records:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = record["title"]
        ET.SubElement(item, "guid", isPermaLink="false").text = "urn:personal-paper-digest:" + record["date"]
        if base:
            ET.SubElement(item, "link").text = base + "/" + record["date"] + ".html"
        ET.SubElement(item, "pubDate").text = format_datetime(iso_date(record["timestamp"]))
        ET.SubElement(item, "description").text = record["html"]
        ET.SubElement(item, f"{{{CONTENT}}}encoded").text = record["html"]
        for category in ("机器人", "强化学习", "通用 AI"):
            ET.SubElement(item, "category").text = category
    return ET.tostring(rss, encoding="unicode", xml_declaration=True)


def run(root, force=False, fixtures=None):
    config = read_json(root / "config.json", {})
    now = datetime.now(ZoneInfo(config["timezone"]))
    state = root / "state"
    state.mkdir(parents=True, exist_ok=True)
    with (state / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        archive = state / "digests" / (str(now.date()) + ".json")
        existing = archive.exists()
        if existing and not force:
            logging.info("Today's digest already exists; rebuilding RSS without creating another item.")
        else:
            if fixtures:
                latest = read_json(fixtures / "latest.json", [])
                trending = read_json(fixtures / "trending.json", [])
            else:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    latest, trending = list(pool.map(lambda order: fetch(order, config), ("publishedAt", "trending")))
            candidates = normalize(latest, trending, now, config)
            if not candidates:
                raise RuntimeError("No recent eligible papers; retaining the previous feed unchanged")
            snapshots = sorted((state / "snapshots").glob("*.json"))
            eligible = [p for p in snapshots if p.stem < str(now.date())]
            previous = read_json(eligible[-1], {}) if eligible else {}
            selected = rank_and_select(candidates, previous, now, config)
            record = {"date": str(now.date()), "timestamp": now.isoformat(),
                      "title": f"{now.date()} 热门论文 Top {len(selected)}｜机器人·强化学习·AI",
                      "papers": selected, "candidate_count": len(candidates),
                      "html": digest_html(selected, now, len(candidates))}
            atomic_write(archive, json.dumps(record, ensure_ascii=False, indent=2))
            snapshot = {"timestamp": now.isoformat(), "papers": {p["id"]: {key: p[key] for key in ("upvotes", "comments", "stars")} for p in candidates}}
            atomic_write(state / "snapshots" / (str(now.date()) + ".json"), json.dumps(snapshot))
            logging.info("Generated %s with %s papers from %s candidates", now.date(), len(selected), len(candidates))
        records = [read_json(p, {}) for p in sorted((state / "digests").glob("*.json"), reverse=True)[:config["keep_days"]]]
        output = root / "public"
        for record in records:
            page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>' + html.escape(record["title"]) + '</title><body>' + record["html"] + '</body></html>'
            atomic_write(output / (record["date"] + ".html"), page)
        atomic_write(output / "feed.xml", render_feed(records, config))
        index = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>每日热门论文</title><body><h1>每日热门论文</h1><p><a href="feed.xml">RSS 订阅</a></p><ul>'
        index += "".join(f'<li><a href="{r["date"]}.html">{html.escape(r["title"])}</a></li>' for r in records)
        atomic_write(output / "index.html", index + '</ul></body></html>')
        logging.info("RSS ready: %s", output / "feed.xml")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--force", action="store_true", help="Regenerate today's entry with the same stable GUID")
    parser.add_argument("--fixtures", type=Path, help="Read latest.json and trending.json instead of using the network")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(args.root, args.force, args.fixtures)
