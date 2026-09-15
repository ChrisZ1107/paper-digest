import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import digest


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((digest.ROOT / "config.json").read_text())
        self.now = datetime.now(timezone.utc)

    def paper(self, n, topics, score=10):
        return {"id": f"2609.{n:05}", "topics": topics, "upvotes": score,
                "comments": 1, "stars": 5, "age_days": 1, "trending_rank": None}

    def test_topic_reservations_and_unique_papers(self):
        papers = [self.paper(n, ["通用 AI"], 100) for n in range(10)]
        papers += [self.paper(n, ["机器人"]) for n in range(10, 13)]
        papers += [self.paper(n, ["强化学习"]) for n in range(13, 16)]
        result = digest.rank_and_select(papers, {}, self.now, self.config)
        self.assertEqual(len(result), 10)
        self.assertEqual(len({p["id"] for p in result}), 10)
        self.assertEqual(sum("机器人" in p["topics"] for p in result), 3)
        self.assertEqual(sum("强化学习" in p["topics"] for p in result), 3)

    def test_missing_history_is_not_fake_growth(self):
        result = digest.rank_and_select([self.paper(1, ["通用 AI"])], {}, self.now, self.config)
        self.assertIsNone(result[0]["growth"])

    def test_growth_and_stale_baseline(self):
        from datetime import timedelta
        paper = self.paper(1, ["机器人"], 20)
        baseline = {"timestamp": (self.now - timedelta(days=1)).isoformat(),
                    "papers": {paper["id"]: {"upvotes": 10, "comments": 0, "stars": 1}}}
        result = digest.rank_and_select([paper], baseline, self.now, self.config)[0]
        self.assertEqual(result["growth"]["upvotes"], 10)
        baseline["timestamp"] = (self.now - timedelta(days=8)).isoformat()
        self.assertIsNone(digest.rank_and_select([paper], baseline, self.now, self.config)[0]["growth"])

    def test_stale_future_and_duplicate_filter(self):
        from datetime import timedelta
        def entry(identifier, date):
            return {"paper": {"id": identifier, "title": "Robot locomotion", "summary": "Test", "publishedAt": date.isoformat()}}
        good = entry("2609.00001", self.now - timedelta(days=1))
        entries = [good, entry("2609.00002", self.now + timedelta(days=1)), entry("2401.00001", self.now - timedelta(days=100))]
        result = digest.normalize(entries, [good], self.now, self.config)
        self.assertEqual(len(result), 1)
        self.assertIn("机器人", result[0]["topics"])

    def test_idempotent_rss_and_failure_preserves_previous(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.json").write_text(json.dumps(self.config))
            from datetime import timedelta
            entries = [{"paper": {"id": f"2609.{n:05}", "title": "Robot <test> & policy", "summary": "A <script> snippet", "publishedAt": (self.now - timedelta(days=1)).isoformat(), "upvotes": n}} for n in range(10)]
            with patch.object(digest, "fetch", return_value=entries):
                digest.run(root)
            original = (root / "public/feed.xml").read_bytes()
            tree = ET.fromstring(original)
            self.assertEqual(len(tree.findall("channel/item")), 1)
            self.assertIn("&lt;script&gt;", tree.findtext("channel/item/description"))
            with patch.object(digest, "fetch", side_effect=RuntimeError("network down")):
                digest.run(root)
                with self.assertRaises(RuntimeError):
                    digest.run(root, force=True)
            self.assertEqual(original, (root / "public/feed.xml").read_bytes())


if __name__ == "__main__":
    unittest.main()
