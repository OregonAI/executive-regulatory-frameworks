# Oregon Executive Regulatory Frameworks

A corpus of Oregon statutes, administrative rules, executive orders, and agency-issued
policy documents, mirrored verbatim from their official sources. This file is the
glossary: what the words mean here, and which near-synonyms to avoid.

## Documents

**Document**:
A single mirrored instrument — one statute section, one rule, one agency policy — carrying
its own frontmatter and its source's full text.
_Avoid_: Record, entry, page

**Policy**:
An agency-issued instrument stating a rule the agency itself follows. Distinguished from a
statute or administrative rule by who issues it, not by how binding it is.
_Avoid_: Directive, guidance

**Transmittal**:
A document that announces a change to a policy without being one. It says a policy changes
on a date; it does not state the rule. A transmittal is never the body of record for what a
policy says.
_Avoid_: Notice, memo, update

**Policy Transmittal (PT)**:
The specific ODHS transmittal series that announces policy changes. The sibling series
(Action Requests, Information Memoranda) are not Policy Transmittals and are out of scope
wherever "PT" is written.

**Announces**:
The relationship a transmittal bears to a policy. A transmittal *announces* a change; it
never supersedes, amends, or replaces the policy it refers to.
_Avoid_: Supersedes, updates, amends

## Agencies

**Issuing body**:
An Oregon state body this corpus can attribute a document to. It is the general term; a
*registry entry* is the record of one.
_Avoid_: Organization, entity, department (a Department is one kind of body, not the class)

**Agency registry**:
The catalog of issuing bodies, and the identity every other OregonAI corpus crosswalks
into. A body is in it because it EXISTS, not because it issues rules. Being absent means no
admitting evidence was found, never that none was sought.
_Avoid_: Agency list, catalog, org chart

**Admitting evidence**:
Evidence that puts a body in the registry: an OAR chapter, or an enabling authority. Either
alone is enough.

**Corroborating evidence**:
Evidence that attaches to a body already admitted but never admits one — a DAS agency
number is the case that forced the distinction. That a body is numbered for financial
administration says it exists; it does not say it is this registry's subject. Corroborating
evidence that matches nothing is REPORTED, never discarded: an unmatched number is a
question for a human, not noise.

**Registry slug**:
A body's stable identifier, and the only thing another corpus should join on. Names change
and are spelled differently by every source; the slug is what survives that.
_Avoid_: Agency id, key, code — a *code* here means a DAS agency number

**Statutory name**:
A body's name as its enabling authority states it, and what the registry's `name` field
means (ADR 0003). Distinguished from the name any particular publisher uses for it: the
Board of Chiropractic Examiners is what the rules index prints, and ORS 684.130 establishes
the **State** Board of Chiropractic Examiners. NOT EVERY ROW HOLDS ONE. Establishing a
statutory name means a human reading the authority that created the body, and most bodies
have not been read yet — so `name` holds an unverified OAR title on those rows, and the row
says which it is holding in *name basis*. The field means "statutory name"; whether a
particular row has one is the row's to state, never something a reader may assume from the
field.
_Avoid_: Official name, legal name, proper name

**Name basis**:
Which of the two things a registry row's `name` is, written on the row in `name_basis`.
`enabling-authority` means the statutory name, read off the body's enabling authority by a
human and recorded in `src/link_enabling_authority.py`, which is the only thing that
establishes one; the row must carry an authority to support the claim, and
`catalog_agencies.py --check` refuses it otherwise. `unverified-oar-title` means nobody has
established a statutory name for this body and `name` still holds the OAR chapter title it
was scraped with, unchanged. The two are never the same state — a row quietly keeping its
OAR title under a field that means *statutory name* is a false statement about Oregon law
published under provenance, which is the same substitution `manual: true` was retired for
and the same one an explicit `unmapped` prevents. Which basis a row states also decides what
`--refresh` does to its name: an established name is carried across untouched, an unverified
one is rebuilt from the chapter page so an upstream retitle reaches it.
_Avoid_: Verified, confirmed, source — a basis says what a name was read off, not how sure
anyone is

**OAR name**:
The name the administrative rules index gives a body — its chapter page's own title, in
full. It differs from the statutory name often enough to matter, and it is the string
OAR-derived joins must match. Every registry entry carries one, in `oar_name`. Where a body
holds a chapter the field is scraped rather than curated, so an upstream retitle moves it,
which is the only reason a join can rely on it; the entries holding no chapter carry the
name this registry publishes for the body, which is what a join has to match and is not a
claim that the rules index prints it.
_Avoid_: Rules name, chapter name — and `raw_index_name`, which is the index's own
abbreviated spelling (`Board of Chiropractic Exam'rs`) and a different string

**Raw index name**:
The abbreviated spelling the rules index's own tree prints for a body — `Board of
Chiropractic Exam'rs`, `Dept. of Administrative Services` — kept verbatim in
`raw_index_name`. It is a THIRD string, not a variant of the OAR name: the index abbreviates
in its listing and prints the title in full on the chapter page, and the registry keeps both
because they are what two different pages of one publisher actually say. Nothing joins on it;
it is evidence of what the index printed, and it is scraped, so it moves when the index does.
_Avoid_: Short name, display name, abbreviation — none of those say whose spelling it is

**Enabling authority**:
What created the body — an ORS section, an article of the Oregon Constitution, or an
executive order. It is recorded as an AUTHORITY and not as a statute (ADR 0003), so
constitutional offices have somewhere true to sit: the Secretary of State and the State
Treasurer hold no statute, and a body created by executive order holds neither a statute nor
a constitutional article. It lives in `enabling_authority` on the registry rows that carry
one, hand-reviewed in `src/link_enabling_authority.py`, which is the only thing that writes
the field. THREE STATES, which may never be collapsed into two: a value in one of those
three forms records an authority; `none: ` and a reason records that someone looked and
there is none to record (ADR 0004's commonest case — a *part of* unit has nothing separate
to enable); and an absent key, which is where all 189 rows stand today, means nobody has
looked yet. A body recorded *part of* another may never carry an authority in the first
form: the two are opposite claims about one body, and `catalog_agencies.py --check` refuses
a row asserting both. Absence is never the claim that a body has no enabling authority, and
a blank value is refused for making that claim with nobody behind it.
_Avoid_: Enabling statute, creating ORS, organic act — all three presuppose a statute

**Legal status**:
Whether a rule is in force. It lives in the document's `status` frontmatter field, whose values
corpus-toolkit's schema fixes as `current | superseded | repealed | proposed | draft`, and it
is a claim about Oregon law. Measured over the committed corpus: 34,836 rules read `current`,
2,083 `repealed` and 34 `superseded`. ITS WRITER IS THE OREGON BULLETIN (ADR 0006), and since
#228 that is a single function — `legal_status.resolve()` — rather than a convention. It had
two writers: `ingest_oar.py` wrote `status: current` as a hardcoded literal on every rule it
created, and `enrich_oar.py` derived the field from the rule's own History line and compared it
in a nightly gate, which would have restamped a Bulletin repeal back to `current` and then
failed the build for the Bulletin being right. Both now read the one writer, which weighs what
each of them knows in a fixed order: a status the Bulletin set, then a repeal in the rule's own
served History, then what the document already says, then `current` — which a fresh ingest may
assert only where nothing better is known. A Bulletin-set status is carried on the OAR catalog
row in `legal_status` and stamped onto the document from there, so the catalog writes and the
document reads. `legal_status.py --check` fails if a second writer appears and `--selftest`
proves it, a re-ingest overwriting a Bulletin-set status included. Since #229 the August 2026
bulletin's 66 repeals and 34 suspensions against rules held here are recorded, and the rules
are MARKED AND KEPT — path, ingest status and document untouched, because deleting a repealed
rule breaks every citation pointing at it.
_Avoid_: Status, unqualified — the catalog has a different field by that name

**Filed force action**:
What the Oregon Bulletin did to a rule's FORCE, as opposed to its text — `repeal` or
`suspend`, the two of `check_bulletin.ACTIONS` that ADR 0006 routes to a person instead of to
an automatic re-ingest. It lives on the OAR catalog row in `legal_status_action`, beside the
`legal_status` it produces and the `legal_status_notice` that filed it, and all three arrive
together or `legal_status.py --check` refuses the row. IT IS ON THE ROW BECAUSE THE SCHEMA
ENUM CANNOT HOLD IT: `current | superseded | repealed | proposed | draft` has one word for a
loss of force and it means a permanent one, while every suspension Oregon files carries an
end date — 185 History lines in this corpus read `temporary suspend filed …, effective …
through …`. So a suspension is stamped `superseded`, the strongest thing the shared enum can
truthfully say (this is not the operative text right now), and the action is what says the
loss is temporary (the gap in the shared enum is corpus-toolkit#159). Without it, 34
suspended rules and 66 repealed ones would be one
undifferentiated set, which is the collapse #229 exists to prevent.
_Avoid_: Bulletin action, filing type — a filing also adopts, amends and renumbers, and those
three change TEXT, re-ingest without asking (#230) and set no legal status at all

**Filed text action**:
What the Oregon Bulletin did to a rule's TEXT, as opposed to its force — `adopt`, `amend`
or `renumber`, the three of `check_bulletin.ACTIONS` that ADR 0006 routes to an AUTOMATIC
re-ingest instead of to a person. It lives in `reingest_oar.TEXT_ACTIONS`, and the two
tables together must cover `check_bulletin.ACTIONS` EXACTLY ONCE — a verb in neither is
read by nothing, a verb in both is re-ingested and reviewed with the re-ingest running
first, and `reingest_oar.py --check` fails on all three. The table is DECLARED rather than
derived as "everything that is not a force action", because a complement makes a verb
nobody has classified re-ingest unattended the day it appears upstream. A rule the same
bulletin ALSO took out of force is refused by rule and not by row: August 2026 amended 12
rules it repealed or suspended, and re-ingesting them would leave the whole safety property
resting on `legal_status.resolve()` being handed the right argument one line later.
Measured on the August 2026 bulletin: 318 amendments against rules this corpus holds, 306
re-ingested and 12 refused by name.
_Avoid_: Amendment, text change — an adoption and a renumber are neither, and a renumber
that changes a rule's number does not change the text under it

**Re-ingest record**:
What a catalog row says about a text refresh this corpus applied without asking anybody. It
lives on the OAR catalog row as `reingest_action` and `reingest_notice`, which arrive
together or `reingest_oar.py --check` refuses the row — the notice alone cannot say which
filing was applied and the action alone is a fact about no particular month. It is a claim
about THIS MIRROR, like ingest status and unlike legal status, and it never appears on a
row that carries a Bulletin-set `legal_status`: a rule out of force is MARKED AND LEFT
(ADR 0006) and an unattended write to one is how a repealed rule comes back as current
under provenance. `reingest_oar.py --check` reads the committed worklist and demands the
record for every text action filed against a held rule, so the gate cannot be satisfied by
a corpus that re-ingested nothing.
_Avoid_: Status, unqualified — the OAR catalog row already spells two different fields that
way and this is a third fact about the same rule

**Ingest status**:
Whether this corpus holds a copy of a rule, and in what shape. It lives in
`_meta/catalog/oar.yml` as `rules[].status`, with its own vocabulary — `ingested` (36,474),
`renumbered` (484, carrying `served_as`), `not_served` (49). It is a claim about THIS MIRROR,
never about Oregon law: a rule can be in force and absent here, or repealed and still held.
The Bulletin's claim about force sits on the SAME ROW under different keys — `legal_status`,
`legal_status_action` and `legal_status_notice`, none of which may appear without the others —
and the two vocabularies never borrow each other's words — `legal_status.py --check` reads
all 37,007 entries and refuses either field holding the other's vocabulary, because on the day they
first collide nothing else in the repository would notice.
_Avoid_: Status, unqualified. The two fields share a name and mean different things, which is
why both entries exist

**Worklist corpus state**:
What the Oregon Bulletin's monthly worklist knows about a rule a filing named, and it is
THREE things: `held` (a document is in `rules/`), `missing_from_mirrored_chapter` (this
corpus mirrors the chapter and holds no document — a coverage gap) and
`chapter_not_mirrored` (the chapter is outside the selection — a boundary, not a fault).
It lives in `_meta/bulletin-worklist.yml` as `rules[].corpus_state`. It is a claim about
THIS MIRROR and about nothing in Oregon law, which it shares with ingest status and not
with legal status. The August 2026 bulletin put 121 rules in the second state, 43 of them
amendments; the field it replaced, `in_corpus: true|false`, had no way to say so.
_Avoid_: `in_corpus`, in corpus, held — the first is the two-state field this replaced,
and reading the new spelling off the old name finds every value truthy

**Part of**:
The relation a unit bears to the body it is internal structure of. A unit is *part of* a
body when nothing separately constitutes it — the Highway Division is how the Department of
Transportation organises itself, not a second body. It has no enabling authority because
there is nothing separate to enable, which is a decision with a reason and not a gap.
_Avoid_: Under, belongs to, child of — all three also describe *administered by*

**Administered by**:
The relation a separately constituted body bears to the department that administers it. The
commodity commissions are *established as state commissions* by ORS 576.062 and
*administered by* the Department of Agriculture under ORS 576.066, which covers member
appointment, budget review and plan approval — not rulemaking, and not legal identity. The
relation cites the authority that establishes it, because a bare parent pointer states a
hierarchy where a cited one states a checkable claim about Oregon law.
_Avoid_: Division of, part of, reports to — an administered body is not part of its parent

**Relation**:
What one body's placement under another is recorded as: a `target` (the parent's registry
slug), a `source` (whose evidence places it there), a `kind` — *part of*, *administered by*,
or `undetermined` — the `basis` that kind was derived from, and the `authority` that makes
it true. It lives in `relations` on every registry row, and since #174 it is the ONLY
statement this registry makes about where a body sits — it REPLACED `parent_slug`, which a
row may no longer carry (ADR 0004). An *administered by* relation always cites an authority, because that
is the claim about Oregon law a reader checks; *part of* cites none, because there is
nothing separate to cite. WHICH section the citation is, is the `basis`'s to say. A derived
relation cites the section that CONSTITUTES the body — ORS 576.062, which is the evidence
its kind rests on — and not the one that establishes the administration; both derived bases
are named for an *enabling authority* for exactly that reason. ORS 576.066, the section the
department's administration runs on, is a curated decision on a basis nothing derives. A body may hold MORE THAN ONE, because DAS, the OAR index and
statute may each place it under a different parent, and ADR 0003 keeps that disagreement
rather than reconciling it: enabling authority decides, and the other readings are
recorded, not resolved away. An empty list says this registry places the body under no other.
_Avoid_: Parent, hierarchy, edge — a relation states whose reading it is, and those do not

**Relation source**:
Which evidence places a body under a parent, written on the relation itself: `oar-index`
(the rules index's tree, which is where the retired `parent_slug` came from), `statute`,
`das`, or
`registry` — a placement this registry recorded by hand, on evidence stated in the row's
`note`, which is the only true source for the one body the rules index does not carry. It is
what makes one list able to hold two origins — an `oar-index` entry is REGENERATED by
`catalog_agencies.py --refresh`, so an upstream re-filing reaches the registry, while every
other entry is curation the refresh carries across untouched. An `oar-index` entry on a row
the scrape cannot see is refused twice over: the index placed that body nowhere, and nothing
can regenerate the entry. A relation with no source is
refused, because it is one nothing can keep safe: `note` is the field that has two origins
and no way to tell them apart, and a hand-written note there is destroyed by a refresh with
nothing to report it.
_Avoid_: Provenance, origin — those name where a document came from, not who says the body
sits here; and never *basis*, which is the key BESIDE this one on the same relation and
answers a different question (what decided the kind)

**Relation basis**:
What decided a relation's KIND, written on the relation itself and never the same fact as
its source: the source says who places this body under that one, the basis says what settled
which of ADR 0004's two kinds it is, and a relation the OAR index discovered can have its
kind decided by a statute. TWO STRENGTHS, which may never be collapsed into one:
`reviewed-enabling-authority` is the basis ADR 0004 describes — the authority the row itself
carries, hand-reviewed — and `proposed-enabling-authority` is a CANDIDATE from
`_meta/catalog/enabling-authority-review.yml` that nobody has read, which is a proposal and
not evidence. 44 of the 81 kinds rest on the second today, and the row upgrades visibly when
the review lands. A kind other than *undetermined* with no basis is refused, for the reason
`manual: true` was retired: an assertion records that someone decided, never what decided
it. It is written by one thing, `src/derive_relation_kinds.py`.
_Avoid_: Evidence, provenance, reason — a basis says what a KIND was derived from, and
`source` already answers where the relation came from

**Undetermined**:
The kind of a relation nobody has decided yet. Choosing between *part of* and *administered
by* turns on whether the body carries its own admitting evidence (ADR 0004), and 37 of the
81 relations have none of any strength — so `undetermined` is what they record, and
`catalog_agencies.py --check` reports the count on every run. It says the relation is REAL
and its kind unestablished, which is neither of the two kinds and is never a third one. It
is also never derived FROM an absence: that a matcher found no candidate for a body is a
statement about the matcher, so a relation nothing speaks to stays undetermined rather than
becoming *part of*, and 37 of them is the answer rather than a backlog.
_Avoid_: Unknown, null, blank — an absent kind lets a consumer read whichever it prefers

**DAS agency number**:
The number DAS assigns a body in the Oregon Accounting Manual (OAM 70.10.00). It identifies
the body in the state's financial administration and is not evidence that the body spends
money: semi-independent bodies carry a number and are explicitly outside the state's
accounting system. It lives in `das_agency_number` on the registry entries that carry one,
hand-reviewed in `src/link_budget_codes.py`; absence means no counterpart was found, never
that none was sought. The same number is also written to `budget_agency_code`, the name the
field carried before ADR 0003 — a deprecated key kept readable for one cycle so consumers
can move at their own pace, and required by `catalog_agencies.py --check` to hold exactly
what `das_agency_number` holds.
_Avoid_: Budget code, agency code, spending code — those name a consumer, not the identifier

**Semi-independent**:
A body that DAS numbers but does not include in the state's accounting system. A fact about
financial administration, not about the body's legal status or its rulemaking authority.

## Provenance

**Verbatim**:
Text reproduced exactly as the source states it. The corpus's default and its reason for
existing — a document reduced to a summary answers no question its source would have.
_Avoid_: Full text, complete

**Derived**:
A fact the corpus computes rather than reads, such as a policy's currency inferred from a
transmittal that announces it. A derived fact is never written into a field that would make
a document appear to assert it about itself.
_Avoid_: Enriched, inferred, backfilled

**Upstream drift**:
A change in what a source URL serves since it was last mirrored. Drift is a claim about
bytes, not about meaning — a re-render, a template change, or a broken fetch all produce it
without any document changing.
_Avoid_: Update, change, staleness

## Conflict analysis

**Conflict candidate**:
A model-proposed contradiction between two documents. A candidate is a hypothesis and is
never presented as a finding before a human verdict.
_Avoid_: Conflict, finding, contradiction

**Triage verdict**:
Our own binary judgment on whether a candidate is real — confirmed or dismissed. It records
what *we* concluded, and is the ground truth an evaluation scores against.
_Avoid_: Status, review, rating

**Audit corroboration**:
What an external auditor's report says that bears on a candidate. It is evidence about a
candidate, from a third party, and is never the same statement as a triage verdict — an
auditor who merely mentions a document has said nothing about whether the candidate is real.
_Avoid_: Validation, confirmation, agreement

**Cited as authority**:
The case where an audit cites a provision as the standard it measures an agency against,
rather than as a defect it found. The expected reading for a statute, and the reason a raw
citation overlap is not evidence on its own.
