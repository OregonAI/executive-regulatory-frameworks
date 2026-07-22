# Oregon Youth Authority — policies — index

Policies (`doc_type: policy`) issued by Oregon Youth Authority
(`agency: oregon-youth-authority`). **Non-authoritative copies** — see [AGENTS.md](../../../AGENTS.md).

Listing of record: <https://www.oregon.gov/oya/pages/policies/policy_list.aspx> (static
HTML; each policy's own link text carries its number and title, mechanically discovered —
no SharePoint API needed). 156 of 157 discovered PDF links ingested (one duplicate link to
an already-ingested policy). Full manifest with per-document hashes:
[`_meta/sources/oregon-youth-authority-policies.yml`](../../../_meta/sources/oregon-youth-authority-policies.yml).

| Part | Scope |
|---|---|
| 0 | Mission, Values, Principles |
| I | Administrative Services |
| II | Facility Operations |
| III | Field / Community Services |

Each policy's "Supersedes:" table lists prior effective dates of the *same* policy number
(a revision history), not a distinct predecessor policy — `supersedes` is left `null` in
frontmatter rather than mis-mapped to that field's DOC-style meaning.
