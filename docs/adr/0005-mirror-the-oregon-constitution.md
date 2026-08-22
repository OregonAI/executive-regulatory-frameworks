# Mirror the Oregon Constitution

**Status: ACCEPTED (2026-08-21), and DONE.** The decision is taken and carried out: this
corpus mirrors the Oregon Constitution as a source group, on the 751 citing documents and the
authority chain they imply. The recheck cadence the section below argues about is an
expressible value (#193); #194 mirrored **Article VI** as the tracer bullet; #195 mirrored the
rest, and the mirror is now WHOLE. **339 sections across every article the page prints**, and
32 sections cataloged and not published because the page prints them as a leadline and a
repeal bracket with nothing between them — a citation to one of those resolves to nothing and
says that, which is a statement about the Constitution and no longer one about coverage.

The "not mirrored yet" answer the partial mirror needed is gone. A constitutional citation now
has exactly one ambiguous case left, and it is the source's own: see the amendment below.

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


## Amendment: what the whole document turned out to be

Written 2026-08-21 with #195, from the 2024 edition rather than from the ADR above. **The
decision that mattered was not whether to mirror the whole document — that is settled above —
but what an ARTICLE is**, and the answer was not the one "18 articles" implies.

**The page prints 40 article headings under 39 distinct designations.** Eighteen roman
numerals, the lettered articles (X-A, and XI-A through XI-Q, which is where the state's
bonding authority lives), and two shapes that break a numeral-keyed identity:

* **ARTICLE VII is printed twice**, as `(Amended)` and `(Original)`. Both are operative and
  both are cited by Oregon courts: the judicial power sits in amended Article VII, and
  original Article VII's provisions on courts and jurisdiction survive with the status of a
  statute by the terms of amended section 2 — the page says so itself, in a note under the
  heading. There is no bare ARTICLE VII on the page at all.
* **ARTICLE XI-A is printed twice under one designation**: the 1916 RURAL CREDITS article,
  repealed in 1942 and kept on the page as its heading and its repeal bracket, and FARM AND
  HOME LOANS TO VETERANS, which is in force.

Those are different problems and the fix is different for each. **Identity carries the
parenthetical** — `vii-amended`, `vii-original`, `xi-f-1`, `xi-i-2` — because that is how
Oregon writes the citation, and a positional or first-wins scheme would have been stable today
and wrong at the next amendment. A designation printed twice is ONE identity and TWO catalog
entries: both are recorded, the repealed one is skipped with its reason (as Article VI section
9a was), and a citation resolves against the print that carries sections.

The fold to a slug is chosen so that an article with no parenthetical keeps the slug it
already had, which is what let #194's ten Article VI documents stay byte-identical. Re-keying
published documents would have broken every citation already resolving against them.

**A second declaration was retired.** What a constitutional citation looks like was written
twice — in the `or-const` scheme and in `AUTHORITY_FORMS` — and the two disagreed in both
directions: the form took `Art. VII (Amended)` and the scheme refused it, the scheme took
`Art. XI-A` and the form refused it, and neither took `Art. XI-F(1)`, which is a real article.
Both now interpolate one token in `repo_lib`, gated by
`citation_schemes.article_form_disagreements()`. The derivation runs from the id shape outward
because the scheme has to PARSE a token into a document id and the form only has to RECOGNIZE
one; a recognizer can be derived from a parser and not the reverse. Same shape as #193's fix
to `CADENCES` versus the `recheck` enum, in the second place this repository stated one fact
twice.

**Five things only the whole document could show**, all of them invisible in Article VI and
all of them measured rather than feared:

1. **Article XI section 11L** is the only section in the document with an uppercase letter
   suffix. Read with `\d+[a-z]?` — as every part of the pipeline did — it was not a section
   that failed a rule and got reported; it was a section nothing could see, sitting between
   11k and 12 in the article's own contents list where no count would look wrong.
2. **A section number is not always one section.** Nine numbers across seven articles are
   printed more than once, 19 prints in all, as the section in force beside a superseded
   print of it. The operative print is FIRST in Article IV and LAST in Articles XI, XIV and
   XV, so neither first-wins nor last-wins is the rule; what distinguishes it is carrying
   text. That rule lives in the SLICER, because `snapshot_slice` is reached from a doc id
   alone and a rule in the ingest would let the text published and the text verified diverge.
3. **#194's 120-character floor was an ORS threshold.** It refused four real one-sentence
   sections — Article II section 1 ("All elections shall be free and equal."), Article I
   sections 17 and 30, Article V section 10 — with a reason saying the slice was too small to
   be the section's text when it was the whole of it. The floor is now measured in the
   section's OWN text: of 381 prints, 40 carry zero letters outside their leadline, brackets
   and notes, every one of the 40 is repealed or superseded, and the next smallest carries 31.
4. **A Legislative Counsel note is not the section's text.** The page prints 57 of them, and a
   slice runs heading to heading, so a note lands in the preceding section's slice. Counted as
   body text it published four repealed sections whose "full text" was a leadline, a repeal
   bracket and an editorial note about the repeal.
5. **Article V section 15 is a heading and a bracket with no leadline**, and four articles
   print a `Note:` between the contents list and the first section. Both were parsing traps
   that put page furniture into a document's title or its body.

**What this does not settle** is unchanged from the ADR above, and one thing was added to it
and has since been settled: resolving a registry row's constitutional enabling authority
against the mirror was #196, and the amendment below is what it decided.

## Amendment: the third form of admitting evidence resolves, and says which nothing it hit

Written 2026-08-21 with #196, which is the payoff this ADR was argued for and the only part of
it the agency registry ever needed. `link_enabling_authority.py --check` now resolves a
constitutional enabling authority against the mirror, exactly as it resolves an ORS citation
against the mirrored statutes and an executive order against the mirrored orders. **All three
of ADR 0003's forms are checked against a document; none is taken on form alone.** The
`form checked, not resolved` line is gone from the report, because the class it counted is
empty rather than small.

`Or. Const. Art. XVII, sec. 99` — this ADR's own example, and the reason the hole was worth
closing — no longer passes. Under ADR 0003 an enabling authority is ADMITTING evidence: it
alone can put a body in the registry, so a class of it that nothing could verify was a hole in
the rule, and Article XVII has two sections.

**THE DECISION THAT TOOK THE WORK IS NOT "DOES IT RESOLVE".** It is that an authority
resolving to nothing must say WHICH nothing, because a registry row citing a section Oregon
repealed and a row citing a section that never existed are different errors and send a
reviewer to re-read different documents. The amendment above established three of those and
found a fourth; the gate reports five, and `--selftest` holds a permanent proof that no two of
them are given the same answer:

* the source page prints no such article — the citation is wrong;
* the article is printed and carries no sections (`no-sections`, the shape of a repealed
  article) — XI-A, XI-B and XI-C;
* the page prints no such section in that article — the citation is wrong, differently;
* the page prints the section and this corpus published no text for it (`history-only`, the 32
  sections printed as a leadline and a repeal bracket);
* and the numeral names TWO operative articles, where the answer is a refusal to guess rather
  than a failure to resolve. A bare `Or. Const. Art. VII, sec. 1` resolves to nothing on
  purpose — the page prints that numeral only as (Amended) and (Original) — and the gate names
  both citations the reviewer must choose between. It may not stand as admitting evidence,
  not because it is wrong but because it does not yet name one article, and evidence has to
  name the thing that admits.

**The catalog says which, not the filesystem.** `_meta/catalog/constitution.yml` records a
status and a reason per article and per section, so none of the five is inferred from a file
being missing — which is also why a SIXTH answer exists: the catalog recording a section as
published while `constitution/` does not carry it is a statement about THIS CORPUS, worded so
a reviewer is not sent back to the Constitution, and it points at `ingest_constitution.py
--check`, whose gate that is. The mirror is read as well as the catalog for one reason: an
empty `constitution/` would otherwise report every constitutional authority as RESOLVED
against documents that are not there, which is the worse half of CONTEXT.md's rule and the
half nothing else here would catch. A SEVENTH answer is not reachable from a registry row at
all — `AUTHORITY_FORMS` classifies the form first — and exists because the resolver is a
public function: answering "it resolves" about a string it never recognised is the one thing
a gate on admitting evidence may never say.

**It resolves through the `or-const` citation scheme**, which is the code path
`resolve_citation` serves to an agent — the gate and the answer an agent gets cannot disagree,
and restating the lookup would have been the third declaration of what a constitutional
citation means after the amendment above retired the second. An empty `constitution/` makes
the gate REFUSE TO ANSWER rather than report every constitutional authority as citing nothing;
that is CONTEXT.md's overriding rule on the population where breaking it is worst, and it is
proved failing rather than asserted.

**This records no authority.** The ~9 bodies whose enabling authority is a constitutional
article are folded into #169's review population, where six of them already sit; `MAPPED` and
`UNMAPPED` are untouched. What changed is that the review's output is now checkable rather
than taken on faith.

## Amendment: the diff the one hash cannot do

Written 2026-08-21 with #197, and it closes a sentence this ADR left open twice: "any
amendment anywhere in the document changes one sha256, so the signal says *something* changed
and never *what*, and the diff has to do the work." The diff is
`ingest_constitution.py --drift PAGE`, and nothing about the update-check cycle changed to
make room for it — `check_updates.py` is generic over source groups, the group is data, and
the constitution participates in `--due` on `even_year_general_election` exactly as it did.

**The value is entirely in the difference.** A report that named every section on any change
would be the same report as one that named none: the operator learns that the hash moved,
which they already knew. So a section whose text is unchanged is not reported, and the gate
that keeps that true is the one run against the COMMITTED snapshot, where the honest answer is
that nothing moved. A drift report that always fires is not a drift report.

**Three answers per section, and the third is the ADR's own rule.** CHANGED, unchanged, and
COULD NOT CHECK — because a section that cannot be sliced out of the candidate page is not a
section Oregon deleted, and from here a heading that stopped parsing and a repeal look
identical. The report says which of the two reasons it has and refuses to choose between
them. It also reports the honest second half, which is easy to miss: a slice runs heading to
heading, so a heading that stops matching drops its text into the PRECEDING section, and that
neighbour really did change. Both are reported, as different things.

**A page that moved with every section intact is a reportable outcome, not an `ok`.** The
change is then outside the text this mirror publishes — a heading, the edition sentence, page
furniture — and the snapshot itself is what needs diffing. The run exits non-zero for it,
because the alternative is a quiet pass on the one signal this group has.

**The committed DOCUMENTS are read as well as the committed snapshot**, for the reason the
amendment above gives: against a `constitution/` that is not there, every section still
compares equal — the two pages are still the two pages — and the report would be a clean bill
of health for documents that do not exist. A mirror missing what the catalog claims makes the
run refuse. The catalog is the allowlist; the filesystem never defines the population. Given
a path, none of this touches the network.
