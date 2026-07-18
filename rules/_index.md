# Administrative Rules (OAR) — index

Oregon Administrative Rules: regulations with the force of law, adopted under ORS 183,
published in OARD by the Secretary of State. Directory layout: `rules/<chapter>/<division>/`.
**Non-authoritative copies.**

> **Renumbering note (May 2026):** the State Information Security rules moved from DAS
> chapter 125, Division 800 (OAR 125-800-xxxx) to **chapter 128 (Office of the State
> Chief Information Officer), Division 30** — AON "DAS 2-2026, renumbered from
> 125-800-xxxx, filed 04/28/2026, effective 05/01/2026". Many DAS policies still cite the
> old 125-800 numbers; those citations resolve to the 128-030 rules below.

| Citation | Title | Status | Effective | Path |
|---|---|---|---|---|
| OAR 128-030-0005 | Purpose, Application, and Authority | current | 2026-05-01 | [128/030/oar-128-030-0005.md](128/030/oar-128-030-0005.md) |
| OAR 128-030-0010 | Definitions | current | 2026-05-01 | [128/030/oar-128-030-0010.md](128/030/oar-128-030-0010.md) |
| OAR 128-030-0020 | State Information Security | current | 2026-05-01 | [128/030/oar-128-030-0020.md](128/030/oar-128-030-0020.md) |

## How to find the right rule

- **DAS's information-security duties and agency obligations:** OAR 128-030-0020.
- **Definitions (incident, information resources, security plan):** OAR 128-030-0010.
- Rule history is encoded in Administrative Order Numbers (AONs); upstream changes arrive
  via the monthly Oregon Bulletin (first business day).

## Full coverage map

DAS administers OAR chapter 125 (34 divisions covering procurement, real property, fleet,
surplus, risk management, records, and more) and chapter 128 (5 divisions, State CIO).
Only division 128-030 (State Information Security) is ingested so far, and only its 3
known rules. [`_meta/catalog/oar.yml`](../_meta/catalog/oar.yml) lists every division in
both chapters (titles from oregon.public.law, retrieved 2026-07-18) with ingestion status
— a discovery/backlog map, not verified content. Individual rule numbers within
not-yet-ingested divisions are not enumerated; propose ingestion via an intake-request
issue.
