# The Bulletin is notice; hashing is observation

Oregon publishes the **Oregon Bulletin** on the first business day of each month: the
official digest of rule filings. `src/check_bulletin.py` reads it and writes
`_meta/bulletin-worklist.yml` — every OAR rule number that month's permanent, temporary and
minor-correction filings adopt, amend, repeal, renumber or suspend. August 2026 (bulltnRsn
1761): 549 rule actions from 159 filings, 418 against rules this corpus holds.

Separately, `corpus-detect-changes` hashes the 484 OAR chapter sources and reports what
moved.

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
no longer the primary signal, because it cannot name a rule — 484 chapter sources stand for
36,955 rule documents, so a moved hash says only that something in a chapter changed.

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

**`in_corpus` is three states, not two.** Measured across two bulletins, every
not-in-corpus rule (312 in July, 131 in August) was in a chapter outside our selection, and
none was a rule missing from a chapter we mirror. Those are different facts and the second is
a genuine gap, so they are recorded apart before they first collide rather than after.

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
