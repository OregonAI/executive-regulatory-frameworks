# Transmittal-derived dates are computed, never stored on the policy

A transmittal announces that a policy changes on a date, which makes it the best available
signal for a weakness in this corpus: agency policies whose own text does not say when they
were last revised. We decided that such a date is **computed by joining a transmittal to
the policy it announces, and never written into the policy's frontmatter**.

## Considered options

Storing the derived date on the policy — as `effective_date`, or as a fourth date field
beside it — was the obvious approach and is the one we rejected. Policy frontmatter already
carries `effective_date`, `last_reviewed`, `source_version`, and `supersedes`, all read
verbatim from the document itself. A derived date placed among them is indistinguishable
from one the document asserts, so the corpus would begin stating, in the policy's own voice,
a fact only a different document attests. That is the failure the `[VERBATIM]`/`[SUMMARY]`
rules in `AGENTS.md` exist to prevent, and it would be introduced by the field's *position*
rather than by anything wrong with its value.

A provenance-bearing field on the policy (recording which transmittal supplied the date) was
the near-miss: honest about origin, but still denormalized, and stale the moment another
transmittal lands.

## Consequences

The transmittal carries the link (`announces`) and its own verbatim effective date; nothing
is written to the policies it refers to. Adding transmittals therefore cannot corrupt a
policy document, which is what makes a pilot ingest safe to try and cheap to abandon.

The cost is that freshness becomes a build-time join rather than a field lookup, and any
consumer wanting it must perform that join rather than reading it off the document.
