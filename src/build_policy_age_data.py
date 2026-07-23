#!/usr/bin/env python3
"""Cache the 'policy age' dataset — how long since each agency policy/procedure/standard/
manual was last touched, against a 2-year review cadence (not statute-relative like
build_freshness_data.py; this is an absolute clock, matching a stated internal-policy norm
that these documents should be revisited every 2 years regardless of whether the law they
implement has changed).

Light step (only scans frontmatter of ~880 policy/procedure/standard/manual docs, not full
statute bodies), but still separated into its own cache so the HTML generator's --check runs
cheaply in CI without re-scanning the corpus.

  python3 src/build_policy_age_data.py          # scan + write cache
  python3 src/build_policy_age_data.py --check   # exit 1 if stale (CI)

Method + honesty:
- last_touched = the LATER of effective_date and last_reviewed, when both are present (a doc
  reviewed without a full re-filing still counts as touched); effective_date alone otherwise.
  last_reviewed is populated for only ~2% of these docs — this mostly reduces to
  effective_date, which is each doc's last recorded filing.
- age_years = (today - last_touched) in years. Docs with neither date are left with
  age_years: null — an honest "unknown", never defaulted to 0 or excluded silently.
- doc_type in {policy, procedure, standard, manual} — the internal-facing bodies a 2-year
  review cadence is meaningfully asked of, as distinct from the statute/rule side already
  covered by build_freshness_data.py.
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from repo_lib import REPO_ROOT, content_files, parse_frontmatter

OUT = REPO_ROOT / "_meta/policy_age.json"
DOC_TYPES = ("policy", "procedure", "standard", "manual")
TODAY = date.today()


def _iso(s):
    try:
        y, m, d = (int(x) for x in s.split("-"))
        return date(y, m, d)
    except Exception:
        return None


def compute() -> dict:
    docs = []
    for p in content_files():
        fm, _ = parse_frontmatter(p)
        if fm["doc_type"] not in DOC_TYPES:
            continue
        eff = _iso(fm.get("effective_date") or "")
        rev = _iso(fm.get("last_reviewed") or "")
        last_touched = max((d for d in (eff, rev) if d), default=None)
        age = round((TODAY - last_touched).days / 365.25, 2) if last_touched else None
        docs.append({
            "id": fm["id"], "title": fm.get("title", ""), "doc_type": fm["doc_type"],
            "agency": fm.get("agency", ""), "citation": fm.get("citation", ""),
            "source_url": fm.get("source_url", ""),
            "effective_date": fm.get("effective_date"), "last_reviewed": fm.get("last_reviewed"),
            "last_touched": last_touched.isoformat() if last_touched else None,
            "age_years": age,
        })
    return {"generated": TODAY.isoformat(), "cadence_years": 2, "docs": docs,
            "note": ("Age = time since effective_date (or last_reviewed if later) — an "
                    "absolute clock against a 2-year internal review cadence, not "
                    "statute-relative. Docs with neither date: age unknown, not assumed "
                    "fresh or stale. Non-authoritative; verify against source_url.")}


def build_html_data(data: dict) -> dict:
    return data


def outputs():
    return {OUT: json.dumps(compute(), ensure_ascii=False, separators=(",", ":"))}


def _stable(text: str) -> dict:
    """Parsed JSON with the clock-derived fields dropped, so --check compares actual data,
    not the day it happened to run on. 'generated' and every doc's 'age_years' are a
    function of date.today() (age_years literally ticks up by 1/365.25 every day even with
    zero real change), so an exact-text --check flakes daily on nothing but the clock --
    worse than the governor-priorities version of this same bug, since that only flaked
    across a UTC/local day-boundary crossing, not on every single run."""
    d = json.loads(text)
    d.pop("generated", None)
    for doc in d.get("docs", []):
        doc.pop("age_years", None)
    return d


def main():
    outs = outputs()
    if "--check" in sys.argv:
        stale = [p for p, t in outs.items() if not p.exists() or _stable(p.read_text()) != _stable(t)]
        if stale:
            print(f"{OUT.relative_to(REPO_ROOT)} is stale — run: python3 src/build_policy_age_data.py")
            sys.exit(1)
        print("policy_age.json is current.")
        return
    for p, t in outs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(t, encoding="utf-8")
    d = json.loads(outs[OUT])
    dated = [x for x in d["docs"] if x["age_years"] is not None]
    overdue = sum(1 for x in dated if x["age_years"] >= 4)
    due = sum(1 for x in dated if 2 <= x["age_years"] < 4)
    print(f"wrote {OUT.relative_to(REPO_ROOT)}: {len(d['docs'])} docs, {len(dated)} dated "
          f"({len(d['docs']) - len(dated)} unknown), {due} due (2-4y), {overdue} overdue (4y+)")


if __name__ == "__main__":
    main()
