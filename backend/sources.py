"""Open-data clients for building the literature graph.

Primary source: **Semantic Scholar Graph API** (free, open). It gives us, for any
paper: metadata, its references (papers it cites), recommended/similar papers, and
author lists. arXiv ids are exposed in each paper's ``externalIds`` so we can
filter to arXiv-only and link straight to arxiv.org.

No API key is required, but the anonymous pool is rate-limited. Set the
environment variable ``S2_API_KEY`` to use your own key for higher limits.
"""
import json
import re
import threading
import time

import requests

import cache
import config

GRAPH = "https://api.semanticscholar.org/graph/v1"
REC = "https://api.semanticscholar.org/recommendations/v1"

# Fields we request for every paper. Kept in one place so all calls are consistent.
PAPER_FIELDS = ",".join([
    "paperId", "externalIds", "title", "abstract", "year", "url",
    "citationCount", "referenceCount", "authors",
])

# Hard ceilings, found by probing the live API for the 400 it returns one past the
# edge. Asking for more is rejected outright, so every caller must clamp.
MAX_LIMIT = {
    "references": 1000,     # "'limit' must be <= 1000"
    "similar": 500,         # "Limit must be between 0 and 500"
    "author_papers": 1000,  # "'limit' must be <= 1000"
}

# Ordering has to happen on our side. S2 accepts a `sort` parameter on these
# endpoints and silently ignores it -- sort=bogusfield:desc returns 200 with rows
# identical to no sort at all -- so passing one would be a no-op that merely looks
# like it works. We fetch a pool and rank it here instead.
SORTS = ("citations", "year_desc", "year_asc", "default")


# The shapes people actually paste. All of these mean 1706.03762:
#   1706.03762 · 1706.03762v7 · arXiv:1706.03762 · https://arxiv.org/abs/1706.03762
#   https://arxiv.org/pdf/1706.03762v7 · and any of the above with stray whitespace
# The version suffix matters most: it's what the arXiv *filename* uses and what the
# paper stamps on its own first page, so it's the form a user is most likely to copy.
# Anchored deliberately -- this must only fire on strings that ARE an id, never on a
# title that happens to contain a number.
_ARXIV_INPUT = re.compile(
    r"""^\s*
        (?:(?:https?://)?(?:www\.)?arxiv\.org/(?:abs|pdf)/)?   # optional URL
        (?:arxiv[:\s]\s*)?                                     # optional arXiv: prefix
        (\d{4}\.\d{4,5})                                       # the id itself
        (?:v\d+)?                                              # optional version
        (?:\.pdf)?                                             # optional extension
        \s*/?\s*$""",
    re.IGNORECASE | re.VERBOSE)


def clean_arxiv_id(text: str | None) -> str | None:
    """Fold any of the pasted shapes down to the bare id Semantic Scholar wants.

    Returns None when the text isn't an arXiv id at all -- including old-style ids
    like hep-th/9901001, which callers should pass through untouched rather than
    reject.
    """
    if not text:
        return None
    m = _ARXIV_INPUT.match(str(text))
    return m.group(1) if m else None


def sort_papers(papers: list[dict], how: str) -> list[dict]:
    if how == "citations":
        return sorted(papers, key=lambda p: p.get("citationCount") or 0, reverse=True)
    if how == "year_desc":
        return sorted(papers, key=lambda p: p.get("year") or 0, reverse=True)
    if how == "year_asc":
        return sorted(papers, key=lambda p: p.get("year") or 9999)
    return list(papers)


# Semantic Scholar publishes different per-key rate limits per endpoint: **1 request
# per second** for /paper/search, /paper/batch and the recommendations service, and
# **10 per second** for everything else. A single flat gap can't satisfy both -- the
# old 0.4s (2.5 rps) was simultaneously too fast for search/recommendations, which
# 429'd even with a valid key, and needlessly slow for the rest.
# https://www.semanticscholar.org/product/api
_SLOW_ENDPOINTS = ("/paper/search", "/paper/batch", "/recommendations/")
_GAP_KEY_SLOW = 1.05   # 1 rps + a margin
_GAP_KEY_FAST = 0.11   # 10 rps + a margin
_GAP_ANON = 1.2        # the anonymous pool is shared by everyone; be a good citizen


class SemanticScholar:
    # Throttling is per endpoint class and shared process-wide, so concurrent
    # requests can't collectively overrun the limit.
    _last = {"slow": 0.0, "fast": 0.0}
    _lock = threading.Lock()

    def __init__(self):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = f"LitGraph/{config.VERSION} (literature survey tool)"
        key = config.get_api_key()
        self.has_key = bool(key)
        if key:
            self.s.headers["x-api-key"] = key
        self.warnings: list[str] = []
        self.rate_limited = False

    def _gap(self, url: str) -> tuple[str, float]:
        slow = any(part in url for part in _SLOW_ENDPOINTS)
        if not self.has_key:
            return ("slow" if slow else "fast"), _GAP_ANON
        return ("slow", _GAP_KEY_SLOW) if slow else ("fast", _GAP_KEY_FAST)

    def _throttle(self, url: str):
        bucket, gap = self._gap(url)
        with SemanticScholar._lock:
            wait = gap - (time.time() - SemanticScholar._last[bucket])
            if wait > 0:
                time.sleep(wait)
            SemanticScholar._last[bucket] = time.time()

    def _get(self, url: str, params: dict | None = None, tries: int = 5):
        """GET with disk caching + polite throttling + backoff. On persistent
        rate-limiting we return None and flag it, so the graph degrades
        gracefully instead of crashing."""
        ckey = "s2:" + url + "?" + json.dumps(params or {}, sort_keys=True)
        hit = cache.get(ckey)
        if hit is not None:
            config.STATS["cache_hits"] += 1
            return hit
        delay = 3.0
        for attempt in range(tries):
            self._throttle(url)
            try:
                r = self.s.get(url, params=params, timeout=30)
            except requests.RequestException:
                if attempt == tries - 1:
                    return None
                time.sleep(delay)
                delay *= 1.8
                continue
            config.STATS["api_calls"] += 1
            if r.status_code == 200:
                data = r.json()
                cache.set(ckey, data)
                return data
            if r.status_code == 404:
                return None
            if r.status_code in (429, 502, 503, 504):
                if attempt < tries - 1:
                    time.sleep(delay)
                    delay *= 1.8
                    continue
                if r.status_code == 429 and not self.rate_limited:
                    self.rate_limited = True
                    self.warnings.append(
                        "Semantic Scholar rate-limited us - graph may be partial. "
                        "Wait a minute and retry, or set an S2_API_KEY.")
                return None
            return None

    # ---- resolving the seed paper -------------------------------------------
    def by_arxiv(self, arxiv_id: str) -> dict | None:
        return self._get(f"{GRAPH}/paper/arXiv:{arxiv_id}",
                         {"fields": PAPER_FIELDS})

    def by_title(self, title: str) -> dict | None:
        data = self._get(f"{GRAPH}/paper/search",
                         {"query": title, "limit": 1, "fields": PAPER_FIELDS})
        if data and data.get("data"):
            return data["data"][0]
        return None

    def resolve(self, arxiv_id: str | None = None, title: str | None = None,
                query: str | None = None) -> dict | None:
        # Accept an id in whatever shape it arrived, and notice when a "query" is
        # really an id -- the UI can only guess, and a pasted URL or a versioned id
        # would otherwise go to title search and find nothing.
        aid = (clean_arxiv_id(arxiv_id) or clean_arxiv_id(query)
               or clean_arxiv_id(title))
        if not aid and arxiv_id:
            aid = str(arxiv_id).strip() or None   # e.g. old-style hep-th/9901001
        if aid:
            p = self.by_arxiv(aid)
            if p:
                return p
            self.warnings.append(f"arXiv:{aid} not found on Semantic Scholar; "
                                 "trying title search.")
        for t in (title, query):
            if t:
                p = self.by_title(t)
                if p:
                    return p
        return None

    # ---- neighbourhood ------------------------------------------------------
    def references(self, paper_id: str, limit: int) -> list[dict]:
        limit = min(limit, MAX_LIMIT["references"])
        if limit <= 0:
            return []
        data = self._get(f"{GRAPH}/paper/{paper_id}/references",
                         {"fields": PAPER_FIELDS, "limit": limit})
        out = []
        # `or []`, not .get("data", []): S2 can answer {"data": null}, and a default
        # only applies when the key is missing -- present-but-null sails past it and
        # crashes the loop. This 500'd on real papers.
        for row in ((data or {}).get("data") or []):
            cited = row.get("citedPaper")
            if cited and cited.get("paperId"):
                out.append(cited)
        return out

    def similar(self, paper_id: str, limit: int) -> list[dict]:
        """Recommended papers, drawn from the whole corpus rather than new arrivals.

        The `from` parameter picks the pool, and its default ("recent") is close to
        worthless for a literature survey: for word2vec it returns 2026 preprints
        with 0 citations, and for the Transformer it returns *nothing at all* --
        which is why similar papers used to be empty or junk. "all-cs" searches the
        whole corpus and gives the real neighbours (Universal Transformers for the
        Transformer, fastText for word2vec).

        We still fall back to the default pool, because all-cs is the CS corpus and
        arXiv is not only CS -- a physics or biology paper is better served by the
        default than by nothing.
        """
        limit = min(limit, MAX_LIMIT["similar"])
        if limit <= 0:
            return []
        base = {"fields": PAPER_FIELDS, "limit": limit}
        for params in ({**base, "from": "all-cs"}, base):
            data = self._get(f"{REC}/papers/forpaper/{paper_id}", params)
            out = (data or {}).get("recommendedPapers") or []
            if out:
                return out
        return []

    def author_papers(self, author_id: str, limit: int) -> list[dict]:
        limit = min(limit, MAX_LIMIT["author_papers"])
        if limit <= 0:
            return []
        data = self._get(f"{GRAPH}/author/{author_id}/papers",
                         {"fields": PAPER_FIELDS, "limit": limit})
        return (data or {}).get("data", []) or []


def arxiv_id_of(paper: dict) -> str | None:
    ext = paper.get("externalIds") or {}
    return ext.get("ArXiv")
