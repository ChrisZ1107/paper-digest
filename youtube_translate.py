#!/usr/bin/env python3
"""Translate arXiv abstracts referenced by the AIPaperSlop feed with Gemini."""
import json, os, re, urllib.request, urllib.error
from pathlib import Path
import xml.etree.ElementTree as ET
from youtube_monitor import atomic_write, render

MODEL = "gemini-3.1-flash-lite"
PROMPT = """请把下面这篇论文的英文摘要翻译成简体中文。只输出译文，不要加标题、评论或外部信息。保留模型名、方法名、指标和数字。"""

def fetch_abstract(identifier):
    url = "https://export.arxiv.org/api/query?id_list=" + identifier
    req = urllib.request.Request(url, headers={"User-Agent": "PaperDigest/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        root = ET.fromstring(r.read())
    summary = root.find("{http://www.w3.org/2005/Atom}entry/{http://www.w3.org/2005/Atom}summary")
    return " ".join((summary.text or "").split()) if summary is not None else ""

def translate(text, key, model=MODEL):
    payload = {"model": model, "store": False,
               "system_instruction": PROMPT,
               "input": text,
               "response_format": {"type": "text", "mime_type": "application/json",
                                   "schema": {"type": "object", "properties": {"translation": {"type": "string"}}, "required": ["translation"]}},
               "generation_config": {"max_output_tokens": 1800, "thinking_level": "minimal"}}
    req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/interactions",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        result = json.load(r)
    content = "".join(c.get("text", "") for step in result.get("steps", []) if step.get("type") == "model_output" for c in step.get("content", []) if c.get("type") == "text")
    value = json.loads(content).get("translation", "").strip()
    if not value or not re.search(r"[\u4e00-\u9fff]", value):
        raise ValueError("invalid translation")
    return value

def run(root):
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        print("GEMINI_API_KEY unavailable; leaving YouTube feed untranslated")
        return
    state_path = root / "state" / "youtube.json"
    state = json.loads(state_path.read_text())
    changed = 0
    for video in state.get("videos", {}).values():
        for paper in video.get("papers", []):
            if paper.get("abstract_zh"):
                continue
            try:
                abstract = fetch_abstract(paper["id"])
                if not abstract:
                    continue
                paper["abstract"] = abstract
                paper["abstract_zh"] = translate(abstract, key)
                changed += 1
                print(f"translated {paper['id']}")
            except Exception as exc:
                print(f"translation skipped {paper.get('id')}: {type(exc).__name__}")
    if changed:
        atomic_write(state_path, json.dumps(state, ensure_ascii=False, indent=2))
        items = [v for v in state.get("videos", {}).values() if v.get("papers")]
        items.sort(key=lambda x: x.get("published", ""), reverse=True)
        atomic_write(root / "public" / "youtube-feed.xml", render(items[:50]))
    print(f"YouTube abstract translations: {changed}")

if __name__ == "__main__":
    run(Path(__file__).resolve().parent)
