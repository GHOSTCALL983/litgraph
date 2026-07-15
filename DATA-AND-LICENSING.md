# Data Sources, API Access and Licensing

**LitGraph v2.0** · Last reviewed: 2026-07-15

This document records where LitGraph's data comes from, exactly which endpoints it
calls, the rate limits it is engineered against, and the licence terms that govern
that data. It is written for operators, integrators and reviewers.

> **Commercial use — read this first.** The Semantic Scholar API License Agreement
> contains terms that bear directly on selling a product built on it, and the data
> returned may carry a **non-commercial** licence. See
> [§5 Licensing](#5-licensing) and [§6 Commercial use](#6-commercial-use-open-question).
> Nothing in this document is legal advice.

---

## 1. Data source

All bibliographic data in LitGraph is retrieved at runtime from the **Semantic
Scholar Academic Graph API**, operated by the Allen Institute for Artificial
Intelligence (AI2). LitGraph stores no bibliographic corpus of its own; it holds
only a transient response cache (§4).

| Resource | URL |
|---|---|
| API product page | <https://www.semanticscholar.org/product/api> |
| API documentation (index) | <https://api.semanticscholar.org/api-docs/> |
| Academic Graph API reference | <https://api.semanticscholar.org/api-docs/graph> |
| Recommendations API reference | <https://api.semanticscholar.org/api-docs/recommendations> |
| Tutorial | <https://www.semanticscholar.org/product/api/tutorial> |
| Public API FAQ | <https://www.semanticscholar.org/faq/public-api> |
| **API License Agreement** | <https://www.semanticscholar.org/product/api/license> |
| AI2 Terms of Use | <https://allenai.org/terms.html> |

Paper and PDF links resolve to **arXiv** (<https://arxiv.org>). LitGraph links to
arXiv; it does not host, mirror or redistribute arXiv content.

## 2. Endpoints used

LitGraph uses four read-only endpoints. It does not write to the API.

| Purpose | Method · Endpoint | Base |
|---|---|---|
| Resolve a paper by arXiv id | `GET /paper/arXiv:{id}` | `https://api.semanticscholar.org/graph/v1` |
| Resolve a paper by title | `GET /paper/search` | `https://api.semanticscholar.org/graph/v1` |
| References (works a paper cites) | `GET /paper/{id}/references` | `https://api.semanticscholar.org/graph/v1` |
| Similar / recommended papers | `GET /papers/forpaper/{id}` | `https://api.semanticscholar.org/recommendations/v1` |
| An author's own papers (node expansion) | `GET /author/{id}/papers` | `https://api.semanticscholar.org/graph/v1` |

Requested fields (identical for every call, defined once in `sources.PAPER_FIELDS`):
`paperId, externalIds, title, abstract, year, url, citationCount, referenceCount,
authors`.

The recommendations call additionally sends **`from=all-cs`** to draw from the whole
corpus rather than the default recent-papers pool. See `docs.html` → *Where "similar"
comes from* for the measured justification.

Every request carries a `User-Agent` of `LitGraph/{version} (literature survey tool)`.

## 3. Rate limits

Published limits (source: <https://www.semanticscholar.org/product/api>):

| Access | Limit |
|---|---|
| **Unauthenticated** | 1,000 requests/second **shared across all anonymous users**, with additional throttling under load. In practice this is unreliable during busy periods. |
| **With an API key** | **1 request/second** on `/paper/search`, `/paper/batch` and `/recommendations`; **10 requests/second** on all other endpoints. |

LitGraph throttles per endpoint class to stay inside these figures
(`sources._GAP_KEY_SLOW` / `_GAP_KEY_FAST`), using a process-wide lock so concurrent
requests cannot collectively overrun the limit. On `429` it backs off (five attempts,
1.8× from 3s) and then degrades to a partial graph with a warning rather than failing.

> **Note for operators:** limits are enforced **per key**, not per installation. If
> you deploy LitGraph for multiple users behind one key, they share that 1 rps.

## 4. Caching

Every successful response is cached to disk for **30 days** (`cache.py`), because
bibliographic metadata is effectively static. This exists to reduce load on AI2's
infrastructure and to make repeat exploration instant. The cache holds API responses
only; it is not a redistributable dataset and is excluded from version control.

Operators may clear it at any time from the admin panel or by deleting the cache
directory.

## 5. Licensing

### 5.1 The API licence

Use of the API is governed by the **Semantic Scholar API License Agreement**
(<https://www.semanticscholar.org/product/api/license>). Relevant clauses, quoted:

> "AI2 grants to you a limited, non-exclusive, non-transferable, non-sublicensable
> and terminable license to use the API solely in operation with compatible
> third-party platforms and software ("Third-Party Products") to access and display
> the data, datasets, content, and materials that AI2 makes available to S2 users on
> www.semanticscholar.org (collectively, "S2 Data") in accordance with the API
> documentation and this Agreement."

The Agreement prohibits, among other things:

> "repackage, sell, rent, lease, lend, distribute, or sublicense the API;"

### 5.2 Attribution — mandatory

> "Licensee will include an attribution to "Semantic Scholar" on its website or in
> any published materials for contributions from S2 through Licensee's use of the API
> and/or S2 Data."

LitGraph satisfies this by displaying **"Paper data from Semantic Scholar"**, linked
to the API product page, in the graph legend on the main application view, and by
attributing Semantic Scholar in this document, the README and the user documentation.

> **Do not remove that attribution.** It is a licence condition, not decoration. It
> is marked as such in `frontend/index.html`.

### 5.3 The data licence is separate from the API licence

> "Licensee's use of S2 Data accessed via the API are separately governed by the
> licenses that accompany such S2 Data, such as CC BY-NC or ODC-BY ("S2 Data
> Licenses")."

This is the material point for a commercial deployment: **CC BY-NC is a
non-commercial licence.** Records returned by the API — abstracts in particular —
may be covered by it. The applicable licence varies per record and is not something
LitGraph can determine automatically.

### 5.4 Third-party components

| Component | Licence | Notes |
|---|---|---|
| Cytoscape.js + fcose | MIT | Loaded from jsDelivr CDN at runtime |
| `requests` | Apache 2.0 | Runtime dependency |
| `pypdf` | BSD-3-Clause | Runtime dependency |
| Playwright | Apache 2.0 | **Development only** — builds the documentation PDF; not required to run |

## 6. Commercial use — open question

LitGraph's own code is proprietary (see `LICENSE`). The data it displays is not
LitGraph's to license.

Two facts are established and quoted above:

1. The API Agreement's prohibited-conduct list includes the word **"sell"**, in the
   phrase *"repackage, sell, rent, lease, lend, distribute, or sublicense **the
   API**"*.
2. S2 Data may carry **CC BY-NC**, a **non-commercial** licence.

There is a genuine distinction between *reselling API access* (clearly prohibited)
and *selling software that an operator points at their own API key* — the Agreement
does not squarely address the latter. **This document does not resolve that question
and must not be read as doing so.**

**Recommended before any commercial distribution:**

- Read the API License Agreement in full: <https://www.semanticscholar.org/product/api/license>
- Contact AI2 to confirm your intended use and ask about commercial terms.
- Obtain your own legal advice, particularly on the CC BY-NC exposure from displaying
  abstracts.
- Consider the model in which **each operator supplies their own API key** and accepts
  AI2's terms directly — which is how LitGraph is built (§7). This does not by itself
  resolve the data-licence question.

## 7. API credentials

**LitGraph ships with no credentials, and none are stored in version control.**

Each operator supplies their own key:

- **Admin panel** — visit `/admin`, set an admin password on first run, then paste the
  key. It is written to `config.json` in the data directory.
- **Environment variable** — set `S2_API_KEY`. Used automatically when present; the
  value in `config.json` takes precedence.

Request a free key at <https://www.semanticscholar.org/product/api> (the *Request an
API key* form); the key is issued by email.

`config.json` holds the API key and a PBKDF2 hash of the admin password. It is
**excluded from version control** via `.gitignore`, together with the response cache.
Verify with `git check-ignore -v backend/config.json` before committing.

LitGraph runs without a key against the anonymous pool, at materially worse
reliability (§3).

---

*LitGraph is not affiliated with, endorsed by, or sponsored by the Allen Institute
for Artificial Intelligence, Semantic Scholar, or arXiv.*
