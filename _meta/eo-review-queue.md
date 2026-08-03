# Executive-order OCR review queue (#77)

The operator's human-read queue: the **25** executive orders whose `## Full text` was
recovered by the two-engine fallback OCR pass (`src/ocr_fallback_eo.py`) and has
**never been read by a human against its source PDF**. Each carries `NOT
human-verified` in its `conversion_notes`; evidence figures below are copied from
`_meta/catalog/eo.yml`'s `text_layer` strings.

**How to work the queue:** rows are ordered by cross-engine agreement, weakest OCR
first. In every document, read the **signature block, personal names, and dates
FIRST** — they are the least reliable OCR output and exactly what a citation
depends on (issue #77). A `signed date` of `null` below means the signed-date
parser found nothing machine-readable: that date must be transcribed by a human or
stay null. When a document passes review, correct any misreads, then record the
verification with corpus-verify (corpus-toolkit >= v1.22.0) and promote
`text_layer` per AGENTS.md's two-engine rule; regenerate this queue's source
catalog entry accordingly.

| # | order | committed doc | source PDF | words | agreement | dictionary | signed date parsed | priority note |
|---|-------|---------------|------------|------:|----------:|-----------:|--------------------|---------------|
| 1 | eo-05-09 | [eo-05-09.md](../executive-orders/eo-05-09.md) | [PDF](https://www.oregon.gov/gov/eo/EO0509.pdf) | 196 | 87% | 92% | 2005-09-05 | weakest agreement in the queue — treat every figure and name as suspect |
| 2 | eo-03-08 | [eo-03-08.md](../executive-orders/eo-03-08.md) | [PDF](https://www.oregon.gov/gov/eo/eo-03-08.pdf) | 75 | 88% | 91% | null | signed date unparsed — transcribe from the PDF; short doc, minutes to verify |
| 3 | eo-08-25 | [eo-08-25.md](../executive-orders/eo-08-25.md) | [PDF](https://www.oregon.gov/gov/eo/eo-08-25.pdf) | 92 | 88% | 92% | null | signed date unparsed; amends EO 06-14 — verify the cross-reference number |
| 4 | eo-06-10 | [eo-06-10.md](../executive-orders/eo-06-10.md) | [PDF](https://www.oregon.gov/gov/eo/eo0610.pdf) | 269 | 89% | 93% | 2006-07-21 | emergency declaration — dates and place names are load-bearing |
| 5 | eo-19-07 | [eo-19-07.md](../executive-orders/eo-19-07.md) | [PDF](https://www.oregon.gov/gov/eo/eo_19_07.pdf) | 78 | 91% | 90% | null | signed date unparsed; amends EO 19-03 — verify the cross-reference number |
| 6 | eo-16-01 | [eo-16-01.md](../executive-orders/eo-16-01.md) | [PDF](https://www.oregon.gov/gov/eo/eo_16-01.pdf) | 83 | 92% | 90% | 2016-01-25 | amends EO 99-09 — verify cross-reference + signature block |
| 7 | eo-25-31 | [eo-25-31.md](../executive-orders/eo-25-31.md) | [PDF](https://www.oregon.gov/gov/eo/eo-25-31.pdf) | 97 | 92% | 90% | 2025-12-09 | rescinds EO 25-30 — a wrong digit here changes which order died |
| 8 | eo-06-09 | [eo-06-09.md](../executive-orders/eo-06-09.md) | [PDF](https://www.oregon.gov/gov/eo/eo0609.pdf) | 319 | 93% | 94% | null | signed date unparsed — transcribe from the PDF |
| 9 | eo-07-18 | [eo-07-18.md](../executive-orders/eo-07-18.md) | [PDF](https://www.oregon.gov/gov/eo/eo-07-18.pdf) | 259 | 93% | 94% | null | drought emergency — signed date unparsed AND county names load-bearing |
| 10 | eo-07-26-a | [eo-07-26-a.md](../executive-orders/eo-07-26-a.md) | [PDF](https://www.oregon.gov/gov/eo/eo-07-26-a.pdf) | 85 | 93% | 91% | 2007-12-18 | amends EO 07-21 — verify the cross-reference number |
| 11 | eo-12-04 | [eo-12-04.md](../executive-orders/eo-12-04.md) | [PDF](https://www.oregon.gov/gov/eo/eo-12-04.pdf) | 76 | 93% | 96% | 2012-02-24 | amends EO 99-09 — verify cross-reference + signature block |
| 12 | eo-17-10 | [eo-17-10.md](../executive-orders/eo-17-10.md) | [PDF](https://www.oregon.gov/gov/eo/eo_17-10.pdf) | 78 | 93% | 94% | null | signed date unparsed; amends EO 17-09 — verify the cross-reference number |
| 13 | eo-06-12 | [eo-06-12.md](../executive-orders/eo-06-12.md) | [PDF](https://www.oregon.gov/gov/eo/eo0612.pdf) | 246 | 94% | 93% | 2006-07-28 | conflagration invocation — fire/place names and dates first |
| 14 | eo-07-19 | [eo-07-19.md](../executive-orders/eo-07-19.md) | [PDF](https://www.oregon.gov/gov/eo/eo-07-19.pdf) | 214 | 94% | 95% | null | signed date unparsed — transcribe from the PDF |
| 15 | eo-06-04 | [eo-06-04.md](../executive-orders/eo-06-04.md) | [PDF](https://www.oregon.gov/gov/eo/eo0604.pdf) | 847 | 95% | 97% | null | signed date unparsed; longest doc in queue — budget the reading time |
| 16 | eo-06-11 | [eo-06-11.md](../executive-orders/eo-06-11.md) | [PDF](https://www.oregon.gov/gov/eo/eo0611.pdf) | 259 | 95% | 92% | 2006-07-23 | conflagration invocation — fire/place names and dates first |
| 17 | eo-06-13 | [eo-06-13.md](../executive-orders/eo-06-13.md) | [PDF](https://www.oregon.gov/gov/eo/eo0613.pdf) | 488 | 95% | 96% | null | signed date unparsed; task-force membership = list of names to verify |
| 18 | eo-06-15 | [eo-06-15.md](../executive-orders/eo-06-15.md) | [PDF](https://www.oregon.gov/gov/eo/eo0615.pdf) | 282 | 95% | 93% | 2006-11-07 | emergency declaration — dates and place names are load-bearing |
| 19 | eo-05-08 | [eo-05-08.md](../executive-orders/eo-05-08.md) | [PDF](https://www.oregon.gov/gov/eo/EO0508.pdf) | 257 | 96% | 93% | 2005-08-29 | conflagration invocation — fire/place names and dates first |
| 20 | eo-08-13 | [eo-08-13.md](../executive-orders/eo-08-13.md) | [PDF](https://www.oregon.gov/gov/eo/eo-08-13.pdf) | 87 | 96% | 97% | null | signed date unparsed; amends EO 08-03 — verify the cross-reference number |
| 21 | eo-06-03 | [eo-06-03.md](../executive-orders/eo-06-03.md) | [PDF](https://www.oregon.gov/gov/eo/eo0603.pdf) | 689 | 97% | 92% | 2006-02-09 | task-force membership = list of names to verify |
| 22 | eo-06-05 | [eo-06-05.md](../executive-orders/eo-06-05.md) | [PDF](https://www.oregon.gov/gov/eo/eo-06-05.pdf) | 972 | 97% | 94% | 2006-04-04 | longest doc after eo-06-04; council membership names |
| 23 | eo-06-14 | [eo-06-14.md](../executive-orders/eo-06-14.md) | [PDF](https://www.oregon.gov/gov/eo/eo-06-14.pdf) | 607 | 97% | 94% | 2006-10-09 | task-force membership = list of names to verify |
| 24 | eo-07-01 | [eo-07-01.md](../executive-orders/eo-07-01.md) | [PDF](https://www.oregon.gov/gov/eo/eo-07-01.pdf) | 662 | 97% | 96% | 2007-01-19 | task-force membership = list of names to verify |
| 25 | eo-07-06 | [eo-07-06.md](../executive-orders/eo-07-06.md) | [PDF](https://www.oregon.gov/gov/eo/eo-07-06.pdf) | 76 | 97% | 97% | 2007-05-25 | strongest agreement in queue — likely a fast confirm; check signature block |

Context (measured 2026-08-02, this branch): 526 catalogued orders — 20 `clean`,
479 `ocr-recovered` (primary-engine text, also never human-verified — the larger,
lower-risk backlog behind this queue), 25 `fallback-ocr` (this queue), 2 stubs with
no text at all (`eo-12-09`, `eo-16-15` — correctly left as stubs; see #77).
