---
id: eis-css-itcs-cp
title: "Statewide IT Control Standards — Contingency Planning (CP)"
doc_type: standard
citation: "Statewide Information Technology Control Standards, Contingency Planning (CP) family"
authority_level: standard
issuing_body: "DAS Enterprise Information Services / Cyber Security Services"
agency: administrative-services-department
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
conversion_notes: "family slice of the shared standard snapshot; stripped repeated page line 'Level N, Published PAGE N' x4"
last_verified: "2026-07-17"
verified_by: "@morficflux"
maintainer: "@morficflux"
relationships:
  implements:
    - ors-276a.300
  implemented_by: []
  references_external:
    - nist-sp-800-53-r5
  related:
    - eis-css-itcs
  supersedes: []
tags: ["information-security", "control-standards", "cp", "nist-800-53"]
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated summary, not the
> official text. Verify against the official source:
> <https://www.oregon.gov/eis/cyber-security-services/Documents/eis-css-statewide-information-technology(IT)-control-standards.pdf>
> (retrieved 2026-07-17).

# Contingency Planning (CP) — Statewide IT Control Standards family

## At a glance

The Contingency Planning (CP) control family of Oregon's Statewide Information
Technology Control Standards (January 2024). It defines 9 base controls (plus
enhancements, 23 entries total) that agencies must meet under DAS Policy
107-004-052 and ORS 276A.300. Control numbering and structure follow NIST SP 800-53
Rev. 5. For binding control text, consult the source PDF — this file is an inventory only.

## Full text

CONTINGENCY PLANNING (CP)
CP-1 - Policy and Procedures
        Refer to the Statewide Information Security Plan for additional details on policies and procedures.
CP-2 - Contingency Plan
        a.   Develop a contingency plan for the system(s) that:
             1.   Identifies essential missions and business functions and associated contingency requirements;
             2.   Provides recovery objectives, restoration priorities, and metrics;
             3.   Addresses contingency roles, responsibilities assigned individuals with contact information;
             4.   Addresses maintaining essential missions and business functions despite a system disruption,
                  compromise, or failure;
             5.   Addresses eventual, full system restoration without deterioration of the controls originally
                  planned and implemented;
             6.   Addresses the sharing of contingency information; and
             7.   Is reviewed and approved by the Agency Head or equivalent;
        b.   Distribute copies of the contingency plan to key contingency personnel;
        c.   Coordinate contingency planning activities with incident handling activities;
        d.   Review the contingency plan for the system at least annually;
        e.   Update the contingency plan to address changes to the organization, system, or environment of
             operation and problems encountered during contingency plan implementation, execution, or testing;
        f.   Communicate contingency plan changes to key contingency personnel;
        g.   Incorporate lessons learned from contingency plan testing, training, or actual contingency activities
             into contingency testing and training; and
        h.   Protect the contingency plan from unauthorized modification and disclosure.
        CP-2(1) - Contingency Plan | Coordinate with Related Plans
        Coordinate contingency plan development with organizational elements responsible for related plans.
        CP-2(3) - Contingency Plan | Resume Essential Missions / Business Functions
        Plan for the resumption of all mission and business functions within time periods documented in the
        Continuity Plan of contingency plan activation.
        CP-2(8) - Contingency Plan | Identify Critical Assets
        Identify and document critical system assets supporting essential mission and business functions.
CP-3 - Contingency Training
        a.   Provide contingency training to system users consistent with their assigned contingency roles and
             responsibilities:
             1.   Within ten (10) days of assuming a contingency role or responsibility;
             2.   When required by system changes; and

             3.   At least annually thereafter; and
        b.   Review and update contingency training content at least annually and following significant events.
CP-4 - Contingency Plan Testing
        a.   Perform a functional exercise at least annually to test the contingency plan for the system to
             determine the effectiveness of the plan and the readiness to execute the plan;
        b.   Review the contingency plan test results; and
        c.   Initiate corrective actions, if needed.
        CP-4(1) - Contingency Plan Testing | Coordinate With Related Plans
        Coordinate Contingency Plan testing with organizational elements responsible for related plans.
CP-6 - Alternate Storage Site
        a.   Establish an alternate storage site, including necessary agreements to permit the storage and
             retrieval of system backup information; and
        b.   Ensure that the alternate storage site provides security controls equivalent to that of the primary site.
        CP-6(1) - Alternate Storage Site | Separation from Primary Site
        Identify an alternate storage site that is sufficiently separated from the primary storage site to reduce
        susceptibility to the same threats.
        CP-6(3) - Alternate Storage Site | Accessibility
        Identify potential accessibility problems to the alternate storage site in the event of an area-wide
        disruption or disaster and outlines explicit mitigation actions.
CP-7 - Alternate Processing Site
        a.   Establish an alternate processing site including necessary agreements to permit the transfer and
             resumption of system operations for essential missions and business functions within time-periods
             consistent with organization-defined recovery time and recovery point objectives when the primary
             processing capabilities are unavailable;
        b.   Make available at the alternate processing site, the equipment and supplies required to transfer and
             resume operations or put contracts in place to support delivery to the site within the Organization-
             defined time-period for transfer and resumption; and
        c.   Provide controls at the alternate processing site that are equivalent to those at the primary site.
        CP-7(1) - Alternate Processing Site | Separation from Primary Site
        Identify an alternate processing site that is sufficiently separated from the primary processing site to
        reduce susceptibility to the same threats.
        CP-7(2) - Alternate Processing Site | Accessibility
        Identify potential accessibility problems to the alternate processing site in the event of an area-wide
        disruption or disaster and outlines explicit mitigation actions.

        CP-7(3) - Alternate Processing Site | Priority of Service
        Develop alternate processing site agreements that contain priority-of-service provisions in accordance
        with availability requirements (including recovery time objectives).
CP-8 - Telecommunications Service
        Establish alternate telecommunications services, including necessary agreements to permit the
        resumption of system operations for essential mission and business functions within agency-defined
        recovery time and recovery point objectives when the primary telecommunications capabilities are
        unavailable at either the primary or alternate processing or storage sites.
        CP-8(1) - Telecommunications Service | Priority of Service Provisions
        a.   Develop primary and alternate telecommunications service agreements that contain priority-of-
             service provisions in accordance with organizational availability requirements (including recovery
             time objectives); and
        b.   Request Telecommunications Service Priority for all telecommunications services used for national
             security emergency preparedness if the primary and/or alternate telecommunications services are
             provided by a common carrier.
        CP-8(2) - Telecommunications Service | Single Points of Failure
        Obtain alternate telecommunications services to reduce the likelihood of sharing a single point of failure
        with primary telecommunications services.
CP-9 - System Backup
        a.   Conduct full backups of user-level information contained in the system weekly, with incremental
             daily;
        b.   Conduct full backups of system-level information contained in the system weekly, with incremental
             daily;
        c.   Conduct full backups of system documentation, including security-related documentation weekly,
             with incremental daily; and
        d.   Protect the confidentiality, integrity and availability of backup information.
        CP-9(1) - System Backup | Testing for Reliability and Integrity
        Test backup information at least annually to verify media reliability and information integrity.
        CP-9(8) - System Backup | Cryptographic Protection
        Implement cryptographic mechanisms to prevent unauthorized disclosure and modification of all backup
        files.
CP-10 - System Recovery and Reconstruction
        Provide for the recovery and reconstitution of the system to a known state within organization-defined
        time period consistent with recovery time and recovery point objectives after a disruption, compromise,
        or failure.

        CP-10(2) - System Recovery and Reconstruction | Transaction Recovery
        Implement transaction recovery for systems that are transaction-based.

## Cross-references

- Rests on: [ORS 276A.300](../../../../statutes/ors-276a.300.md)
- Required by: [DAS 107-004-052](../../policies/das-107-004-052.md)
- Framework: [NIST SP 800-53 Rev. 5](../../../../external-references/nist-sp-800-53-r5.md)
- Parent document: [Statewide IT Control Standards](../eis-css-itcs.md)

## Provenance & change history

- Source: shared snapshot `_meta/snapshots/eis-css-itcs.pdf` / `.txt` · retrieved
  2026-07-17 · sha256 `16985315fc10c902762c51c2a13e78eaf104ac6d6c58cc96eae4cbfdcd698d2a`
- See this knowledge body's [CHANGELOG](../CHANGELOG.md).
