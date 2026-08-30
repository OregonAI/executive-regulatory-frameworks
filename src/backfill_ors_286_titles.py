#!/usr/bin/env python3
"""One-off backfill for #286: 18 `_meta/catalog/ors.yml` section titles that diverge from
their own printed catchline, hand-verified against the committed chapter snapshots (NOT a
bulk `parse_toc()` re-run — see below for why).

  python3 src/backfill_ors_286_titles.py            # apply
  python3 src/backfill_ors_286_titles.py --check    # report only, no writes; exit 1 if any diff

SCOPE, exactly: #286 measured 27 catalog titles that fail `ingest_ors.anchor_ok`'s
word-for-word-from-the-front comparison against the section's own printed catchline
(37,534 ingested sections checked). #201's own code review widened `anchor_ok`'s
one-sided-prefix tolerance from the final compared word only to any position, which
independently resolved 6 of the 27 (a plural/inflection at a non-final word now passes);
those 6 (137.593, 197A.302, 249.850, 480.560, 673.370, 708A.475) are intentionally NOT
touched here. Of the 21 that remain (re-measured on this branch, matching #286's own
follow-up review exactly), THREE are intentionally left alone, all for the same reason:
their catalog title is already correct, and what diverges is an artifact of the printed
source, not a defect in the curated title. Writing the source's own artifact into a
curated field, to make a mechanical check pass, is the exact fabrication CONTEXT.md's
Access-failure/Upstream-drift split exists to prevent.

  - 341.305: catalog title reads "tax levy" (correct); the printed chapter-341 snapshot's
    own catchline has the typo "tex levy" -- #286's own follow-up comment names this one
    explicitly.
  - 315.123, 470.540: catalog titles read "recordkeeping requirements" / "timetable for
    certification" (correct, and matching the chapter's own TOC printing); the printed
    BODY catchline instead reads "record- keeping requirements" / "time- table for
    certification" -- a mid-word hyphen from the source's own line-wrapped PDF-to-text
    extraction, not a real spelling. #286's OWN body text names this exact pair as
    hyphenation artifacts and calls "recordkeeping"/"timetable" "the real" forms -- an
    earlier version of this backfill got this backwards for these two specifically,
    writing the artifact form into the catalog and into the ingested statute files
    (title, H1, At-a-glance); caught in code review and reverted before landing, on
    exactly the same reasoning #286's follow-up already applied to 341.305. Left
    diverging here for the identical reason 341.305 is.

That leaves exactly 18 rows, the `FIXES` table below.

WHY HAND-VERIFIED RATHER THAN A `parse_toc()` RE-RUN (the mechanism `backfill_ors_titles.py`
and `backfill_ors_toc_recovery.py` used for their own prior parser-bug backfills): two of
these 18 (735.345, 824.200) print a DIFFERENT catchline in the chapter's TOC than in the
section's own body text -- the TOC prints "...ORS 735.300 to 735.365..." while the section's
own body prints "...735.300 to 735.365..." with no "ORS". `anchor_ok` (and this document's
own `## Full text`) is anchored to the BODY printing, not the TOC, so the TOC-derived text
`catalog_ors.parse_toc()` now produces post-#286's XREF_RE fix is the WRONG source for these
two specifically -- each of the 18 titles below is instead read directly from
`repo_lib.snapshot_slice`'s own catchline extraction (the same text `anchor_ok` itself
checks against), the one ground truth this repository already trusts, rather than re-derived
by a second, TOC-scoped path that happens to agree everywhere else. Because that TOC-derived
path (`backfill_ors_titles.py`) is a live, rerunnable tool and NOT scoped to skip rows this
module has already hand-corrected, `backfill_ors_titles.py` itself now refuses to touch any
section number this module's `FIXES` claims (see its own docstring) -- otherwise a future
unscoped rerun would silently overwrite 735.345 and 824.200 back to the TOC-derived (wrong,
for these two) text, re-diverging them the moment anyone re-ran the older tool.

WHY NOT THE FULL CORPUS: re-running a fixed `catalog_ors.parse_toc()` across every mirrored
chapter (`backfill_ors_titles.py`, unscoped) improves far more than these 18 -- most
catalog titles that truncate at an in-catchline "ORS N.NNN to N.NNN" range (missing the
range's own tail and whatever follows) still PASS `anchor_ok` today, because a true prefix
is not a divergence that check refuses. That is a real, much larger latent improvement
(#346 is a narrower, adjacent parse_toc bug found while measuring it), but it is a
different, far bigger scope than the 27 (now 21) `anchor_ok` FAILURES #286 itself measured
and asked to be corrected -- reported here rather than silently done at 70x this PR's own
stated scope.

For every row below: updates `_meta/catalog/ors.yml`'s `sections[].title`, and if the
section is already ingested (`statutes/ors-*.md` exists), patches that file's `title:`
frontmatter, its `# {title} (ORS {sec})` heading, and its "At a glance" line in place --
reusing `backfill_ors_titles.py`'s own `patch_statute_file`, unmodified. Everything else in
each patched file (full text, citations, dates, verified_by, etc.) is left untouched.
"""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from backfill_ors_titles import patch_statute_file
from repo_lib import REPO_ROOT

CATALOG = REPO_ROOT / "_meta/catalog/ors.yml"

# section -> (chapter, corrected title). Corrected titles are `repo_lib.snapshot_slice`'s
# own catchline extraction for that section against the committed
# `_meta/snapshots/ors-chapter-<ch>.txt` -- the exact text `ingest_ors.anchor_ok` checks
# against -- read and verified by hand against the snapshot, not generated. 341.305,
# 315.123, 470.540, and the 6 the tolerance widening already resolved are deliberately
# absent (see module docstring).
FIXES = {
    "273.522": ("273", "Definition for “forest products”"),
    "274.406": ("274", "Declaration of state’s claim; effect; filing with the county clerk"),
    "316.182": ("316", "Withholding statement of exemption certificate; default withholding "
                        "rate"),
    "415.063": ("415", "Permissible use of compliance self-evaluative audit document by "
                        "Oregon Health Authority; consideration of document in determining "
                        "of civil penalty"),
    "423.105": ("423", "Payment of court-ordered financial obligations; rules"),
    "432.223": ("432", "Reports of adoption; reports of amendments or annulments of "
                        "judgment of adoption; persons required to report; rules"),
    "452.300": ("452", "Oregon Health Authority vector control program"),
    "468A.830": ("468A", "Program for environmental and public health impacts of wildfire "
                          "smoke"),
    "468B.130": ("468B", "Prohibition on sale or distribution of cleaning agents containing "
                          "phosphorus; rules"),
    "475.868": ("475", "Unlawful manufacture of 3,4-methylenedioxymethamphetamine within "
                        "1,000 feet of school"),
    "475.872": ("475", "Unlawful delivery of 3,4-methylenedioxymethamphetamine within "
                        "1,000 feet of school"),
    "624.020": ("624", "License; rules; fee payment; denial, suspension and revocation of "
                        "licenses; posting; nontransferability"),
    "651.190": ("651", "Demographic data collection reporting requirements for hospitals; "
                        "list of hospitals required to report; civil penalty; rules"),
    "657.045": ("657", "Employment; agricultural labor excluded; exceptions"),
    "691.485": ("691", "Board of Licensed Dietitians"),
    "735.345": ("735", "Violation of 735.300 to 735.365; penalties"),
    "824.200": ("824", "Definitions for 824.200 to 824.256"),
    "97.933": ("97", "Certification of provider of prearrangement or preconstruction "
                      "sales; annual reports; rules; audits; fees"),
}


def main():
    check = "--check" in sys.argv
    cat = yaml.safe_load(CATALOG.read_text())
    by_ch = {c["chapter"]: c for c in cat["chapters"]}

    n_diffs = n_files_patched = n_incomplete = n_already_fixed = 0
    for sec, (ch, new_title) in sorted(FIXES.items()):
        c = by_ch.get(ch)
        if c is None:
            print(f"WARN  chapter {ch} not in catalog -- skipped ({sec})")
            continue
        s = next((s for s in c["sections"] if s["number"] == sec), None)
        if s is None:
            print(f"WARN  {sec} not in chapter {ch}'s catalog rows -- skipped")
            continue
        old_title = s["title"]
        if old_title == new_title:
            n_already_fixed += 1
            continue
        n_diffs += 1
        if check:
            print(f"DIFF  ORS {sec}: {old_title!r} -> {new_title!r}")
            continue
        if s.get("status") == "ingested" and s.get("path"):
            fpath = REPO_ROOT / s["path"]
            if fpath.exists():
                n = patch_statute_file(fpath, sec, ch, c["title"], old_title, new_title)
                if n == 3:
                    n_files_patched += 1
                else:
                    n_incomplete += 1
                    print(f"WARN  {s['path']}: only {n}/3 title occurrences matched "
                          f"(section {sec}) -- left partially patched, check by hand")
        s["title"] = new_title

    if check:
        if n_diffs:
            print(f"FAILED: {n_diffs} of {len(FIXES)} section title(s) not yet applied "
                  f"({n_already_fixed} already match) -- run: "
                  "python3 src/backfill_ors_286_titles.py")
            sys.exit(1)
        print(f"OK: all {len(FIXES)} #286 section titles already match.")
        return

    CATALOG.write_text(yaml.safe_dump(cat, sort_keys=False, allow_unicode=True, width=100))
    print(f"backfilled {n_diffs} section title(s) ({n_already_fixed} already matched); "
          f"patched {n_files_patched} already-ingested statute file(s)"
          + (f" ({n_incomplete} incomplete, see WARN lines above)" if n_incomplete else ""))


if __name__ == "__main__":
    main()
