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
