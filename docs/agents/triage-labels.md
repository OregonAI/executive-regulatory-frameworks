# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Edit the right-hand column to match whatever vocabulary you actually use.

## These are a second axis, not a replacement

`AGENTS.md` requires every issue to carry a **topic** label on creation — `bug`,
`enhancement`, `documentation`, or `question` — and forbids inventing labels on the fly.
The five roles above describe issue **state** instead, so they sit alongside a topic label
rather than substituting for one. A triaged issue normally carries both, e.g.
`bug` + `ready-for-agent`.

Because they are sanctioned here, applying them is not "inventing a label on the fly".
`wontfix` already exists on the repo; the other four are created on first use.
