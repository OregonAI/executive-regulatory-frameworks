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
A body's name as its enabling authority states it, and the canonical `name` in the registry.
Distinguished from the name any particular publisher uses for it.
_Avoid_: Official name, legal name, proper name

**OAR name**:
The name the administrative rules index gives a body. It differs from the statutory name
often enough to matter, and it is the string OAR-derived joins must match.
_Avoid_: Rules name, chapter name

**Enabling authority**:
What created the body — a statute, or the Oregon Constitution. Not every body has a
statutory one: the Secretary of State and the State Treasurer are constitutional offices,
and a body created by executive order has neither.
_Avoid_: Enabling statute, creating ORS, organic act — all three presuppose a statute

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

**DAS agency number**:
The number DAS assigns a body in the Oregon Accounting Manual (OAM 70.10.00). It identifies
the body in the state's financial administration and is not evidence that the body spends
money: semi-independent bodies carry a number and are explicitly outside the state's
accounting system.
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
