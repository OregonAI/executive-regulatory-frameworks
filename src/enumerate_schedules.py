#!/usr/bin/env python3
"""MIGRATED from the retired OregonAI/oregon-records-retention (PLAN.md Phase 9), because it
is the only thing that knows the shape of the Archives Division index page. Without it,
re-enumerating this family means rediscovering that page structure from scratch.

Writes ERF's `_meta/sources/<group>.yml` shape (schema-validated via extra_schema_checks),
not the flat `_meta/source-manifest.yml` the retired corpus used.


Enumerate Oregon Secretary of State agency "special" records-retention schedules.

Source index:
  https://sos.oregon.gov/archives/records-management/Pages/state-admin-schedules.aspx

Stdlib only (urllib, re, html.parser, json, hashlib). No requests/bs4.

Output: inventory.json  -- a stable, sorted list of records:
  {slug, title, url, kind, ...audit fields}

NOTE ON PAGE STRUCTURE (verified 2026-07-25):
The page is NOT a <ul><li><a> list. Each entry is a paragraph shaped like:

    <p> Administrative Services, Dept. of&#58;
        <i class="fas fa-file-pdf"></i>&#160;<a href=".../schedule-das.pdf">Schedule</a><br></p>

so the anchor text is the useless literal "Schedule" for most rows, and the
human-readable agency name is the paragraph text that PRECEDES the anchor.
A single group (ODOT) is nested in a <blockquote> under a <strong> heading; those
rows have no leading label but DO carry a descriptive anchor text
("ODOT - Rail Division Schedule"). The title resolver below handles both shapes.
"""

import argparse
import hashlib
import html as htmllib
import json
import os
import re
import sys
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin

INDEX_URL = (
    "https://sos.oregon.gov/archives/records-management/Pages/"
    "state-admin-schedules.aspx"
)
USER_AGENT = (
    "OregonPolicyCorpus/1.0 (records-retention schedule inventory; "
    "contact: dzinck@gmail.com)"
)

# ---------------------------------------------------------------------------
# Classification rules -- deliberately explicit and auditable.
#
# Each rule is (kind, reason, predicate(url_path, filename)).  Rules are
# evaluated in order; the FIRST match wins.  Nothing is ever silently dropped:
# every PDF link on the page ends up in inventory.json with a `kind` and a
# `classification_reason` naming the rule that fired.
# ---------------------------------------------------------------------------

# Filenames that live in the schedule/ directory but are guidance material
# rather than an agency special schedule (annotated guides, update guides,
# "Retention-Schedule-Basics", forms, FAQs, general/OAR 166 schedules, ...).
#
# IMPORTANT: these match on whole hyphen-delimited words only.  Naive substring
# matching produces false positives against real agency slugs -- e.g. the token
# "training" is a substring of the genuine schedule
# "schedule-human-services-training-investigation-safety.pdf", and "form" is a
# substring of "information".  Single common words that could plausibly appear
# in an agency/division name (training, update, overview, services) are
# deliberately NOT listed; only unambiguous document-genre words are.
GUIDANCE_PATTERNS = (
    r"retention-schedule-basics",
    r"basics",
    r"annotated",
    r"guides?",
    r"guidance",
    r"instructions?",
    r"faqs?",
    r"forms?",
    r"templates?",
    r"checklists?",
    r"how-?to",
    r"general-schedules?",
    r"oar-?166",
    r"webinars?",
    r"tutorials?",
)

# A word matches only at a hyphen/start/end boundary within the filename stem.
GUIDANCE_RE = re.compile(
    r"(?:^|-)(?:%s)(?:-|$)" % "|".join(GUIDANCE_PATTERNS), re.I
)

SPECIAL_SCHEDULE_RE = re.compile(r"^schedule-(?P<slug>[A-Za-z0-9][A-Za-z0-9._-]*)\.pdf$", re.I)


def classify(url_path, filename):
    """Return (kind, reason, slug_or_None).

    kind is 'special_schedule' or 'guidance'.
    """
    stem = re.sub(r"\.pdf$", "", filename, flags=re.I)

    # Rule 1: a guidance genre word appears as a whole word in the filename.
    # Checked BEFORE the schedule- pattern so that e.g.
    # "schedule-Retention-Schedule-Basics.pdf" or "schedule-update-guide.pdf"
    # are not mistaken for an agency schedule.
    m = GUIDANCE_RE.search(stem)
    if m:
        return "guidance", "R1:filename-contains-guidance-word:%s" % m.group(0).strip("-"), None

    # Rule 2: must live under the schedule document directory.
    if "/documents/schedule/" not in url_path.lower():
        return "guidance", "R2:not-under-Documents/schedule/", None

    # Rule 3: must match schedule-<agency>.pdf.
    m = SPECIAL_SCHEDULE_RE.match(filename)
    if not m:
        return "guidance", "R3:filename-does-not-match-schedule-<agency>.pdf", None

    return "special_schedule", "R4:matches-schedule-<agency>.pdf-in-schedule-dir", m.group("slug")


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

BLOCK_TAGS = {"p", "div", "li", "tr", "td", "h1", "h2", "h3", "h4", "blockquote", "br"}


class ScheduleLinkParser(HTMLParser):
    """Collect every *.pdf anchor together with enough context to name it.

    For each PDF anchor we retain:
      * href
      * anchor text
      * `label`  -- text seen since the start of the current block element and
                    before this anchor (this is where the agency name lives)
      * `group`  -- the sub-group heading a link belongs to, e.g.
                    "Transportation Department (ODOT)".  On this page nesting is
                    expressed by <blockquote> indentation: a <strong> heading in
                    a link-less paragraph applies ONLY to the links inside the
                    <blockquote> that follows it.  Scoping the group to the
                    blockquote prevents the heading from leaking onto every
                    later top-level agency (Treasury, Water Resources, ...).
      * `section`-- the enclosing <h2>/<h3> (e.g. "Agencies")
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._block_text = []      # text since last block boundary
        self._in_a = False
        self._a_href = None
        self._a_text = []
        self._heading_stack = []   # capturing <strong>/<h*> text
        self._heading_text = []
        self._pending_heading = None   # heading seen in a link-less block
        self._last_heading = None      # most recent link-less heading
        self.section = None
        self.group = None
        self._quote_depth = 0
        self._block_had_link = False

    # -- block boundaries -------------------------------------------------
    def _flush_block(self):
        # A block that contained a heading but no link becomes a candidate
        # group heading for a following <blockquote>.
        if self._pending_heading and not self._block_had_link:
            self._last_heading = self._pending_heading
        self._pending_heading = None
        self._block_had_link = False
        self._block_text = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in BLOCK_TAGS:
            self._flush_block()
        if tag == "blockquote":
            # Indented sub-list: the last standalone heading scopes it.
            self._quote_depth += 1
            self.group = self._last_heading
        if tag in ("strong", "b", "h1", "h2", "h3", "h4"):
            self._heading_stack.append(tag)
            self._heading_text = []
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if href.lower().split("?")[0].split("#")[0].endswith(".pdf"):
                self._in_a = True
                self._a_href = href
                self._a_text = []
                self._block_had_link = True

    def handle_startendtag(self, tag, attrs):
        if tag.lower() == "br":
            self._flush_block()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "a" and self._in_a:
            self.links.append(
                {
                    "href": self._a_href,
                    "anchor_text": _clean(" ".join(self._a_text)),
                    "label": _clean(" ".join(self._block_text)),
                    "group": self.group if self._quote_depth > 0 else None,
                    "section": self.section,
                }
            )
            self._in_a = False
            self._a_href = None
            self._a_text = []
        if tag in ("strong", "b", "h1", "h2", "h3", "h4") and self._heading_stack:
            self._heading_stack.pop()
            text = _clean(" ".join(self._heading_text))
            if text:
                self._pending_heading = text
                if tag in ("h1", "h2", "h3", "h4"):
                    self.section = text
            self._heading_text = []
        if tag == "blockquote":
            self._quote_depth = max(0, self._quote_depth - 1)
            if self._quote_depth == 0:
                self.group = None
        if tag in BLOCK_TAGS:
            self._flush_block()

    def handle_data(self, data):
        if self._in_a:
            self._a_text.append(data)
        else:
            self._block_text.append(data)
        if self._heading_stack:
            self._heading_text.append(data)


def _clean(text):
    text = htmllib.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" :;-–—")


# ---------------------------------------------------------------------------
# Title resolution
# ---------------------------------------------------------------------------

def resolve_title(link, slug):
    """Pick the best human-readable name for a schedule.

    Priority:
      1. the paragraph label preceding the anchor ("Administrative Services, Dept. of")
      2. a descriptive anchor text ("ODOT - Rail Division Schedule"), with a
         trailing bare "Schedule" trimmed
      3. the group heading + slug
      4. the slug itself, title-cased
    """
    label = link.get("label") or ""
    anchor = link.get("anchor_text") or ""
    group = link.get("group") or ""

    if label and label.lower() not in ("schedule", "pdf"):
        return label, "label"

    if anchor and anchor.lower() != "schedule":
        title = re.sub(r"\s*Schedule\s*$", "", anchor).strip()
        return (title or anchor), "anchor_text"

    if group:
        return "%s - %s" % (group, slug), "group+slug"

    return slug.replace("-", " ").title(), "slug"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def fetch(url, cache_path=None, use_cache=False):
    if use_cache and cache_path and os.path.exists(cache_path):
        with open(cache_path, "rb") as fh:
            return fh.read()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    if cache_path:
        with open(cache_path, "wb") as fh:
            fh.write(raw)
    return raw



MANIFEST_NOTE = """Every upstream source this corpus consumes. Human-approved via PR before ingestion.
Generated by src/enumerate_schedules.py --manifest; do not hand-edit the sources list.

Two traps recorded here so a future re-enumeration does not fall into them:
1. The index page's raw HTML hash is UNSTABLE - it is SharePoint-rendered and carries a
   fresh __VIEWSTATE and correlation id on every request. Change detection must compare
   the extracted LINK SET, never the page bytes.
2. Titles come from the paragraph label PRECEDING each anchor, not the anchor text: 66 of
   the 76 anchors read literally 'Schedule'. Ten ODOT divisions nested in a blockquote are
   the exception and do carry descriptive anchor text.

`id` is the LOWERCASED slug. Four upstream filenames are uppercase (schedule-OWEB.pdf,
OYA, PSRB, TSPC) and a document id must match ^[a-z0-9][a-z0-9-]+$, so id and url differ
in case for those four; the script asserts that lowercasing introduces no collisions.
"""

ID_RE = re.compile(r"[a-z0-9][a-z0-9-]+")


def write_manifest(records, index_url, path):
    """Emit _meta/source-manifest.yml. Kept in this script rather than done by hand so
    that re-enumerating after an upstream change regenerates the manifest the same way
    every time."""
    import yaml

    schedules = [r for r in records if r["kind"] == "special_schedule"]
    ids = [f"schedule-{r['slug'].lower()}" for r in schedules]
    if len(set(ids)) != len(ids):
        raise SystemExit("lowercasing slugs collided - resolve before writing a manifest")

    sources = []
    for r in sorted(schedules, key=lambda x: x["slug"].lower()):
        doc_id = f"schedule-{r['slug'].lower()}"
        if not ID_RE.fullmatch(doc_id):
            raise SystemExit(f"id {doc_id!r} does not match the required id pattern")
        entry = {
            "id": doc_id,
            "citation": f"{r['title']} - Oregon Special Records Retention Schedule",
            "title": r["title"],
            "url": r["url"],
            "doc_type": "schedule",
            "recheck": "quarterly",
            "sha256": "",
            "why_relevant": ("Agency-specific record series and retention periods that the "
                             "OAR chapter 166 general schedules do not cover."),
            "references_out": ["OAR 166 general schedules", "ORS 192"],
        }
        if r["slug"] != r["slug"].lower():
            entry["filename_case_note"] = f"upstream filename is schedule-{r['slug']}.pdf (uppercase)"
        if r.get("group"):
            entry["group"] = r["group"]
        sources.append(entry)

    # ERF's source-group shape (_meta/schema/source-group.schema.json), not the retired
    # corpus's flat manifest. `sha256` is required by that schema and the old enumerator
    # never populated it — it is filled from the committed snapshot by the ingest, so an
    # enumeration alone leaves it empty and drift detection has nothing to compare.
    import datetime
    doc = {"group": "secretary-of-state-retention-schedules",
           "title": "Secretary of State Archives Division special records-retention schedules",
           "kind": "content-hash",
           "recheck": "quarterly",
           "last_checked": str(datetime.date.today()),
           "upstream_signal": MANIFEST_NOTE,
           "sources": [{"id": x["id"], "url": x["url"], "sha256": x.get("sha256", ""),
                        "notes": x.get("why_relevant") or x.get("title", "")}
                       for x in sources]}
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(doc, fh, sort_keys=False, allow_unicode=True, width=100)
    return len(sources)



def check_manifest(records, path):
    """Compare a live enumeration against the committed manifest.

    Compares the LINK SET, never the page bytes. The index page is
    SharePoint-rendered and ships a fresh __VIEWSTATE and correlation id on every
    request, so its raw hash changes constantly while the content does not — hashing
    the page would cry wolf on every run and be ignored within a week.

    Drift here is a real event for a records corpus: a schedule appearing means an
    agency's retention rules are newly published, and one disappearing means the
    authority a document cites has been withdrawn.
    """
    import yaml

    with open(path, encoding="utf-8") as fh:
        committed = yaml.safe_load(fh)
    have = {s["id"]: s["url"] for s in committed.get("sources") or []}
    live = {f"schedule-{r['slug'].lower()}": r["url"]
            for r in records if r["kind"] == "special_schedule"}

    added = sorted(set(live) - set(have))
    removed = sorted(set(have) - set(live))
    moved = sorted(i for i in set(live) & set(have) if live[i] != have[i])

    for label, ids, mapping in (("ADDED upstream", added, live),
                                ("REMOVED upstream", removed, have),
                                ("URL CHANGED", moved, live)):
        for i in ids:
            print(f"  {label}: {i}  {mapping[i]}")
    if added or removed or moved:
        print(f"\nmanifest drift: {len(added)} added, {len(removed)} removed, "
              f"{len(moved)} moved — re-run with --manifest and review the diff")
        return 1
    print(f"manifest is current ({len(live)} schedules, link set unchanged)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=INDEX_URL)
    ap.add_argument("--out", default="inventory.json")
    ap.add_argument("--manifest", metavar="PATH",
                    help="also write _meta/source-manifest.yml from the enumeration")
    ap.add_argument("--check-manifest", metavar="PATH",
                    help="compare a live enumeration against a committed manifest and "
                         "exit 1 on drift (added/removed/moved schedules)")
    ap.add_argument("--cache", default="index.html")
    ap.add_argument("--use-cache", action="store_true",
                    help="reuse a previously downloaded copy of the index page")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    out_path = args.out if os.path.isabs(args.out) else os.path.join(here, args.out)
    cache_path = args.cache if os.path.isabs(args.cache) else os.path.join(here, args.cache)

    raw = fetch(args.url, cache_path, args.use_cache)
    text = raw.decode("utf-8", errors="replace")
    page_sha = hashlib.sha256(raw).hexdigest()

    parser = ScheduleLinkParser()
    parser.feed(text)
    parser.close()

    records = {}
    duplicates = []
    for link in parser.links:
        url = urljoin(args.url, link["href"])
        path = url.split("://", 1)[-1]
        filename = url.rsplit("/", 1)[-1].split("?")[0]
        kind, reason, slug = classify(path, filename)
        if slug is None:
            slug = re.sub(r"\.pdf$", "", filename, flags=re.I).lower()
        title, title_source = resolve_title(link, slug)

        rec = {
            "slug": slug,
            "title": title,
            "url": url,
            "kind": kind,
            "filename": filename,
            "anchor_text": link["anchor_text"],
            "label": link["label"],
            "group": link["group"],
            "section": link.get("section"),
            "title_source": title_source,
            "classification_reason": reason,
        }
        key = url
        if key in records:
            duplicates.append(key)
            continue
        records[key] = rec

    inventory = sorted(records.values(), key=lambda r: (r["kind"], r["slug"].lower()))

    payload = {
        "source_url": args.url,
        "source_sha256": page_sha,
        "source_bytes": len(raw),
        "counts": {
            "anchors_seen": len(parser.links),
            "unique": len(inventory),
            "duplicates_collapsed": len(duplicates),
            "special_schedule": sum(1 for r in inventory if r["kind"] == "special_schedule"),
            "guidance": sum(1 for r in inventory if r["kind"] == "guidance"),
        },
        "classification_rules": {
            "R1": "filename contains a guidance genre word (whole hyphen-delimited word, one of: %s) -> guidance" % ", ".join(GUIDANCE_PATTERNS),
            "R2": "URL not under /Documents/schedule/ -> guidance",
            "R3": "filename does not match schedule-<agency>.pdf -> guidance",
            "R4": "otherwise -> special_schedule; slug = filename minus 'schedule-' prefix and '.pdf'",
        },
        "records": inventory,
    }

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=False)
        fh.write("\n")

    c = payload["counts"]
    print("index page:        %s (%d bytes, sha256 %s)" % (args.url, c and len(raw), page_sha[:16]))
    print("pdf anchors seen:  %d" % c["anchors_seen"])
    print("unique urls:       %d  (duplicates collapsed: %d)" % (c["unique"], c["duplicates_collapsed"]))
    print("  special_schedule: %d" % c["special_schedule"])
    print("  guidance:         %d" % c["guidance"])
    print("wrote %s" % out_path)
    if args.check_manifest:
        sys.exit(check_manifest(sorted(records.values(), key=lambda r: r["slug"].lower()),
                                args.check_manifest))
    if args.manifest:
        n = write_manifest(sorted(records.values(), key=lambda r: r["slug"].lower()),
                           args.url, args.manifest)
        print("wrote %s (%d sources)" % (args.manifest, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
