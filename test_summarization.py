import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import summarization as s

PAPER = {"id": "2301.10602", "title": "Quadruped locomotion with PPO",
         "abstract": "We train quadruped robots using reinforcement learning and transfer from simulation to real hardware."}
VALUE = {"overview": "作者介绍了一种利用强化学习训练四足机器人的方法，并将策略迁移到真实硬件。",
         "highlights": [{"text": "作者使用强化学习训练四足机器人。", "evidence": PAPER["abstract"]}],
         "tags": ["四足机器人", "强化学习"]}

class SummarizationTests(unittest.TestCase):
    def test_rules_and_word_boundaries(self):
        self.assertIn("PPO", s.rule_tags(PAPER))
        self.assertNotIn("PPO", s.rule_tags({"title": "Support", "abstract": "opportunities"}))

    def test_evidence_must_exist(self):
        value = copy.deepcopy(VALUE)
        value["highlights"][0]["evidence"] = "We outperform all baselines by 90 percent."
        with self.assertRaises(ValueError):
            s.validate(value, PAPER)

    def test_bad_schema_and_tags(self):
        for change in ({"tags": ["made-up"]}, {"overview": "English only overview"}, {"highlights": []}):
            with self.assertRaises(ValueError):
                s.validate(dict(VALUE, **change), PAPER)

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"})
    @patch.object(s, "request_summary", return_value=VALUE)
    def test_cache_and_content_change(self, request):
        with tempfile.TemporaryDirectory() as folder:
            papers = [copy.deepcopy(PAPER)]
            s.enrich(papers, {}, Path(folder))
            s.enrich(papers, {}, Path(folder))
            self.assertEqual(request.call_count, 1)
            papers[0]["title"] += " revised"
            s.enrich(papers, {}, Path(folder))
            self.assertEqual(request.call_count, 2)
            self.assertNotIn("test-secret", "".join(p.read_text() for p in Path(folder).rglob("*.json")))

    @patch.dict(os.environ, {"GEMINI_API_KEY": ""})
    @patch.object(s, "request_summary")
    def test_offline_fallback(self, request):
        with tempfile.TemporaryDirectory() as folder:
            papers = [copy.deepcopy(PAPER)]
            s.enrich(papers, {}, Path(folder))
            request.assert_not_called()
            self.assertNotIn("ai_summary", papers[0])
            self.assertIn("四足机器人", papers[0]["rule_tags"])

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-secret"})
    @patch.object(s, "request_summary", side_effect=s.GeminiError("HTTP 429"))
    def test_api_error_stops_calls(self, request):
        with tempfile.TemporaryDirectory() as folder:
            papers = [copy.deepcopy(PAPER) for _ in range(10)]
            s.enrich(papers, {}, Path(folder))
            self.assertEqual(request.call_count, 1)
            self.assertTrue(all("ai_summary" not in p for p in papers))

    def test_html_escape(self):
        paper = dict(PAPER, ai_summary=dict(VALUE, overview="<script>alert(1)</script>"), summary_status="AI")
        output = s.render(paper)
        self.assertNotIn("<script>", output)
        self.assertIn("&lt;script&gt;", output)

    @patch("urllib.request.build_opener")
    def test_api_contract_public_input_only(self, opener):
        response = Mock()
        response.read.return_value = json.dumps({"status": "completed", "steps": [
            {"type": "model_output", "content": [{"type": "text", "text": json.dumps(VALUE)}]}]}).encode()
        opener.return_value.open.return_value.__enter__ = Mock(return_value=response)
        opener.return_value.open.return_value.__exit__ = Mock(return_value=False)
        self.assertEqual(s.request_summary(dict(PAPER, private_notes="PRIVATE"), s.MODEL, "KEY"), VALUE)
        req = opener.return_value.open.call_args.args[0]
        self.assertNotIn(b"PRIVATE", req.data)
        self.assertNotIn("KEY", req.full_url)
        self.assertFalse(json.loads(req.data)["store"])

if __name__ == "__main__":
    unittest.main()
