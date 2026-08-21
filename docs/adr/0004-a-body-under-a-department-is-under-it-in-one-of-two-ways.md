# A body under a department is under it in one of two ways

Eighty-one of the registry's 189 entries carry a `parent_slug`, and the field says the same
thing about all of them: this body is under that one. The commodity commissions are under
the Department of Agriculture. The Highway Division is under the Department of
Transportation. Both statements are true and they are not the same statement.

We decided `parent_slug` splits into two relations. A body is **part of** another when it
has no separate constitution — the parent is the body and this is its internal structure.
A body is **administered by** another when it is separately constituted and attached to a
department for administration. Which one applies is decided by the test ADR 0003 already
defines: does this unit carry its own admitting evidence beyond the OAR chapter that put
it in the registry?

## Considered options

Leaving `parent_slug` alone was tempting because nothing is currently wrong. No consumer
misreads it, because no consumer asks it anything: the crosswalks join on slug and read
`name`. It fails on the first question anyone will actually ask of a register of bodies —
*is this a separate body or part of a bigger one* — and the field cannot answer it. Worse,
it answers confidently, which is how a reader concludes the Oregon Trawl Commission is a
division of the Department of Agriculture.

Statute is unambiguous that it is not. ORS 576.062 reads "The following commodity
commissions **are established as state commissions**", and enumerates nineteen of the
twenty-three the registry carries. The department's role over them is a separate section:
ORS 576.066 has the department monitor their practices, appoint and remove their members,
review their budgets and approve their plans. That is oversight of a body, not composition
of one, and the same section names "the several commissions, the Oregon Beef Council and
the Oregon Wheat Commission" as peers.

Contrast `Department of Transportation, Highway Division` or `Secretary of State, Elections
Division`. There is no statute constituting either, because there is no separate body to
constitute. That is one legal entity describing how it organises itself.

**The distinction is measurable today, which is why it is worth encoding.** Of the 81
children, 25 have their own statutory authority and 56 do not. That is not a spectrum with
hard cases in the middle; it is two populations. Adding a hand-maintained `kind` field
would have let a human assert the answer, and we rejected that for the same reason ADR 0003
retired `manual: true`: an assertion records that someone decided, never what decided it.

We also rejected inferring the relation from the OAR chapter. Every one of the 189 has its
own chapter, and every one of the 81 children has a chapter distinct from its parent's, so
the rules index cannot tell a division from a body. This is the same lesson as the DAS
agency number: a publisher's filing decision is evidence about the publisher.

**The relation carries its own authority, and that is the point.** Recording that the
commodity commissions are administered by the Department of Agriculture is less useful than
recording that ORS 576.066 is what makes that true, and that what it covers is member
appointment, budget review and plan approval — not rulemaking, and not legal identity. A
bare parent pointer states a hierarchy; a cited one states a claim about Oregon law that a
reader can check. It also gives ADR 0003's rule that disagreements are kept somewhere to
live: DAS's nesting, the OAR chapter's nesting and statute's placement become three sources
for one relation, recorded side by side rather than reconciled into silence.

**The compound name goes, and ADR 0003 already retired it.** `Department of Agriculture,
Oregon Albacore Commission` is not the body's name; ORS 576.062 calls it the Oregon
Albacore Commission. The compound is a path the OAR index built, duplicating `parent_slug`
inside a string, and it has already cost three times: it defeated the enabling-authority
matcher for 81 bodies until #155, it hid the commodity commissions from ADR 0003's own
worked example (#156), and it is not applied consistently — `Oregon Health Authority Equity
and Inclusion Division` has a parent and no comma, alone among the 81.

## Consequences

`parent_slug` is replaced by a relation that names the parent, its kind, and the authority
establishing it. A body may hold more than one, because a body may genuinely sit under
different parents according to different sources, and that disagreement is a finding.

Nesting stops being a naming problem. `Oregon Health Authority, Health Licensing Office,
Board of Cosmetology` looks like it needs a three-level model; it does not. The Health
Licensing Office is a body (ORS 676.560) and the Board of Cosmetology is a body (ORS
690.155), so it is two `administered_by` hops between three bodies, and a single parent
reference per body handles it at any depth. Only the compound name made depth look
structural.

Divisions stay in the registry. Their OAR chapter is admitting evidence under ADR 0003, so
`part_of` is not a demotion and does not narrow the register's scope — it records that the
unit's legal existence is its parent's. What changes is that a division no longer looks
like a body with a missing enabling authority, which is how all 56 currently read.

`UNMAPPED` gains its most common legitimate reason. A `part_of` unit has no enabling
authority because there is nothing separate to enable, and that is a decision with a stated
basis rather than a gap. Distinguishing it from a body whose statute has not been found yet
is the whole discipline this repository keeps.

What this does not settle is whether the two kinds are exhaustive. Eight of the twelve
licensing boards that reached tier 3 are declared to operate as semi-independent state
agencies under ORS 182.456 to 182.472, and they are attached to no department at all in the
ordinary sense. Whether that is a third relation or an absence of one is not decided here. Nor does it settle the Oregon Alfalfa Seed
Commission, which the registry carries as a commodity commission and which ORS 576.062 does
not enumerate.
