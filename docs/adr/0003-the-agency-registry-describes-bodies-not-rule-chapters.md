# The agency registry describes bodies, not rule chapters

The registry was built by walking the OAR chapter index, so a chapter assignment was what
made a body real: one chapter, one entry, name taken from the chapter page's title. That
held until bodies without chapters had to be recorded anyway, and seventeen entries acquired
`manual: true` — among them the Secretary of State and the Governor's Office, which issue no
rules and never will.

We decided the registry describes **Oregon state bodies**, and that evidence of one comes in
two strengths: an OAR chapter or an enabling authority **admits** a body, while a DAS agency
number only **corroborates** one already admitted. We also decided `name` is the
**statutory** name, and the OAR chapter title moves to `oar_name`.

## Considered options

Keeping the registry strictly OAR-keyed was the cheapest option and the most honest about
how the data was gathered. It fails on its own exception list: seventeen entries already
break the rule, and `manual: true` records only that a human insisted, never *why the body
belongs*. Importing the DAS agency numbers from OAM 70.10.00 would have made this worse —
133 numbers against 80 currently mapped, so every unmatched one becomes another judgment
call with nowhere to record its basis.

Two registries — one OAR-keyed, one DAS-keyed, joined by slug — keeps each population
honest and was genuinely tempting. We rejected it because the join is the whole problem: a
body is one body, and the reason we know it exists is not part of its identity. Three
corpora already crosswalk into *one* registry, and giving them two to reconcile pushes our
bookkeeping into every consumer.

**Evidence is the load-bearing word, and it has two strengths.** The first draft of this
decision made all evidence equal — any of the three sufficient to admit a body — and OAM
70.10.00 immediately showed why that is wrong. Its 133 numbered rows include 22 commodity
commissions the registry has never carried and one row, `60310`, that is a grouping header
naming no organization at all. Under equal evidence, importing a code field would have grown
the registry by 12% and minted an entry for a category, both as side effects nobody asked
for.

So a DAS number corroborates and never admits. That a body is numbered for financial
administration establishes that it exists; it does not establish that it is this registry's
subject, and those are different claims. The 22 commissions may well belong here — they are
real bodies with ORS 576 authority — but they should arrive because someone admitted them,
not because a code import swept them in.

An unmatched number is REPORTED rather than dropped. That is the discipline
`link_budget_codes.py` already keeps with its explicit `UNMAPPED` list, and the one the
consumer crosswalks keep with `unmapped` — "we looked and there is no counterpart" and
"nobody has looked yet" must not be the same state. It also dissolves the `60310` problem
without a special case: a grouping header matches no body, lands in the report, and is
recorded there as a non-body once a human says so. Making the distinction structural retires
`manual: true`, which could not express any of it.

**The name decision is the risky half, and it is deliberate.** `name` is what
`oregon-kpm`, `oregon-audits` and `oregon-budget` resolve against today, and it currently
holds the OAR chapter title. Adding `statutory_name` alongside would have changed nothing
and broken nothing. We chose to promote the statutory name to `name` because the registry's
subject is the body, and a body's name is the one its enabling authority gives it — the OAR
index is a publisher, and publishers spell things their own way. `Business Development
Department, Oregon (DBA: Business Oregon)` is one string in DAS's register, another in the
rules index, and a third in statute; only one of those is the body's name.

The cost is real and falls outside this repo: each consumer crosswalk must be re-verified
against the new `name` before this lands, because a crosswalk that silently keeps matching
on a string that now means something else is exactly the failure these crosswalks exist to
prevent.

**Where evidence disagrees, statute decides and the disagreement is kept.** DAS nests the
commodity commissions under one header; the OAR index derives hierarchy from chapter
assignment; a statute may place a body under a third parent. Enabling authority wins, because
it is what actually created the relationship — but the other readings are recorded rather
than resolved away. A body that DAS files under one parent and statute under another is a
finding, and silently picking one hides it.

## Consequences

`name` becomes the statutory name; the OAR chapter title lands in `oar_name` and remains
the string OAR-derived joins must match. `manual: true` retires — a row is justified by the
evidence it carries. `budget_agency_code` is renamed to `das_agency_number`, because the
number identifies a body in the state's financial administration and says nothing about
whether it spends money: thirteen semi-independent bodies carry one and are explicitly
outside the state's accounting system.

Enabling authority is recorded as an authority, not as a statute, so constitutional offices
have somewhere true to sit. A body created by executive order has neither a statute nor a
constitutional article, and that absence is recorded rather than left blank.

Adding a body now requires stating what ADMITTING evidence puts it there, which is more work
per entry and is the point. Importing OAM 70.10.00 will produce a standing report of numbers
matching no body — 23 of them today, the 22 commissions plus `60310` — and that report is
the intended output, not a failure to finish the job.

What this does not settle is what disqualifies a body. Local school districts and
municipalities are out of scope, but "Oregon state body" is doing that work by assertion
until a case forces it to be written down. The commodity commissions are the first real
test: nothing here says whether they should be admitted, only that a code import may not
admit them.

## Amendment (2026-08-28): the commodity commissions were already carried when this was written

Filed as #156. The worked example above says OAM 70.10.00's "133 numbered rows include 22
commodity commissions the registry has never carried" and that equal evidence "would have
grown the registry by 12% and minted an entry for a category." Both describe the registry's
state, and neither was ever true. `_meta/catalog/agencies.yml` added the Oregon Albacore
Commission and twenty-two other Department of Agriculture child rows on 2026-07-19 — a month
before this ADR was drafted (2026-08-19) — each with a `relations` entry naming the
Department of Agriculture, and has carried them continuously since. They were invisible to
whoever wrote the passage because the OAR index stores each one under the compound name
`Department of Agriculture, <Child>`. A different obstacle affected the enabling-authority
matcher: its catchline anchoring initially missed the nineteen rows tied to ORS 576.062
because that section's own catchline names the *category* — "Establishment of commodity
commissions" — not any individual commission. #159's enumerated-list matching, not the
comma-splitting #155 added for compound registry names generally, is what recovered those
nineteen.

Measured now against the committed registry, two sets need to be told apart: OAM 70.10.00's
`60310` heading names 22 commissions, and the registry carries 23 Department-of-Agriculture
child rows. They overlap in 21 members. Two registry rows carry no name from OAM's list — the
Oregon Alfalfa Seed Commission and the Oregon Invasive Species Council, ORS 570.770, which is
not itself a commodity commission; its authority is invasive-species policy, not agricultural
marketing. Going the other way, one OAM name has no registry row at all: the Oregon Hemp
Commission, number 609, listed under `60310` alongside the other twenty-one. That is a real
gap in the registry, filed separately as #281; it is not fixed here, because this ADR records
a decision, not the registry's contents.

Of the registry's 23 Department-of-Agriculture rows, 22 carry a reviewed `enabling_authority`.
Nineteen share the enumerated ORS 576.062; three carry their own section — the Oregon Beef
Council, ORS 577.210; the Oregon Wheat Commission, ORS 578.030; and the Invasive Species
Council, ORS 570.770. Only the Oregon Alfalfa Seed Commission carries no
`enabling_authority` key at all, which means nobody has reviewed it yet, not that a review
found none to record. All 23 rows, the Alfalfa Seed Commission included, carry an OAR
chapter, and were admitted on that evidence alone starting 2026-07-19, a month before this
ADR existed to state the rule; the enabling-authority review is later, additional evidence
for 22 of them, not the evidence that first admitted them. So the population the original
passage counted as absent was present the whole time, admitted throughout on evidence this
ADR treats as sufficient on its own — by OAR chapter first, and by a reviewed enabling
authority today for all but the Alfalfa Seed Commission.

The `60310` half of the same sentence is checked at the same time, and it stands: OAM
70.10.00's 133 numbered rows still include `60310 Commodity Commissions (Individual
commissions listed below)`, a grouping header naming no individual organization, followed
by its twenty-two named commissions as separate indented rows. That header is not a body
under any evidence this registry accepts, and nothing here changes it.

**What the 12%-growth figure gets wrong, and what still holds without it.** The figure
assumed a code import would mint 22 or 23 *new* entries; it would not have — all 23 of the
Department-of-Agriculture rows already existed, admitted by OAR chapter, before OAM 70.10.00
was ever read against the registry. What equal evidence would actually mint here is two
entries: `60310` itself, a grouping header with no body behind it, and the Oregon Hemp
Commission (#281), a real body OAM names that the registry does not yet carry. A single
grouping header admitted as if it were a body is disqualifying on its own, so the argument
does not need a percentage — but stated as one anyway, to keep the comparison honest: two
entries against OAM's 133 numbered rows is 1.5%, and on the original figure's own base —
growth against the 189 rows that existed beforehand — it is two rows over 189, 1.06%, not
the twenty-two rows over 189 (11.64%) the original 12% assumed. Either base gives a far
smaller fraction than the retired claim, from a different cause: nothing was being added,
because almost everything counted was already there.

**The closing paragraph's open question is answered, and was answered before this ADR was
written — for the registry's own rows.** "The commodity commissions are the first real
test: nothing here says whether they should be admitted" does not hold for any of the
registry's 23 Department-of-Agriculture rows: every one carries an OAR chapter, which is
admitting evidence under this ADR's own rule, and has since 2026-07-19. It does not hold for
the Oregon Hemp Commission either, in the opposite direction — nothing has admitted it,
because the registry carries no row for it to admit, which is exactly the gap #281 files.
What was genuinely open, and stays open here, is what evidence beyond the OAR chapter each
registry row carries and what relation it holds to the Department of Agriculture. Of the 23,
22 — the 21 that match OAM's list plus the Invasive Species Council — now carry both a
reviewed `enabling_authority` and an `administered_by`
relation citing it (ADR 0004); the Alfalfa Seed Commission alone stays `undetermined` on
both counts, because no enabling authority has yet been found for it, and a relation needs
one to derive from. The worked example survives correction rather than being replaced: OAM
70.10.00 is still the example, `60310` is still the disqualifying case, and the
admitting/corroborating distinction still rests on it — only the counts of what a code
import would have minted, and of what the registry already held, are corrected in place.

The Consequences section above — "a standing report of numbers matching no body — 23 of
them today, the 22 commissions plus `60310`" — is checked at the same time and needs no
correction: it counts by `das_agency_number`, which none of the 23 Department-of-Agriculture
rows carry, so all 22 OAM commission numbers plus `60310` still match no body under that
join. That is a different join from the name match this amendment corrects above, over
overlapping but non-identical sets, which is why the two give different counts without
disagreeing.

This correction follows the convention ADR 0004 already set with its own two `## Amendment`
sections: the text above stands unedited, because it records what was believed and argued
at the time, and the correction sits beside it rather than being folded silently into the
original prose. Dating this section's heading is new here, not inherited — ADR 0004's two
amendments carry no date in their own headings, only one landing date stated once in that
section's prose — and is recorded as the convention going forward.

## Amendment (2026-08-28, later the same day): #281 closed the gap this amendment names

The paragraph above states, in the present tense, that the Oregon Hemp Commission carries
no row "because the registry carries no row for it to admit, which is exactly the gap #281
files." Commit `180bb020b9` landed on this branch later the same day and added that row
(`oregon-hemp-commission`), admitted on ORS 571.406 rather than the ORS 576.062 the other 21
commodity commissions rest on — ORS 571.435 lists the Hemp Commission separately from the
commissions created under ORS 576.051 to 576.455, so the enumerated-list evidence the other
21 rest on does not reach it and it needed its own citation. The sentence above is left
exactly as it stood when drafted, per this ADR's own convention two paragraphs up; this note
is the pointer forward, not a correction of it.
