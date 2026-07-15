# LitGraph

**Graphical literature survey for arXiv.** Turn any arXiv paper into an interactive
map of the work it cites, related research, and the authors connecting them — then
grow the map by expanding any node.

Version 2.0 · Created by **Shreyan Kundu**

---

## Overview

Provide a paper — an arXiv identifier, a title, or a PDF — and LitGraph renders an
interactive graph of:

- The **seed paper** at the centre.
- The **references** it cites, sized by citation count.
- **Similar papers**, drawn from the whole Semantic Scholar corpus.
- **Every author**, linked to each of their papers, so collaborators meet at shared
  work and prolific researchers emerge as hubs.

Every node opens a detail panel with the abstract, citation count and direct
arXiv/PDF links. Any node can be expanded to extend the graph, and multiple papers
can be analysed together into a single merged map.

LitGraph targets **open-access arXiv papers**, so every paper on the map resolves to
a freely available full text.

## Requirements

- **Python 3.10+**
- Two packages: `requests`, `pypdf`
- An internet connection (the graph library loads from a CDN)
- Optional but recommended: a free Semantic Scholar API key — see
  [Configuration](#configuration)

There is no build step, bundler, container or database.

## Installation

```bash
pip install -r requirements.txt
```

## Running

```bash
python backend/server.py
```

Then open <http://localhost:8000>. On Windows, `run.bat` does the same thing.
Stop the server with `Ctrl+C`.

| Route | Purpose |
|---|---|
| `/` | The application |
| `/docs` | Full documentation (also available as a PDF) |
| `/system` | Interactive architecture map |
| `/admin` | Administration: API key, defaults, cache, password |
| `/health` | Health check |

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8000` | Port to serve on |
| `S2_API_KEY` | — | Semantic Scholar API key (the admin panel takes precedence) |
| `LITGRAPH_DATA_DIR` | `backend/` | Where `config.json` and the response cache are written |

## First run

1. Start the server and open <http://localhost:8000/admin>.
2. Set an administrator password. This protects the API key and cache controls.
3. Paste your Semantic Scholar API key (see below). Alternatively set `S2_API_KEY`.
4. Open <http://localhost:8000> and analyse a paper — try `1706.03762`.

### Obtaining an API key

LitGraph ships with **no credentials**. Each operator supplies their own.

Request a free key from the *Request an API key* form at
<https://www.semanticscholar.org/product/api>. It is issued by email.

LitGraph will run without a key against Semantic Scholar's shared anonymous pool,
but that pool is rate-limited across all anonymous users worldwide and is unreliable
under load. A key is strongly recommended for anything beyond casual use.

> **Your key is never committed.** It is stored in `config.json` inside the data
> directory, which is excluded by `.gitignore` along with the response cache.

## Usage

Enter an arXiv identifier in any of these forms:

```
1706.03762            1706.03762v7            arXiv:1706.03762
https://arxiv.org/abs/1706.03762             (or a pasted PDF link)
```

…or a paper title, or upload the PDF. Use **＋ Add** to queue several papers into one
merged graph.

The control bar sets how much of each source to retrieve and how results are
prioritised when there are more matches than your limit:

| Control | Range | Notes |
|---|---|---|
| References — limit | 0–1000 | Papers the seed cites |
| References — priority | Most cited / Newest / Oldest / API order | |
| Similar — limit | 0–500 | Related work |
| Similar — priority | Most relevant / Most cited / Newest / Oldest | |
| Authors — per paper | 0–50 | Authors drawn per paper |
| Authors — from | Every paper / Seed only | |
| 2nd hop | 0–25 | Also pull the references *of* your top references |

**Quick / Deep Research / Complex** are presets that load starting values into these
controls.

## Documentation

Complete documentation is served at **`/docs`** while the application is running, and
is distributed as **`frontend/LitGraph-Documentation.pdf`**. It covers every feature
in both plain-English and technical form, the verified API limits, the data pipeline,
the HTTP API, and a candid account of the system's constraints.

- [`DATA-AND-LICENSING.md`](DATA-AND-LICENSING.md) — data sources, endpoints, rate
  limits, and the licence terms governing the data. **Read this before any commercial
  deployment.**
- [`CHANGELOG.md`](CHANGELOG.md) — release history.
- `/system` — interactive architecture map.

## Architecture

```
 Browser (vanilla JS + Cytoscape.js)
        │  fetch / JSON
        ▼
 server.py ······ pure Python standard library, no framework
        │
        ├── graph_builder.py   normalise config · build · expand
        ├── pdf_extract.py     PDF → arXiv id / title
        └── config.py          settings · PBKDF2 auth · sessions
                │
                ▼
        sources.py ──► cache.py (30-day disk cache)
                   ──► Semantic Scholar API ──► arXiv links
```

Each source is retrieved as a pool, filtered to arXiv, ranked, and then trimmed to
the requested limit — in that order, so a limit means what it says. Because the pool
size is constant, changing a limit re-slices cached data and costs no API call.

## Data and attribution

Bibliographic data is retrieved from the **Semantic Scholar Academic Graph API**,
operated by the Allen Institute for Artificial Intelligence. Use of that API requires
attribution to Semantic Scholar, which LitGraph displays in the application; **this
attribution must not be removed.**

Data returned by the API is governed by its own licences, which may include
non-commercial terms. See [`DATA-AND-LICENSING.md`](DATA-AND-LICENSING.md).

LitGraph is not affiliated with, endorsed by, or sponsored by the Allen Institute for
Artificial Intelligence, Semantic Scholar, or arXiv.

## Licence

Copyright © 2026 Shreyan Kundu. All rights reserved. Proprietary — see
[`LICENSE`](LICENSE).
