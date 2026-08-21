# Mirror the Oregon Constitution

**Status: PROPOSED.** Nothing has been ingested and no source group exists. This records a
recommendation and the measurements behind it so the decision can be made against something
concrete, or declined for a stated reason.

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
section 4a. Nine `UNMAPPED` rows with a stated reason cost nothing.

We reject it as *sufficient* but not as a stopgap, because of what it does to verification.
`link_enabling_authority.py --check` resolves an ORS citation against the mirrored statutes
and an executive order against the mirrored orders (#170 — it no longer skips everything
that does not begin with `ORS `), and it can do neither for a constitutional article: there
is nothing to resolve it against, so it checks the FORM and reports the row as unresolved.
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
ORS section there is no chapter re-issue to notice.

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
