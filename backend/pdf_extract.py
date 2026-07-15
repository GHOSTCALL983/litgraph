"""Extract identifying info (arXiv id / title) from an uploaded paper PDF.

We only need enough to *resolve* the paper on Semantic Scholar, which then gives
us the real reference/author graph. So the strategy is:

  1. Look for an explicit ``arXiv:XXXX.XXXXX`` id anywhere on the first pages
     (most reliable -> exact match).
  2. Fall back to the PDF's embedded /Title metadata.
  3. Fall back to the biggest text on page 1 -- a title is set in the largest
     type on the page, so font size identifies it far more reliably than any
     property of the words themselves.
  4. Fall back to the longest of the first few lines, for PDFs that expose no
     usable font sizes.
"""
import re
import unicodedata

from pypdf import PdfReader

# arXiv ids look like  1706.03762  or  2310.06825v2  (new scheme, 2007-)
ARXIV_RE = re.compile(r'arXiv:\s*(\d{4}\.\d{4,5})(v\d+)?', re.IGNORECASE)

# Lines that are never the title, however big or long they are.
BOILERPLATE = ('arxiv', 'preprint', 'copyright', 'doi:', 'http://', 'https://',
               '@', 'proceedings')

MAX_TITLE = 250


def _clean(text: str | None) -> str | None:
    """Normalise text lifted out of a PDF.

    Typesetting leaves ligatures in the extracted string -- word2vec's title comes
    out as "Ef<fi>cient" with a single U+FB01, not the letters f and i. It *looks*
    right and silently isn't, which matters because titles get sent to Semantic
    Scholar's search. NFKC folds those back to ASCII letters; the rest tidies the
    ragged whitespace PDF extraction leaves behind.
    """
    if not text:
        return None
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_TITLE] or None


def _is_boilerplate(line: str) -> bool:
    low = line.lower()
    return any(w in low for w in BOILERPLATE)


def _plausible(line: str) -> bool:
    """Long enough to be a title, and mostly letters rather than symbols."""
    if len(line) < 8:
        return False
    return sum(c.isalpha() for c in line) >= len(line) * 0.5


def _sized_lines(page) -> list[tuple[float, float, str]]:
    """Page text as (font_size, y, line), via pypdf's text visitor.

    plain extract_text() discards font size, leaving length as the only proxy for
    importance -- and length is actively wrong: a licence banner or a conference
    notice is longer than most titles. The visitor keeps the size, so we can ask
    the question we actually mean.
    """
    runs: dict[tuple[float, float], list[str]] = {}
    order: list[tuple[float, float]] = []

    def visit(text, cm, tm, font_dict, font_size):
        if not text or not text.strip():
            return
        try:
            size = round(float(font_size), 1)
        except (TypeError, ValueError):
            return
        # Same size on the same baseline == the same visual line.
        key = (size, round(tm[5]))
        if key not in runs:
            runs[key] = []
            order.append(key)
        runs[key].append(text)

    try:
        page.extract_text(visitor_text=visit)
    except Exception:  # noqa: BLE001 - any parser hiccup just means "no sizes"
        return []
    out = []
    for key in order:
        line = "".join(runs[key]).strip()
        if line:
            out.append((key[0], key[1], line))
    return out


def _title_by_font(page) -> str | None:
    lines = [(s, y, t) for s, y, t in _sized_lines(page)
             if s > 0 and _plausible(t) and not _is_boilerplate(t)]
    if not lines:
        return None
    biggest = max(s for s, _, _ in lines)
    # A title often wraps onto two lines; both are set in the same size. Take
    # them top-of-page first (PDF y grows upward).
    parts = sorted(((y, t) for s, y, t in lines if s == biggest),
                   key=lambda p: -p[0])
    title = " ".join(t for _, t in parts).strip()
    return title[:MAX_TITLE] or None


def _title_by_length(first_page_text: str) -> str | None:
    """Last resort: the title is usually one of the first few longish lines."""
    lines = [ln.strip() for ln in first_page_text.splitlines()]
    candidates = []
    for ln in lines[:15]:
        if len(ln) < 12 or _is_boilerplate(ln) or not _plausible(ln):
            continue
        candidates.append(ln)
        if len(candidates) >= 5:
            break
    if not candidates:
        return None
    return max(candidates[:4], key=len)[:MAX_TITLE]


def extract(pdf_path: str) -> dict:
    """Return {'arxiv_id', 'title', 'first_page'} — any field may be None."""
    reader = PdfReader(pdf_path)
    if not reader.pages:
        return {"arxiv_id": None, "title": None, "first_page": ""}
    n = min(2, len(reader.pages))
    first_page = reader.pages[0].extract_text() or ""
    head_text = "\n".join((reader.pages[i].extract_text() or "") for i in range(n))

    arxiv_id = None
    m = ARXIV_RE.search(head_text)
    if m:
        arxiv_id = m.group(1)  # without the version suffix

    title = None
    meta = reader.metadata
    if meta and meta.title and len(meta.title.strip()) > 10:
        title = meta.title
    if not title:
        title = _title_by_font(reader.pages[0])
    if not title:
        title = _title_by_length(first_page)

    return {"arxiv_id": arxiv_id, "title": _clean(title),
            "first_page": first_page[:2000]}
