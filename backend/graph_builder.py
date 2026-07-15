"""Turn a seed paper into an interactive literature graph.

Nodes are **papers** and **authors**; edges encode how they relate:
  - cites      : main paper  -> a paper it references
  - similar    : main paper <-> a recommended/similar paper
  - authored   : an author -> a paper they wrote  (this is what visually
                 "connects the authors": two authors sharing a paper meet at it,
                 and authors who appear on several papers become hubs)

Per the project goal we keep only papers that exist on **arXiv** (open access),
so every paper node links straight to arxiv.org. The uploaded/seed paper is
always kept even if it lacks an arXiv id.

Every source (references / similar / an author's papers) is fetched as a POOL and
then filtered, ranked and trimmed here -- see `_fetch`.
"""
import copy

from sources import MAX_LIMIT, SORTS, SemanticScholar, arxiv_id_of, sort_papers

# How many rows to pull before filtering. Always the API ceiling, because:
#   1. a big fetch costs the same ONE call as a small one (only bytes differ), and
#   2. it keeps the cache key constant, so changing a limit in the UI re-slices a
#      cached pool instead of hitting the network at all.
POOL = {
    "refs": MAX_LIMIT["references"],
    "similar": MAX_LIMIT["similar"],
    "author_papers": MAX_LIMIT["author_papers"],
}

# Ceilings the UI is allowed to ask for. Anything higher is clamped, never sent.
MAX_KEEP = {
    "refs": MAX_LIMIT["references"],
    "similar": MAX_LIMIT["similar"],
    "author_papers": MAX_LIMIT["author_papers"],
    "authors_per_paper": 50,
    "second_hop": 25,
}

# The sources a config can carry a limit + sort for.
SOURCES = ("refs", "similar")

MAX_AUTHORS_PER_PAPER = 8

# Depth presets exposed in the UI, expressed in the same shape as a custom config.
MODES = {
    "quick": {
        "refs":    {"limit": 25, "sort": "citations"},
        "similar": {"limit": 8,  "sort": "default"},
        "authors": {"enabled": True, "scope": "main", "per_paper": MAX_AUTHORS_PER_PAPER},
        "second_hop": 0,
    },
    "deep": {
        "refs":    {"limit": 40, "sort": "citations"},
        "similar": {"limit": 15, "sort": "default"},
        "authors": {"enabled": True, "scope": "all", "per_paper": MAX_AUTHORS_PER_PAPER},
        "second_hop": 0,
    },
    "complex": {
        "refs":    {"limit": 50, "sort": "citations"},
        "similar": {"limit": 20, "sort": "default"},
        "authors": {"enabled": True, "scope": "all", "per_paper": MAX_AUTHORS_PER_PAPER},
        "second_hop": 6,
    },
}

# Used when the user clicks a node and expands from it.
EXPAND = {
    "refs":    {"limit": 25, "sort": "citations"},
    "similar": {"limit": 8,  "sort": "default"},
    "authors": {"enabled": True, "scope": "all", "per_paper": MAX_AUTHORS_PER_PAPER},
    "author_papers": {"limit": 30, "sort": "citations"},
    "second_hop": 0,
}

# References pulled per parent when a preset walks a second hop.
SECOND_HOP_REFS = {"limit": 15, "sort": "citations"}


def _clamp(value, hi, fallback):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(0, min(value, hi))


def normalize(cfg: dict | None = None, mode: str | None = None,
              base: dict | None = None) -> dict:
    """Validate a UI config into something safe to run.

    Starts from a preset and overlays whatever the caller supplied. Every limit is
    clamped to the API's real ceiling, so a hand-written request can't provoke a
    400 or a runaway fetch.
    """
    out = copy.deepcopy(base or MODES.get((mode or "deep").lower(), MODES["deep"]))
    cfg = cfg or {}

    for src in SOURCES:
        given = cfg.get(src) or {}
        if "limit" in given:
            out[src]["limit"] = _clamp(given["limit"], MAX_KEEP[src], out[src]["limit"])
        if given.get("sort") in SORTS:
            out[src]["sort"] = given["sort"]

    au = cfg.get("authors") or {}
    if "enabled" in au:
        out["authors"]["enabled"] = bool(au["enabled"])
    if au.get("scope") in ("main", "all"):
        out["authors"]["scope"] = au["scope"]
    if "per_paper" in au:
        out["authors"]["per_paper"] = _clamp(
            au["per_paper"], MAX_KEEP["authors_per_paper"], out["authors"]["per_paper"])

    # Only `expand` carries an author-papers step (following an author out to their
    # own work); a normal build has no use for one.
    ap = cfg.get("author_papers") or {}
    if "author_papers" in out:
        if "limit" in ap:
            out["author_papers"]["limit"] = _clamp(
                ap["limit"], MAX_KEEP["author_papers"], out["author_papers"]["limit"])
        if ap.get("sort") in SORTS:
            out["author_papers"]["sort"] = ap["sort"]

    if "second_hop" in cfg:
        out["second_hop"] = _clamp(cfg["second_hop"], MAX_KEEP["second_hop"],
                                   out["second_hop"])
    return out


class GraphBuilder:
    def __init__(self):
        self.s2 = SemanticScholar()
        self.nodes: dict[str, dict] = {}
        self.edges: dict[str, dict] = {}

    # ---- node / edge helpers ------------------------------------------------
    def _paper_node(self, p: dict, kind: str = "paper") -> str:
        pid = p["paperId"]
        ax = arxiv_id_of(p)
        if pid not in self.nodes:
            self.nodes[pid] = {"data": {
                "id": pid,
                "type": kind,
                "label": (p.get("title") or "Untitled")[:80],
                "title": p.get("title") or "Untitled",
                "year": p.get("year"),
                "citationCount": p.get("citationCount") or 0,
                "abstract": (p.get("abstract") or "")[:600],
                "authors": [a.get("name") for a in (p.get("authors") or [])],
                "arxiv": ax,
                "url": (f"https://arxiv.org/abs/{ax}" if ax
                        else p.get("url")),
                "pdf": (f"https://arxiv.org/pdf/{ax}" if ax else None),
            }}
        elif kind == "main":
            self.nodes[pid]["data"]["type"] = "main"
        return pid

    def _author_node(self, a: dict) -> str | None:
        aid = a.get("authorId")
        name = a.get("name")
        if not aid or not name:
            return None
        nid = f"author:{aid}"
        if nid not in self.nodes:
            self.nodes[nid] = {"data": {
                "id": nid, "type": "author", "label": name, "title": name,
                "url": f"https://www.semanticscholar.org/author/{aid}",
            }}
        return nid

    def _edge(self, src: str, tgt: str, rel: str):
        eid = f"{src}__{rel}__{tgt}"
        if eid not in self.edges:
            self.edges[eid] = {"data": {"id": eid, "source": src,
                                        "target": tgt, "rel": rel}}

    def _add_authors(self, paper: dict, paper_node_id: str, per_paper: int) -> list[str]:
        out = []
        for a in (paper.get("authors") or [])[:per_paper]:
            aid = self._author_node(a)
            if aid:
                self._edge(aid, paper_node_id, "authored")
                out.append(aid)
        return out

    # ---- fetch one source ---------------------------------------------------
    def _fetch(self, kind: str, paper_id: str, src_cfg: dict) -> list[dict]:
        """Pool -> arXiv filter -> sort -> trim.

        The order matters. Trimming last is what makes a limit mean what it says:
        the old code asked the API for `limit` rows and *then* dropped the
        non-arXiv ones, so a request for 40 references could land 4 on screen.
        """
        limit = src_cfg["limit"]
        if limit <= 0:
            return []
        if kind == "refs":
            pool = self.s2.references(paper_id, POOL["refs"])
        else:
            pool = self.s2.similar(paper_id, POOL["similar"])
        pool = [p for p in pool if p.get("paperId") and arxiv_id_of(p)]
        return sort_papers(pool, src_cfg["sort"])[:limit]

    def _add_author_papers(self, author_node_id: str, cfg: dict):
        aid = author_node_id.split("author:")[-1]
        pool = self.s2.author_papers(aid, POOL["author_papers"])
        pool = [p for p in pool if p.get("paperId") and arxiv_id_of(p)]
        for p in sort_papers(pool, cfg["sort"])[:cfg["limit"]]:
            pid = self._paper_node(p)
            self._edge(author_node_id, pid, "authored")

    # ---- one seed's neighbourhood -------------------------------------------
    def _add_seed(self, cfg, arxiv_id=None, title=None, query=None):
        """Resolve one seed paper and add its neighbourhood into the shared
        node/edge maps. Returns (main_node_id, resolved_paper) or None."""
        main = self.s2.resolve(arxiv_id=arxiv_id, title=title, query=query)
        if not main:
            return None
        main_id = self._paper_node(main, kind="main")
        au = cfg["authors"]
        if au["enabled"]:
            self._add_authors(main, main_id, au["per_paper"])
        wide = au["enabled"] and au["scope"] == "all"

        # References (papers this seed cites) — arXiv-only.
        refs = self._fetch("refs", main_id, cfg["refs"])
        for p in refs:
            pid = self._paper_node(p)
            self._edge(main_id, pid, "cites")
            if wide:
                self._add_authors(p, pid, au["per_paper"])

        # Similar / recommended papers — arXiv-only.
        for p in self._fetch("similar", main_id, cfg["similar"]):
            pid = self._paper_node(p, kind="similar")
            self._edge(main_id, pid, "similar")
            if wide:
                self._add_authors(p, pid, au["per_paper"])

        # Second hop: expand the most-cited references one level deeper.
        if cfg["second_hop"]:
            top = sorted(refs, key=lambda p: p.get("citationCount") or 0,
                         reverse=True)[:cfg["second_hop"]]
            for parent in top:
                for p in self._fetch("refs", parent["paperId"], SECOND_HOP_REFS):
                    pid = self._paper_node(p)
                    self._edge(parent["paperId"], pid, "cites")

        return main_id, main

    # ---- build (one or many seeds merged into one graph) --------------------
    def build(self, seeds, mode="deep", cfg=None) -> dict:
        cfg = normalize(cfg, mode=mode)
        mains, seed_titles = [], []
        for s in seeds:
            res = self._add_seed(cfg, arxiv_id=s.get("arxiv_id"),
                                 title=s.get("title"), query=s.get("query"))
            if res:
                mid, mp = res
                if mid not in mains:
                    mains.append(mid)
                seed_titles.append(mp.get("title"))
        if not mains:
            if self.s2.rate_limited:
                raise ValueError(
                    "Semantic Scholar is rate-limiting requests right now. Wait "
                    "a minute and retry, or set an S2_API_KEY for higher limits.")
            raise ValueError(
                "Could not identify any of these papers on Semantic Scholar. Try "
                "pasting arXiv ids (e.g. 1706.03762) directly.")

        papers = [n for n in self.nodes.values() if n["data"]["type"] != "author"]
        authors = [n for n in self.nodes.values() if n["data"]["type"] == "author"]
        return {
            "nodes": list(self.nodes.values()),
            "edges": list(self.edges.values()),
            "main": mains[0],
            "mains": mains,
            "meta": {
                "mode": mode,
                "config": cfg,
                "paper_count": len(papers),
                "author_count": len(authors),
                "seed_count": len(mains),
                "title": seed_titles[0] if len(seed_titles) == 1 else None,
                "seeds": seed_titles,
                "warnings": self.s2.warnings,
            },
        }

    # ---- expand from an existing node ---------------------------------------
    def expand(self, node_id: str, kind: str = "paper", cfg=None) -> dict:
        """Grow the graph outward from one already-shown node. Returns only the
        NEW nodes/edges (the client merges them, skipping ids it already has).
        The center node already exists client-side, so we only reference its id.
        """
        cfg = normalize(cfg, base=EXPAND)
        if kind == "author":
            self._add_author_papers(node_id, cfg["author_papers"])
        else:
            center = node_id
            au = cfg["authors"]
            for p in self._fetch("refs", center, cfg["refs"]):
                pid = self._paper_node(p)
                self._edge(center, pid, "cites")
                self._add_authors(p, pid, au["per_paper"])
            for p in self._fetch("similar", center, cfg["similar"]):
                pid = self._paper_node(p, kind="similar")
                self._edge(center, pid, "similar")
                self._add_authors(p, pid, au["per_paper"])

        if not self.nodes and not self.edges and self.s2.rate_limited:
            raise ValueError(
                "Semantic Scholar is rate-limiting requests right now. Wait a "
                "minute and retry, or set an S2_API_KEY.")
        return {
            "nodes": list(self.nodes.values()),
            "edges": list(self.edges.values()),
            "warnings": self.s2.warnings,
        }


def build_graph(arxiv_id=None, title=None, query=None, mode="deep", cfg=None) -> dict:
    return GraphBuilder().build(
        [{"arxiv_id": arxiv_id, "title": title, "query": query}], mode=mode, cfg=cfg)


def build_graph_multi(seeds, mode="deep", cfg=None) -> dict:
    return GraphBuilder().build(seeds, mode=mode, cfg=cfg)


def expand_node(node_id, kind="paper", cfg=None) -> dict:
    return GraphBuilder().expand(node_id, kind=kind, cfg=cfg)
