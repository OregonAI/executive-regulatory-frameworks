---
id: eis-css-itcs-au
title: "Statewide IT Control Standards — Audit and Accountability (AU)"
doc_type: standard
citation: "Statewide Information Technology Control Standards, Audit and Accountability (AU) family"
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
conversion_notes: "family slice of the shared standard snapshot; stripped repeated page line 'Level N, Published PAGE N' x3"
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
tags: ["information-security", "control-standards", "au", "nist-800-53"]
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated summary, not the
> official text. Verify against the official source:
> <https://www.oregon.gov/eis/cyber-security-services/Documents/eis-css-statewide-information-technology(IT)-control-standards.pdf>
> (retrieved 2026-07-17).

# Audit and Accountability (AU) — Statewide IT Control Standards family

## At a glance

The Audit and Accountability (AU) control family of Oregon's Statewide Information
Technology Control Standards (January 2024). It defines 11 base controls (plus
enhancements, 16 entries total) that agencies must meet under DAS Policy
107-004-052 and ORS 276A.300. Control numbering and structure follow NIST SP 800-53
Rev. 5. For binding control text, consult the source PDF — this file is an inventory only.

## Full text

AUDIT AND ACCOUNTABILITY – AU
AU-1 - Policy and Procedures
        Refer to the Statewide Information Security Plan for additional details on policies and procedures.
AU-2 - Events Logging
        a.   Identify the types of events that systems are capable of logging in support of the audit function that,
             at a minimum, includes:
             1.   For on-premises applications:
                  i)    successful and unsuccessful account logon events;
                  ii)   account management events;
                  iii) object access;
                  iv) policy change;
                  v)    privilege functions;
                  vi) process tracking; and
                  vii) system events.
             2.   For Web applications:
                  i)    all administrator activity;
                  ii)   authentication checks;
                  iii) authorization checks;
                  iv) data deletions;
                  v)    data access;
                  vi) data changes; and
                  vii) permission changes;
        b.   Coordinate the event logging function with other organizational entities requiring audit-related
             information to guide and inform the selection criteria for events to be logged;
        c.   Specify the event types for logging within the system consisting of a subset of the event types defined
             in AU-2 (a), along with the frequency of (or situation requiring) logging for each identified event type;
        d.   Provide a rationale for why the event types selected for logging are deemed to be adequate to
             support after-the-fact investigations of incidents; and
        e.   Review and update the event types selected for logging at least annually, or when a major change to
             the system occurs.
AU-3 - Content of Audit Records
        Ensure that audit records contain information that establishes the following:
        a.   What type of event occurred;
        b.   When the event occurred;
        c.   Where the event occurred;

        d.   Source of the event;
        e.   Outcome of the event; and
        f.   Identity of any individuals, subjects, or objects/entities associated with the event.
        AU-3(1) - Content of Audit Records | Additional Audit Information
        Generate audit records containing the information necessary to facilitate the reconstruction of events in
        the event (or suspected event) of unauthorized activity or malfunction.
AU-4 - Audit Storage Capacity
        Allocate audit log storage capacity to accommodate State of Oregon records retention schedules and any
        other applicable retention requirements.
AU-5 - Response to Audit Processing Failures
        a.   Alert agency designated personnel or roles when the event of an audit logging process failure; and
        b.   Overwrite oldest record(s).
AU-6 - Audit Review, Analysis, and Reporting
        a.   Review and analyze system audit records at least weekly for indications of inappropriate or unusual
             activity;
        b.   Report findings to appropriate organization according to agency, State of Oregon, and Federal
             Incident Response Policy and procedures; and
        c.   Adjust the level of audit record review, analysis, and reporting within the system when there is a
             change in risk based on law enforcement information, intelligence information, or other credible
             sources of information.
        AU-6(1) - Audit Review, Analysis, and Reporting | Process Integration
        Integrate audit record review, analysis, and reporting processes.
        AU-6(3) - Audit Review, Analysis, and Reporting | Correlate Audit Repositories
        Analyze and correlate audit records across different repositories to gain organization-wide situational
        awareness.
AU-7 - Audit Reduction and Report Generation
        Provide and implement an audit reduction and report generation capability that:
        a.   Supports on-demand audit record review, analysis, and reporting requirements and after-the-fact
             investigations of incidents; and
        b.   Does not alter the original content or time ordering of audit records.
        AU-7(1) - Audit Reduction and Report Generation | Automatic Processing
        Provide and implement the capability to process, sort, and search audit records for events of interest
        based on individual items, or combinations of items contained in the audit records, as defined in AU-3.
AU-8 - Time Stamps
        a.   Use internal system clocks to generate time stamps for audit records; and

        b.   Record time stamps for audit records that meet organization-defined granularity of time
             measurement; and that use Coordinated Universal Time, have a fixed local time offset from
             Coordinated Universal Time, or that include the local time offset as part of the time stamp.
AU-9 - Protection of Audit Information
        a.   Protect audit information and audit logging tools from unauthorized access, modification, and
             deletion; and
        b.   Alert the Organization assigned personnel upon detection of unauthorized access, modification, or
             deletion of audit information.
        AU-9(4) - Protection of Audit Information | Access by Subset of Privileged Users
        Authorize access to management of audit logging functionality to only personnel that have a need to
        know and have been expressly authorized for this function.
AU-11 - Audit Record Retention
        Retain audit records for at least ninety (90) days to provide support for after-the-fact investigations of
        incidents and to meet regulatory and organizational information retention requirements.
AU-12 - Audit Record Generation
        a.   Provide audit record generation capability for the event types the system is capable of auditing as
             defined in AU-2a on all information system and network components where audit capability is
             deployed/available;
        b.   Allow agency system owners, agency information owners, or system security administrators to select
             the event types that are to be logged by specific components of the system; and
        c.   Generate audit records for the event types defined in AU-2 that include the audit record content
             defined in AU-3.

## Cross-references

- Rests on: [ORS 276A.300](../../../../statutes/ors-276a.300.md)
- Required by: [DAS 107-004-052](../../policies/das-107-004-052.md)
- Framework: [NIST SP 800-53 Rev. 5](../../../../external-references/nist-sp-800-53-r5.md)
- Parent document: [Statewide IT Control Standards](../eis-css-itcs.md)

## Provenance & change history

- Source: shared snapshot `_meta/snapshots/eis-css-itcs.pdf` / `.txt` · retrieved
  2026-07-17 · sha256 `16985315fc10c902762c51c2a13e78eaf104ac6d6c58cc96eae4cbfdcd698d2a`
- See this knowledge body's [CHANGELOG](../CHANGELOG.md).
