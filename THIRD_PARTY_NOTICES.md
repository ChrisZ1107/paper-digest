# Zotero-arXiv-Daily adaptation

The recency-weighted abstract-similarity algorithm in `personalization.py` is
adapted from [TideDra/zotero-arxiv-daily](https://github.com/TideDra/zotero-arxiv-daily),
commit `2879bcdf4ae3f021b77faa84bdfd01185509ebf2`, specifically
`src/zotero_arxiv_daily/reranker/base.py` and the library-filtering approach in
`src/zotero_arxiv_daily/executor.py`.

Upstream is licensed under the GNU Affero General Public License version 3.
The full license is included in `LICENSE`; this combined project is distributed
under AGPL-3.0. Original upstream attribution is retained here.

Changes: standard-library Zotero/Atom access, lightweight MiniLM embedding model,
combined heat/relevance ranking, RSS output, private corpus kept only in memory,
and no email or LLM text-generation step. The full upstream application is not
executed. The embedding model runs on the GitHub runner without remote inference.
