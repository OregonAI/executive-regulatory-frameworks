# Department of Environmental Quality — policies — index

Policies (`doc_type: policy`) issued by Department of Environmental Quality
(`agency: department-of-environmental-quality`). **Non-authoritative copies** — see [AGENTS.md](../../../AGENTS.md).

Listing of record: a SharePoint **list** (not a document library) at
`/deq/Get-Involved/Lists/Internal Management Directives`, found via the anonymous
`_api/web/lists` enumeration endpoint (the page itself is JS-rendered and gave no static
links). Each item's `Directive` field points to an external records-management viewer
(`ormswd2.synergydcs.com/ORMSCMSearchDEQ`) rather than a downloadable PDF — the viewer embeds
the full document inline as base64 for client-side pdf.js rendering, which is how the
verbatim text was recovered (see `_fetch_synergy_pdf` / `_discover_deq_imd` in
`src/ingest_policies.py`). Manifest:
[`_meta/sources/department-of-environmental-quality-policies.yml`](../../../_meta/sources/department-of-environmental-quality-policies.yml).

| Division | Ingested |
|---|---|
| Water Quality | 26 |
| Air Quality | 13 |
| Land Quality | 9 |
| Cross-Agency | 4 |
| **all** | **52** |

Of 73 items on the list (72 distinct — one item duplicates another's target document), **19
are image-only PDFs with no extractable text layer** (left out per HC-1 — never OCR; flagged
for future human review) and **one** links to a differently-shaped page
(`SearchDetail.aspx`, not `RecordViewer.aspx`) that has no embedded document at all —
deferred, not a text-extraction failure. IMD PDFs have no consistent structured date field
across 2001–2026, so `effective_date` is `null` throughout; `source_version` instead carries
the list's own `Year_x0020_Issued` field, explicitly labeled as coming from the listing, not
the document's own text.
