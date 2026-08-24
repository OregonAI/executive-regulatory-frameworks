# The Bulletin is notice; hashing is observation

Oregon publishes the **Oregon Bulletin** on the first business day of each month: the
official digest of rule filings. `src/check_bulletin.py` reads it and writes
`_meta/bulletin-worklist.yml` — every OAR rule number that month's permanent, temporary and
minor-correction filings adopt, amend, repeal, renumber or suspend. August 2026 (bulltnRsn
1761): 549 rule actions from 159 filings, 418 against rules this corpus holds.

Separately, `corpus-detect-changes` hashes the 484 sources in `_meta/sources/oar.yml` and
reports what moved. Those are **484 individual rule pages in four chapters** — 125 (420),
122 (33), 128 (22), 105 (9) — not chapter sources, and they cover **1.3% of the 36,953
rule documents on disk, in 4 of the 170 mirrored chapters** (#247).

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
everywhere else: **could not check is never reported as is not there.**

Hashing is kept for exactly one job it alone can do: detecting change nobody announced. It is
no longer the primary signal — but the reason first given here was wrong, and the correction
matters more than the claim did.

The manifest holds individual rule pages, so a moved hash **does** name a rule exactly. What
it cannot do is name a rule the Bulletin also named: the 484 watched rules sit in chapters
105, 122, 125 and 128, and the August 2026 worklist names 534 rules across 35 chapters, none
of them those four. **The intersection is zero, and the chapter disjointness is structural
rather than one month's accident** (#247).

So two of the four cases below — *filed but not yet served* and *agreement* — cannot occur on
the current manifest, and the one job hashing is kept for is scoped to 484 rules the Bulletin
has never named. A drift run printing `oar 484/484` reads as coverage of the OAR mirror; it
is coverage of 1.3% of it. `src/oar_watch_coverage.py --check` now says so on every run, and
fails if this paragraph and the manifest stop agreeing.

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
