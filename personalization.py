"""Zotero/arXiv RSS adapter with Zotero-arXiv-Daily's recency-weighted ranking.

The weighting algorithm is adapted from TideDra/zotero-arxiv-daily,
commit 2879bcdf4ae3f021b77faa84bdfd01185509ebf2, under AGPL-3.0.
Private library records and embeddings stay in memory and are never serialized.
"""
from datetime import datetime, timezone
import html
import json
import logging
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class IntegrationError(RuntimeError):
    """Safe message, with no credentials or private library contents."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request_bytes(url, key=None):
    if key and urllib.parse.urlsplit(url).netloc != "api.zotero.org":
        raise IntegrationError("Credential destination rejected")
    headers = {"User-Agent": "PersonalPaperDigest/2.0"}
    if key:
        headers.update({"Zotero-API-Key": key, "Zotero-API-Version": "3"})
    opener = urllib.request.build_opener(NoRedirect())
    for attempt in range(3):
        try:
            with opener.open(urllib.request.Request(url, headers=headers), timeout=40) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise IntegrationError(f"Upstream HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 2:
                raise IntegrationError("Upstream connection failed") from None
        time.sleep(3 * (attempt + 1))


def zotero_json(path, key, **params):
    url = "https://api.zotero.org" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return json.loads(request_bytes(url, key))


def plain_text(value):
    return " ".join(html.unescape(re.sub(r"<[^>]*>", " ", value or "")).split())


def arxiv_id(value):
    match = re.search(r"(?<!\d)(\d{4}\.\d{4,5})(?:v\d+)?(?!\d)", value or "")
    return match.group(1) if match else None


def fetch_corpus(key, settings):
    identity = zotero_json("/keys/current", key)
    user_id = str(identity.get("userID", ""))
    if not user_id.isdigit() or not identity.get("access", {}).get("user", {}).get("library"):
        raise IntegrationError("Zotero key has no personal-library read access")
    expected = os.environ.get("ZOTERO_ID", "").strip()
    if expected and expected != user_id:
        raise IntegrationError("Zotero user ID does not match the configured key")
    selection = os.environ.get("ZOTERO_COLLECTIONS", "").strip()
    allowed = None
    if selection:
        wanted = {name.strip() for name in selection.split(",") if name.strip()}
        collections = []
        for start in range(0, 10000, 100):
            batch = zotero_json(f"/users/{user_id}/collections", key, limit=100, start=start)
            collections.extend(batch)
            if len(batch) < 100:
                break
        allowed = {c["key"] for c in collections if c["key"] in wanted or c["data"]["name"] in wanted}
        matched = {name for name in wanted if any(c["key"] == name or c["data"]["name"] == name for c in collections)}
        if matched != wanted:
            raise IntegrationError("A requested Zotero collection was not found")
        for _ in range(len(collections)):
            descendants = {c["key"] for c in collections if c["data"].get("parentCollection") in allowed}
            if descendants <= allowed:
                break
            allowed.update(descendants)
    corpus = []
    examined = 0
    max_corpus = settings.get("max_corpus", 500)
    for start in range(0, 50000, 100):
        batch = zotero_json(f"/users/{user_id}/items/top", key, format="json", limit=100,
                            start=start, sort="dateAdded", direction="desc",
                            itemType="conferencePaper || journalArticle || preprint || thesis")
        examined += len(batch)
        for item in batch:
            data = item["data"]
            abstract = plain_text(data.get("abstractNote"))
            if not abstract or (allowed is not None and not allowed.intersection(data.get("collections", []))):
                continue
            corpus.append({"abstract": abstract, "added": data["dateAdded"],
                           "title": plain_text(data.get("title")),
                           "arxiv_id": arxiv_id(data.get("url", "") + " " + data.get("extra", "") + " " + data.get("DOI", ""))})
            if len(corpus) >= max_corpus:
                break
        if len(corpus) >= max_corpus or len(batch) < 100:
            break
    if not corpus:
        total = zotero_json(f"/users/{user_id}/items/top", key, format="json", limit=1)
        if not total:
            raise IntegrationError("Zotero cloud library is empty; sync the desktop library first")
        raise IntegrationError(f"No synced Zotero papers with abstracts in the selected library ({examined} paper records checked)")
    return sorted(corpus, key=lambda item: item["added"], reverse=True)


def parse_arxiv(xml, now, classify, max_age_days=30):
    root = ET.fromstring(xml)
    if "Feed error" in root.findtext(ATOM + "title", ""):
        raise IntegrationError("arXiv rejected the category query")
    results = {}
    for entry in root.findall(ATOM + "entry"):
        if entry.findtext(ARXIV + "announce_type", "new") not in ("new", "cross"):
            continue
        identifier = arxiv_id(entry.findtext(ATOM + "id", ""))
        title = plain_text(entry.findtext(ATOM + "title", ""))
        abstract = entry.findtext(ATOM + "summary", "")
        abstract = plain_text(abstract.split("Abstract:", 1)[-1])
        released = entry.findtext(ATOM + "published") or root.findtext(ATOM + "updated")
        try:
            date = datetime.fromisoformat(released.replace("Z", "+00:00"))
            age = (now - date).total_seconds() / 86400
        except (AttributeError, ValueError, TypeError):
            continue
        if not identifier or not title or not abstract or not 0 <= age <= max_age_days:
            continue
        categories = [c.get("term", "") for c in entry.findall(ATOM + "category")]
        topics = classify(title + " " + abstract, categories)
        results[identifier] = {"id": identifier, "title": title, "abstract": abstract,
                              "topics": topics, "published": date.date().isoformat(), "date_label": "公告",
                              "age_days": age, "upvotes": 0, "comments": 0, "stars": None,
                              "repo": "", "trending_rank": None, "sources": ["arXiv"]}
    return list(results.values())


def recency_weights(count):
    if count < 1:
        raise IntegrationError("Empty reference corpus")
    weights = [1 / (1 + math.log10(i + 1)) for i in range(count)]
    total = sum(weights)
    return [weight / total for weight in weights]


def weighted_similarity(candidate_features, corpus_features):
    """Upstream BaseReranker's weighting, on normalized vectors in newest-first order."""
    weights = recency_weights(len(corpus_features))
    return (candidate_features @ corpus_features.T * weights).sum(axis=1)


def add_relevance(candidates, corpus, model_name=MODEL):
    from sentence_transformers import SentenceTransformer
    # This standard model does not require executing remote Python model code.
    encoder = SentenceTransformer(model_name, device="cpu", trust_remote_code=False)
    corpus_features = encoder.encode([p["abstract"] for p in corpus], normalize_embeddings=True,
                                     batch_size=32, show_progress_bar=False)
    candidates_features = encoder.encode([p["abstract"] for p in candidates], normalize_embeddings=True,
                                         batch_size=32, show_progress_bar=False)
    scores = weighted_similarity(candidates_features, corpus_features)
    for paper, score in zip(candidates, scores):
        paper["relevance"] = round(float(score), 5)


def enrich(candidates, config, now, classify):
    key = os.environ.get("ZOTERO_KEY", "").strip()
    settings = config.get("personalization", {})
    if not settings.get("enabled") or not key:
        return candidates, "未启用 Zotero 个性化，使用现有热度排序。"
    try:
        corpus = fetch_corpus(key, settings)
        query = "+".join(settings.get("arxiv_categories", ["cs.RO", "cs.LG", "cs.AI", "cs.CV"]))
        extra = []
        source_note = ""
        try:
            extra = parse_arxiv(request_bytes("https://rss.arxiv.org/atom/" + query), now, classify, config["max_age_days"])
        except Exception:
            source_note = " 本次 arXiv 源暂不可用，仅对 HF 候选计算相关性。"
        merged = {p["id"]: dict(p) for p in extra}
        for paper in candidates:
            if paper["id"] in merged:
                merged[paper["id"]] = dict(paper, sources=["Hugging Face", "arXiv"])
            else:
                merged[paper["id"]] = dict(paper)
        owned_ids = {p["arxiv_id"] for p in corpus if p["arxiv_id"]}
        owned_titles = {p["title"].casefold() for p in corpus}
        pool = [p for p in merged.values() if p["id"] not in owned_ids and p["title"].casefold() not in owned_titles]
        if not pool:
            raise IntegrationError("No unsaved candidates available")
        add_relevance(pool, corpus, settings.get("model", MODEL))
        logging.info("Zotero personalization succeeded; arXiv candidates: %d", len(extra))
        return pool, "已启用 Zotero-arXiv-Daily 加权摘要相似度：相关性 65%，热度与新鲜度 35%；近期收藏权重更高。" + source_note
    except Exception as exc:
        # Never log exception repr/traceback: third-party errors may contain private text.
        logging.warning("Zotero personalization unavailable (%s); retaining heat-based digest", type(exc).__name__)
        return candidates, "本次 Zotero 个性化暂不可用，已退回热度排序；下一期自动重试。"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        key = os.environ.get("ZOTERO_KEY", "").strip()
        if not key:
            raise SystemExit("ZOTERO_KEY is not configured")
        try:
            corpus = fetch_corpus(key, {"max_corpus": 500})
        except Exception as exc:
            raise SystemExit("Zotero verification failed: " + (str(exc) if isinstance(exc, IntegrationError) else type(exc).__name__)) from None
        print("Zotero library verified; abstract-based recommendation is ready.")
