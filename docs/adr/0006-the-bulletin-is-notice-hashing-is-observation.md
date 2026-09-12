# The Bulletin is notice; hashing is observation

Oregon publishes the **Oregon Bulletin** on the first business day of each month: the
official digest of rule filings. `src/check_bulletin.py` reads it and writes
`_meta/bulletin-worklist.yml` — every OAR rule number that month's permanent, temporary and
minor-correction filings adopt, amend, repeal, renumber or suspend. August 2026 (bulltnRsn
1761): 549 rule actions from 159 filings, 418 against rules this corpus holds.

Separately, `corpus-detect-changes` hashes the sources in `_meta/sources/oar.yml` and
reports what moved. Those are individual rule pages. The set was **seeded** from this
worklist (#256) — every rule the Bulletin named that this corpus holds, plus a rolling
sample of held rules it did not name — and it **grows with ingestion**: `ingest_oar.py`
registers every rule it mirrors, so a newly-held rule is watched from the day it arrives.

**The policy is: every rule this corpus mirrors is watched, from the day it is ingested.**
Decided on #308, 2026-09-11. The #256 seeding — a Bulletin-named set plus a rolling sample —
was scaffolding for a mirror that was too incomplete to watch wholesale, not a statement that
a subset is the right thing to watch. `ingest_oar.py` registering every rule it mirrors is
therefore the policy working, not a side effect to be undone.

**The binding constraint is a request budget, not a coverage fraction.** #402 priced the
backfill and the arithmetic decides this. `corpus_toolkit.sources.fetch` holds
`MIN_INTERVAL = 2.0` seconds between requests **to the same host**, and every OAR rule page
is on one host, `secure.sos.state.or.us`. The watch therefore costs **1,800 pages per hour,
serially, and cannot be parallelised without abandoning that interval** — which is not on the
table. Today's 6,614 pages is **3.7 hours per run**. Enrolling all 42,561 would be **23.6
hours per run, 42,561 requests a week to a single state server.**

**That is refused, on politeness grounds, and recorded here rather than deferred.** The cost
would not be ours; it would be imposed on the Secretary of State, to detect changes that for
the Bulletin-named half Oregon *already announces*. Hashing is the backstop for change nobody
filed. A backstop does not have to be exhaustive to be honest — it has to be **stated**.

So the watch is defined by four rules, in this order:

1. **Every rule the Bulletin names is watched.** Unconditional, unaffected by any budget —
   477 this month.
2. **Every rule `ingest_oar.py` enrols stays watched.** Accretive, and why coverage rises on
   its own as the mirror is re-ingested.
3. **The rolling sample is sized to fill the remaining request budget**, not to reach a
   coverage percentage.
4. **Full enrolment of the 35,947 is refused**, for the arithmetic above, until either the
   interval or the corpus's relationship with the host changes.

Today that yields **6,614 rule pages across 136 chapters — 15.5% of the 42,561 rule documents
on disk**, across 170 mirrored chapters. Of those 6,614, 1,006 carry the #256 seeding (406
Bulletin-named, 600 sampled) and 5,608 arrived with #238's ingest.

This is **not** "watch a subset because it is cheaper." Rule 1 is unconditional, rule 2 means
the number grows without anyone deciding to grow it, and rule 4 makes the refusal legible.
*Could not check is never reported as is not there* — and a stated budget says exactly what is
and is not being observed, which is the opposite of the paragraph #308 was filed against.

**The rolling sample therefore does not retire.** It is the only mechanism that reaches the
35,947 — it walks the whole mirror, not the watched set, so retiring it would take those rules
from *visited once every ~71 runs* to *never visited*. Under a budget rather than a backfill,
that rotation is permanent infrastructure, not a transitional measure.

We decided the two run **side by side**, and that neither is the arbiter of the other.

## The distinction

The Bulletin is **authority about what was filed**. Hashing is **observation of what is
served**. They answer different questions, so "which is right when they disagree" is the
wrong frame — the disagreement is itself the finding, and there are four cases:

| Bulletin | hash | what it means |
|---|---|---|
| names a rule | unchanged | filed but not yet served, or served identically |
| silent | moved | **a change nobody announced** — the loud one |
| names a rule | moved | agreement |
| silent | unchanged | quiet — indistinguishable from a broken fetcher, which is why Q8's sequence check exists |

This is [ADR 0010](https://github.com/OregonAI/corpus-toolkit/blob/main/docs/adr/0010-a-group-drift-finding-reports-correlation-not-cause.md)'s
distinction one level up. That ADR refused to read a group drift finding as evidence of a
shared *cause*; this one refuses to read either signal as the *truth* about the other.

## Considered and rejected: the Bulletin replaces hashing

corpus-toolkit#78's premise was replacement — "read ONE document a month instead of hashing
36k rules" — and the arithmetic is compelling. We rejected it because a silent upstream
correction files no notice. Under a Bulletin-only design "no filing this month" and "nothing
changed" become the same observation, which is the substitution this repository refuses
everywhere else: **could not check is never reported as is not there.** (This ADR applies
that rule; it is not where it lives. It is stated in AGENTS.md and defined in `CONTEXT.md`
under **Could not check** — which is where two docstrings in `src/` citing "ADR 0006" for it
should have been pointing.)

Hashing is kept for exactly one job it alone can do: detecting change nobody announced. It is
no longer the primary signal — but the reason first given here was wrong, and the correction
is what made the table work.

The manifest holds individual rule pages, so a moved hash **does** name a rule exactly. What
it could not do was name a rule the Bulletin also named. The 484 rules watched before #256
sat in chapters 105, 122, 125 and 128; the worklist names rules across 35 chapters, none of
them those four. **The intersection was zero and the disjointness was structural**, so two of
the four cases below — *filed but not yet served* and *agreement* — could never occur (#247).

The watched set is now **derived from the notice it is compared against**, so all four cases
are reachable by construction: 406 rules are in both signals this month. The rolling sample
carries the other half of the job, because a rule nobody filed against is exactly the rule a
silent correction would touch; the cursor advances and wraps, so at 600 a run the whole
mirror is visited once every **71** runs — stated rather than implied, and a far weaker
guarantee than the named half.

Under the policy stated above the sample is **permanent**, and its weakness is now its whole
justification: it is the only coverage the 35,947 un-enrolled rules have, and #402 decided
they stay un-enrolled because the alternative is 23.6 hours of requests a week to one state
server. The sample shrinks only as `ingest_oar.py` enrols rules by re-ingesting them. It does
not retire — under a request budget there is no point at which nothing remains for it to
reach.

`src/seed_oar_watch.py --check` fails if a rule this bulletin named and this corpus holds is
not watched, and `src/oar_watch_coverage.py --check` fails if this paragraph and the manifest
stop agreeing.

## Consequences

**Legal status gets one writer, and it is the Bulletin.** A rule document's `status` —
corpus-toolkit's schema enum `current | superseded | repealed | proposed | draft` — is a claim
about force. `ingest_oar.py` currently writes `status: current` as a hardcoded literal on
every rule it creates, so an auto-re-ingest of an amended rule would silently resurrect one
the Bulletin had marked repealed. A fresh ingest may assert `current` only where it has no
better information, and must never overwrite a status the Bulletin set. One writer, gated —
the arrangement `name_basis` and `issuing_body_registry_fault` already use.

**A repealed rule is marked, never deleted.** 66 repeals and 34 suspensions this month land
on rules we hold. Deleting them breaks the citations that point at them; leaving them
untouched publishes a repealed rule as current under provenance. The status is derived in
`_meta/catalog/oar.yml` and stamped onto the document from there, so the catalog is the
writer and the document is a reader.

**Actions split on whether they change text or force.** An amendment is a text refresh the
provenance chain already verifies, so it re-ingests automatically. A repeal or suspension is a
claim about force and goes to a human. 418 rules this month would have been 418 tickets
against a 25-issue cap; splitting on action puts review where judgement is needed.

**`in_corpus` is three states, not two.** *Held*, *chapter not mirrored*, and *missing from
a mirrored chapter* are different facts, and the third is a genuine coverage gap rather than a
boundary. Measured on the August bulletin against the 170 mirrored chapters: of 131
not-in-corpus rules, **121 are in chapters this corpus mirrors and are absent from disk** — 74
adoptions, 43 amendments, 1 repeal, 3 suspensions — and only 10 are genuinely out of scope. The
43 amendments are rules that existed and changed in chapters we claim to mirror.

An earlier draft of this ADR said the opposite — that no not-in-corpus rule was missing from a
mirrored chapter, and that the third state was therefore being built before it could occur. That
came from a query whose chapter set was built by a regex expecting `oar-*.md` filenames in a
directory that holds chapter *directories*; the set was empty, so every rule fell outside it. A
query matching nothing returns the same clean answer as one matching everything. **The two
meanings have already collided, 121 times in one month, and the collision is currently
invisible** — which is a stronger reason for the split, not a weaker one.

The worklist records them as `corpus_state: held | missing_from_mirrored_chapter |
chapter_not_mirrored`, a RENAMED field rather than a widened `in_corpus`: every value of a
two-state field is truthy, so a consumer reading the new spelling off the old name would find
every row held. And the mirrored-chapter set that decides between the last two is itself
checked against the corpus's own held rules — a chapter listing that cannot account for the
documents on disk makes the gate refuse, which is the measurement error above, caught.

**A renumber records its destination or says it could not.** `_meta/catalog/oar.yml` already
stores `served_as`; the worklist today records `action: renumber` with no target. July filed
64 renumbers, 32 against rules we hold. *Renumbered*, *renumbered with unknown target*, and
*repealed* are three states and only one of them means the text is gone.

**A gap in the bulletin sequence is an error.** `bulltnRsn` is monotonic and the bulletins are
monthly, so a missed month is detectable and must fail rather than pass quietly. A filing that
cannot be fetched or parsed leaves its rules in an explicit unknown state — otherwise a parse
failure and a quiet month produce the identical empty worklist.

**The monthly report files an issue.** corpus-toolkit#67 exists because both observed capped
drift runs put their notice on stderr and nobody read it. One issue per run, not per rule.

## What this does not settle

Whether the 49 rules the catalog marks `not_served` with the note *"OARD page contains no rule
number (rule likely repealed)"* are in fact repealed. That is inference from absence, hedged,
and predates this decision; the Bulletin can retire it as a backlog. Their documents currently
say `current`.
