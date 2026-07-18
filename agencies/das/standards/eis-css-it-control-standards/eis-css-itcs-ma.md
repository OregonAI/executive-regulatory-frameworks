---
id: eis-css-itcs-ma
title: "Statewide IT Control Standards — Maintenance (MA)"
doc_type: standard
citation: "Statewide Information Technology Control Standards, Maintenance (MA) family"
authority_level: standard
issuing_body: "DAS Enterprise Information Services / Cyber Security Services"
agency: das
legal_authority:
  - "ORS 276A.300"
source_url: "https://www.oregon.gov/eis/cyber-security-services/Documents/eis-css-statewide-information-technology(IT)-control-standards.pdf"
source_format: pdf
retrieved: "2026-07-17"
source_sha256: "16985315fc10c902762c51c2a13e78eaf104ac6d6c58cc96eae4cbfdcd698d2a"
snapshot_id: eis-css-itcs
effective_date: null
last_reviewed: null
source_version: "January 2024 (Level 1, Published)"
status: current
supersedes: null
content_mode: verbatim
conversion_notes: "family slice of the shared standard snapshot; stripped repeated page line 'Level N, Published PAGE N' x2"
last_verified: "2026-07-17"
verified_by: "@morficflux"
maintainer: "@morficflux"
relationships:
  implements:
    - "ors-276a.300"
  implemented_by: []
  references_external:
    - "nist-sp-800-53-r5"
  related:
    - "eis-css-itcs"
  supersedes: []
tags: ["information-security", "control-standards", "ma", "nist-800-53"]
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated summary, not the
> official text. Verify against the official source:
> <https://www.oregon.gov/eis/cyber-security-services/Documents/eis-css-statewide-information-technology(IT)-control-standards.pdf>
> (retrieved 2026-07-17).

# Maintenance (MA) — Statewide IT Control Standards family

## At a glance

The Maintenance (MA) control family of Oregon's Statewide Information
Technology Control Standards (January 2024). It defines 6 base controls (plus
enhancements, 10 entries total) that agencies must meet under DAS Policy
107-004-052 and ORS 276A.300. Control numbering and structure follow NIST SP 800-53
Rev. 5. For binding control text, consult the source PDF — this file is an inventory only.

## Full text

MAINTENANCE (MA)
MA-1 - Policy and Procedures
        Refer to the Statewide Information Security Plan for additional details on policies and procedures.
MA-2 - Controlled Maintenance
        a.   Schedule, document, and review records of maintenance, repair, and replacement on system
             components in accordance with manufacturer or vendor specifications and/or organizational
             requirements;
        b.   Approve and monitor all maintenance activities, whether performed on site or remotely and whether
             the system or system components are serviced on site or removed to another location;
        c.   Require that organization-defined personnel or roles explicitly approve the removal of the system or
             system components from organizational facilities for off-site maintenance, repair, or replacement;
        d.   Sanitize equipment to remove organization-defined information from associated media prior to
             removal from organizational facilities for off-site maintenance, repair, or replacement;
        e.   Check all potentially impacted controls to verify that the controls are still functioning properly
             following maintenance, repair, or replacement actions; and
        f.   Include organization-defined information in maintenance records.
MA-3 - Maintenance Tools
        a.   Approve, control, and monitor the use of system maintenance tools; and
        b.   Review previously approved system maintenance tools at least annually.
        MA-3(1) - Maintenance Tools | Inspect Tools
        Inspect the maintenance tools used by maintenance personnel for improper or unauthorized
        modifications.
        MA-3(2) - Maintenance Tools | Inspect Media
        Check media containing diagnostic and test programs for malicious code before the media are used in the
        system.
        MA-3(3) - Maintenance Tools | Prevent Unauthorized Removal
        Prevent the removal of maintenance equipment containing organizational information by:
        a.   Verifying that there is no organizational information contained on the equipment;
        b.   Sanitizing or destroying the equipment;
        c.   Retaining the equipment within the facility; or
        d.   Obtaining an exemption from the information owner explicitly authorizing removal of the equipment
             from the facility.
MA-4 - Non-local Maintenance
        a.   Approve and monitor all non-local maintenance and diagnostic activities performed on agency
             systems;

        b.   Allow the use of non-local maintenance and diagnostic tools, only as consistent with organizational
             policy and documented in the security plan for the system;
        c.   Employ strong identification and authentication techniques in the establishment of non-local
             maintenance and diagnostic sessions;
        d.   Maintain records of non-local maintenance and diagnostic activities; and
        e.   Terminate all sessions and network connections when non-local maintenance is completed.
MA-5 - Maintenance Personnel
        a.   Establish a process for maintenance personnel authorization and maintain a list of authorized
             maintenance organizations or personnel;
        b.   Verify that non-escorted personnel performing maintenance on the system possess the required
             access authorizations; and
        c.   Designate organizational personnel with required access authorizations and technical competence to
             supervise the maintenance activities of personnel who do not possess the required access
             authorizations.
        MA-5(1) - Maintenance Personnel | Individuals Without Appropriate Access
        The organization:
        a.   Implements procedures for the use of maintenance personnel that lack appropriate security
             clearances or are not U.S. citizens, that include the following requirements:
             1.    Maintenance personnel who do not have needed access authorizations, clearances, or formal
                   access approvals are escorted and supervised during the performance of maintenance and
                   diagnostic activities on the information system by approved organizational personnel who are
                   fully cleared, have appropriate access authorizations, and are technically qualified;
             2.    Prior to initiating maintenance or diagnostic activities by personnel who do not have needed
                   access authorizations, clearances or formal access approvals, all volatile information storage
                   components within the information system are sanitized and all nonvolatile storage media are
                   removed or physically disconnected from the system and secured; and
        b.   Develops and implements alternate security safeguards in the event an information system
             component cannot be sanitized, removed, or disconnected from the system.
MA-6 - Timely Maintenance
        Obtain maintenance support and/or spare parts in sufficient time to meet recovery time objectives of
        failure.

## Cross-references

- Rests on: [ORS 276A.300](../../../../statutes/ors-276a.300.md)
- Required by: [DAS 107-004-052](../../policies/das-107-004-052.md)
- Framework: [NIST SP 800-53 Rev. 5](../../../../external-references/nist-sp-800-53-r5.md)
- Parent document: [Statewide IT Control Standards](../eis-css-itcs.md)

## Provenance & change history

- Source: shared snapshot `_meta/snapshots/eis-css-itcs.pdf` / `.txt` · retrieved
  2026-07-17 · sha256 `16985315fc10c902762c51c2a13e78eaf104ac6d6c58cc96eae4cbfdcd698d2a`
- See this knowledge body's [CHANGELOG](../CHANGELOG.md).
