from datetime import datetime, timezone
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import digest
import personalization as p


class PersonalizationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 15, 8, tzinfo=timezone.utc)
        self.config = json.loads((Path(__file__).parent / "config.json").read_text())

    def candidate(self, identifier="2609.10001"):
        return {"id": identifier, "title": "Robot policy", "abstract": "Robot reinforcement learning",
                "topics": ["机器人", "强化学习"], "age_days": 1, "upvotes": 0, "comments": 0,
                "stars": None, "trending_rank": None, "sources": ["Hugging Face"]}

    def test_weights_prioritize_recent_and_sum_to_one(self):
        weights = p.recency_weights(12)
        self.assertAlmostEqual(sum(weights), 1)
        self.assertGreater(weights[0], weights[-1])
        self.assertEqual(p.recency_weights(1), [1])

    def test_arxiv_new_cross_duplicate_and_replacement(self):
        def entry(identifier, kind):
            return f'<entry><id>oai:arXiv.org:{identifier}</id><title>Robot policy</title><summary>Abstract: reinforcement learning</summary><published>2026-09-15T04:00:00Z</published><arxiv:announce_type>{kind}</arxiv:announce_type><category term="cs.RO"/></entry>'
        xml = '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">'
        xml += entry('2609.10001v1', 'new') + entry('2609.10001v1', 'cross') + entry('2609.10002v2', 'replace') + '</feed>'
        papers = p.parse_arxiv(xml, self.now, digest.classify)
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]['id'], '2609.10001')
        self.assertEqual(papers[0]['topics'], ['机器人', '强化学习'])
        self.assertEqual(papers[0]['date_label'], '公告')

    def test_unconfigured_and_failed_personalization_keep_feed(self):
        candidates = [self.candidate()]
        with patch.dict(os.environ, {}, clear=True):
            result, note = p.enrich(candidates, self.config, self.now, digest.classify)
        self.assertEqual(result, candidates)
        self.assertIn('未启用', note)
        with patch.dict(os.environ, {'ZOTERO_KEY': 'secret-sentinel'}, clear=True), patch.object(p, 'fetch_corpus', side_effect=RuntimeError('secret-sentinel')):
            with self.assertLogs(level='WARNING') as logs:
                result, note = p.enrich(candidates, self.config, self.now, digest.classify)
        self.assertEqual(result, candidates)
        self.assertNotIn('secret-sentinel', str(logs.output) + note)

    def test_merged_candidates_exclude_saved_and_do_not_leak_corpus(self):
        corpus = [{'arxiv_id': '2609.10001', 'title': 'Private saved title', 'abstract': 'PRIVATE', 'added': '2026-09-14'}]
        candidates = [self.candidate(), self.candidate('2609.10002')]
        def scorer(pool, corpus, model):
            for paper in pool:
                paper['relevance'] = 0.7
        with patch.dict(os.environ, {'ZOTERO_KEY': 'dummy'}, clear=True), patch.object(p, 'fetch_corpus', return_value=corpus), patch.object(p, 'request_bytes', return_value=b''), patch.object(p, 'parse_arxiv', return_value=[self.candidate('2609.10002')]), patch.object(p, 'add_relevance', side_effect=scorer):
            result, note = p.enrich(candidates, self.config, self.now, digest.classify)
        self.assertEqual([paper['id'] for paper in result], ['2609.10002'])
        self.assertEqual(result[0]['relevance'], 0.7)
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('Private saved title', json.dumps(result))

    def test_relevance_changes_ranking(self):
        low, high = self.candidate(), self.candidate('2609.10002')
        low['relevance'], high['relevance'] = 0.1, 0.8
        result = digest.rank_and_select([low, high], {}, self.now, self.config)
        self.assertEqual(result[0]['id'], high['id'])

    def test_credentials_cannot_follow_another_host(self):
        with self.assertRaises(p.IntegrationError):
            p.request_bytes('https://example.com/private', key='secret')

    def test_zotero_empty_library_and_id_mismatch(self):
        def api(path, key, **params):
            if path == '/keys/current':
                return {'userID': 123, 'access': {'user': {'library': True}}}
            return []
        with patch.dict(os.environ, {}, clear=True), patch.object(p, 'zotero_json', side_effect=api):
            with self.assertRaisesRegex(p.IntegrationError, 'cloud library is empty'):
                p.fetch_corpus('dummy', {})
        with patch.dict(os.environ, {'ZOTERO_ID': '456'}, clear=True), patch.object(p, 'zotero_json', side_effect=api):
            with self.assertRaisesRegex(p.IntegrationError, 'does not match'):
                p.fetch_corpus('dummy', {})


if __name__ == '__main__':
    unittest.main()
