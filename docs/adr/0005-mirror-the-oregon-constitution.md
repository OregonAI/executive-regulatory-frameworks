# Mirror the Oregon Constitution

**Status: ACCEPTED (2026-08-21).** The decision is taken: this corpus will mirror the Oregon
Constitution as a source group, on the 751 citing documents and the authority chain they
imply. What has landed is the recheck cadence the section
below argues about, now an expressible value (#193), and the first article: #194 created
`constitution.yml` and mirrored **Article VI**, 10 of the 11 sections the page prints (section
9a is repealed and printed as its leadline and history alone, so there is no text to mirror —
the catalog records that, and a citation to it says so). One article of eighteen is mirrored
today; the other seventeen are #195, and until they land a constitutional citation into one of
them resolves to nothing AND SAYS IT IS NOT MIRRORED, which is not the ambiguity this ADR
rejects below — that ambiguity is a partial mirror that cannot tell you which it is.

This corpus mirrors the Oregon Revised Statutes and the Oregon Administrative Rules, and it
maintains a catalog of the federal instruments its documents cite — 1,271 targets and 916
authority claims. It does not carry the Oregon Constitution, and 751 of its own documents
cite it: 567 statutes, 162 rules, 14 agency documents and 7 executive orders. Article XI
alone is referred to 846 times.

We propose mirroring it as a source group, on the grounds of those 751 documents and the
authority chain they imply — not on the grounds of the agency registry, which is where the
question arose and which is the weakest reason to do it.

## Considered options

**Doing nothing** is defensible and nearly free, and it is what the corpus does today. It
fails on an asymmetry that is hard to justify once stated: this repository built machinery
to track citations out to *another sovereign's* law, and cannot resolve a citation to the
instrument at the top of its own. `authority_chain` answers "what requires this" by walking
from rule to statute and stops there, at precisely the point where the interesting answer
for 751 documents is one step further up.

**Recording constitutional authorities in the registry as unverified strings** is the cheap
version of the same idea, and for the registry alone it would be enough. About nine bodies
would take a constitutional enabling authority — the Office of the Governor, the Secretary
of State, the Oregon State Treasury, the Judicial Department, District Attorneys and
Deputies, the Legislative Assembly, and probably the Oregon State Lottery under Article XV
section 4a. Nine rows carrying an unverified constitutional citation cost nothing — when
this was written the registry had no field to put one in, so they would have been nine
`UNMAPPED` rows with a stated reason; #170 landed the field, and a body whose authority is a
constitutional article now records that article rather than a reason it has none.

We reject it as *sufficient* but not as a stopgap, because of what it does to verification.
`link_enabling_authority.py --check` resolves an ORS citation against the mirrored statutes
and an executive order against the mirrored orders (#170 — it no longer skips everything
that does not begin with `ORS `), and it can do neither for a constitutional article: there
is nothing to resolve it against, so it checks the FORM and reports how many rows it could
not resolve.
`Or. Const. Art. XVII, sec. 99` is well-formed, and it passes.
Under ADR 0003 an enabling authority is *admitting* evidence — it alone can put a body in
the registry — so an unverifiable class of admitting evidence is a hole in the rule, not a
formatting inconvenience. Mirroring closes it without a special case: constitutional rows
get checked the same way ORS rows do.

**Mirroring only the cited sections** was tempting because the cited set is small. In the
precise `Article X, section Y` form there are 43 distinct targets across 294 occurrences.
We reject it because a partial mirror makes "not found" ambiguous in exactly the way this
repository refuses elsewhere: a citation that resolves to nothing would mean either that
the citation is wrong or that we never mirrored that section, and those must not be the
same state. The whole document is small enough that the distinction costs nothing to keep.

**The cost is lower than the ORS precedent suggests.** The Oregon Constitution is published
at `oregonlegislature.gov/bills_laws/Pages/OrConst.aspx` as a **single HTML page** carrying
all 18 articles, so it is one source entry with one URL, one sha256 and one snapshot —
against `ors.yml`'s 545 chapter sources. Slicing one snapshot into per-section documents is
what the ORS ingest already does; those documents carry
`conversion_notes: sliced the section's text out of the shared chapter snapshot`.

## Consequences

A new source group, `constitution.yml`, and a new `doc_type`. Sections become documents with
the same frontmatter contract, provenance and change history as every other mirrored
document, so nothing downstream needs a special case for them.

`--check` stops skipping non-ORS authorities and verifies constitutional citations against
the mirror. That is the change that makes this worth doing for the registry, rather than
the nine rows themselves.

The recheck cadence differs from every existing group and should not be copied from ORS.
The constitution is amended by ballot measure at general elections, not by the biennial
session that drives `ors.yml`'s `recheck: biennial`. Getting this wrong is quiet: a
constitution that is never rechecked drifts without any signal, because unlike a repealed
ORS section there is no chapter re-issue to notice. The amendment below records what that
cadence became.

The `check-updates` skill gains an update group, and `detect-upstream-changes` gains one
source to watch. A single-page source is also a single point of failure for drift detection:
any amendment anywhere in the document changes one sha256, so the signal says *something*
changed and never *what*, and the diff has to do the work.

**This widens what the corpus claims to be, and that is the part to decide.** The repository
is named for executive regulatory frameworks and currently holds rules, the statutes that
authorize them, and executive orders. The constitution is the layer above all three. That is
either the natural completion of the authority chain or the first step of a scope that ends
at "Oregon law", and this ADR asserts the former without having earned it. The 751 citing
documents are the argument; whoever decides this should be satisfied by that argument
specifically, because it is the only one offered.

What this does not settle is whether the same reasoning admits the Oregon Constitution's
*history* — superseded sections and repealed articles are cited in older documents — or
Oregon appellate decisions construing it, which are cited in some rules and which would be a
far larger undertaking with a genuinely different reproduction basis.

## Amendment: the cadence is its own value, because `biennial` is two years out of phase

Written 2026-08-21 with the decision above (#193), before anything is ingested, because the
cadence is the part of this ADR that had nowhere true to live. `_meta/sources/*.yml` admitted
five values, and the obvious move — reuse `biennial`, since the ballot cycle is also two years
— is the ambiguity this ADR calls quiet, in the one field a reader would trust to be
unambiguous. Two groups would both declare `biennial` while meaning opposite halves of the
same cycle: `ors.yml` means the edition published after the ODD-year legislative session, and
the constitution means the amendments decided at the general election in November of
EVEN-numbered years.

That is not a naming preference, and it was measured rather than asserted. A cadence in this
repo is a number of days since the last check, so the question is where a group lands when it
comes due. Measured over every anchor in the month after an election — the month is the point;
a single flattering anchor proves nothing — and every consecutive pair of general elections
from 2026 to 2100, a group carrying `biennial`'s 730 days comes due between **5 days BEFORE
the next election and 32 days after it**. The failure is not that 730 never lands well: from a
late anchor it does. It is that from the NATURAL anchor, a check made promptly after an
election, it lands on the wrong side of the next one — and one value cannot mean both, because
nothing distinguishes a group that means the session from one that means the ballot.

The value is **`even_year_general_election`**, and its interval is **765 days = 735 + 30**.
735 is the LONGEST span between two consecutive general elections — the Tuesday after the
first Monday in November slides election day between the 2nd and the 8th, so consecutive
even-year elections stand 728 or 735 days apart through 2100 — and taking the longest is what
keeps a due date from landing before the election. The 30 is the margin in which the vote is
canvassed and an approved amendment takes effect; a check on election night finds nothing to
read. Measured the same way as `biennial` above, it comes due between **30 and 67 days after**
the election it must follow, from every anchor in that window, and `src/check_updates.py
--selftest` holds both measurements: the one that must be in that window, and the one that
must not.

WHAT THE INTERVAL CANNOT DO is hold its phase, and the honest statement of that is sharper
than "start it in the right place". `check_updates.py` re-anchors `last_checked` on the day
the check RAN, so the window above is a ONE-HOP property: 765 days against a cycle that is
actually 728 or 735 means each recheck lands **30 to 37 days later than the last**, and after
enough cycles a group anchored perfectly still walks out of the window — far enough, and it
skips an election entirely.

That walk is the reason the interval is longer than the cycle rather than shorter, and it is a
choice between two failures rather than an oversight. A cadence SHORTER than the cycle walks
backward into a state it cannot leave: it comes due before the election, finds nothing
changed, re-anchors earlier still, and never sees an amendment again while reporting `ok` the
whole time. A cadence longer walks late — the amendments are still caught, just later — and an
out-of-phase group drifts toward the window rather than away from it. We took the recoverable
failure.

Neither is a cadence that knows when the election is. Putting the group on phase when it is
created is #194's and #197's job — the `last_checked` a new group starts with is a decision,
not a formality — re-setting it when the walk has gone far enough is a human's, and a cadence
that could state the phase itself, "due after the next even-year general election", is #198.
This records the limit rather than leaving it to be discovered from a due-state that looks
fine.

Two other things follow, and neither is about the constitution. The cadence was declared
TWICE — `CADENCE_DAYS` in `src/check_updates.py` and the `recheck` enum in
`_meta/schema/source-group.schema.json` — with nothing gating their agreement: the same shape
as `CURATED_KEYS` in #165, two hand-maintained lists of one fact that agreed only because
nobody had touched them. The schema's node is now DERIVED from the table
(`--sync-schema` writes it, `--check` fails when the committed one has drifted), and the
derivation runs that way round because the interval is the half a JSON Schema has no keyword
for. And a group declaring a cadence nobody declared is now REPORTED against the group,
where it used to be a `KeyError` raised from a dict lookup inside `report_due()` — which named
the dict instead of the file, and took every other group's due-state down with it.
