# Auditor evidence is recorded separately from the triage verdict

Conflict candidates carry `triage.status` — our binary verdict, `confirmed` or `dismissed`,
which feeds `_meta/eval/triage-verdicts.yml` as human-authored ground truth. When we began
checking candidates against Oregon Secretary of State audit reports, the two looked like the
same field. We decided they are **separate fields recording separate statements**, and that
the auditor taxonomy has four values rather than the verdict's two.

## Considered options

Reusing `triage.status` for auditor findings was tempting: both are judgments about a
candidate, the schema already existed, and the tooling already wrote to it. It is wrong
because the two answer different questions. `triage.status` answers *is this candidate a
real conflict* — our conclusion. Auditor evidence answers *what does an independent expert's
report say about this provision* — someone else's, about the world.

Collapsing them corrupts the evaluation set. An audit that merely mentions a document has
said nothing either way, but the binary schema has nowhere to put "no evidence"; it would be
recorded as `dismissed` and become a hard negative that no human ever judged false. The eval
would then be scoring models against an assertion nobody made.

The taxonomy needs four values, not three, because *cited as authority* — an audit citing a
provision as the standard it measures an agency against — is the expected case for statutes
and has no home in corroborate/contradict/mention.

## Consequences

`triage.status` stays binary and untouched. Auditor evidence lands in its own field, and the
two passes are performed separately so third-party evidence does not anchor our own verdict.

The overlap between the two corpora is therefore not a result on its own. A document appearing
in both sets is a hypothesis about where to look, and reporting the raw overlap as validation
would assert exactly the thing the reading pass exists to test.
