# Changelog

All notable changes to LitGraph are recorded here.
This project adheres to [Semantic Versioning](https://semver.org/).

---

## [2.0.0] — 2026-07-15

A control and correctness release. Version 1.0 offered three fixed depth presets and
no user control over retrieval; version 2.0 exposes per-source limits and result
ordering, corrects several defects in how results were retrieved and filtered, and
adds formal documentation.

### Added

- **Per-source controls** — independent limits for references, similar papers and
  authors, each capped at the API's verified ceiling, with a configurable second hop.
- **Result priority** — order results by most cited, newest, oldest, or the source's
  own relevance ranking.
- **References visibility toggle**, completing the set alongside similar papers and
  authors.
- **Documentation** — a full documentation page at `/docs` in both plain-English and
  technical registers, distributed as a PDF at `/docs.pdf`.
- **`DATA-AND-LICENSING.md`** — data sources, endpoints, rate limits and licence terms.
- **Version reporting** — a single source of truth surfaced through the API
  `User-Agent`, `/api/config`, the documentation page and the PDF.
- **Semantic Scholar attribution** in the application, as required by the API licence.
- **Configurable retrieval via the HTTP API** — `/api/analyze` and `/api/expand`
  accept an optional `config` object; `/api/config` publishes the caps, sort options
  and presets so clients derive constraints from the server.

### Changed

- **Retrieval pipeline reordered** to pool → filter → rank → trim. Previously the
  limit was applied at the API and the arXiv filter afterwards, so a request for 40
  references could yield as few as 4. Limits now describe results, not requests.
- **Limit changes no longer contact the API.** Pool size is constant, so adjusting a
  limit re-slices cached data.
- **Rate limiting is now per endpoint class**, matching the published per-key limits
  of 1 request/second for search and recommendations and 10 requests/second
  elsewhere. The previous flat 2.5 requests/second exceeded the limit on the former
  and under-used it on the latter.
- **Visibility filtering is edge-driven**, deriving each node's relationships from its
  edges rather than a single overwritten type field.
- Depth presets now populate the controls rather than fixing behaviour.

### Fixed

- **Similar papers returned no or irrelevant results.** The recommendations service
  was left to default to its recent-papers pool, which returned nothing for some
  well-known papers and uncited preprints for others. Recommendations are now drawn
  from the full corpus.
- **arXiv identifiers were rejected in every form but one.** Versioned identifiers
  (`1706.03762v7`), prefixed identifiers (`arXiv:1706.03762`), pasted arXiv URLs and
  identifiers with surrounding whitespace all failed to resolve.
- **Unhandled error when a reference list was returned as null**, caused by relying on
  a dictionary default for a key that was present with a null value.
- **PDF title detection selected the longest line rather than the largest**, so papers
  carrying a licence banner or notice above the title had the banner extracted as the
  title. Detection now uses font size. Ligatures are normalised.
- **Malformed or empty PDF uploads returned a server error** instead of a validation
  response.
- **Visibility toggles left disconnected nodes on screen** and could not hide
  references at all.
- **JSON export contained an internal interface flag** on every node.

### Removed

- **Citation lookup** ("papers citing this one"). The upstream service returns
  citations in a recency-biased order and does not support server-side ordering, so
  for highly cited papers the retrievable sample was not representative and could not
  be made so. A limit and priority control would have implied a fidelity the data did
  not support.
- **Container packaging** (Dockerfile, Compose file). LitGraph has two dependencies
  and no build step; packaging added maintenance without benefit.

---

## [1.0.0]

Initial release.

- Interactive Cytoscape graph of a seed paper's references, citing papers, similar
  papers and authors.
- Three depth presets; PDF upload; multi-paper batching; node expansion.
- Administration panel, 30-day response cache, architecture map, guided tour,
  PNG/JSON export.
