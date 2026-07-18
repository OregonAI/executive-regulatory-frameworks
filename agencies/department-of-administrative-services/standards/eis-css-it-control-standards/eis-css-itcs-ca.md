---
id: eis-css-itcs-ca
title: "Statewide IT Control Standards — Assessment, Authorization, and Monitoring (CA)"
doc_type: standard
citation: "Statewide Information Technology Control Standards, Assessment, Authorization, and Monitoring (CA) family"
authority_level: standard
issuing_body: "DAS Enterprise Information Services / Cyber Security Services"
agency: department-of-administrative-services
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
tags: ["information-security", "control-standards", "ca", "nist-800-53"]
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated summary, not the
> official text. Verify against the official source:
> <https://www.oregon.gov/eis/cyber-security-services/Documents/eis-css-statewide-information-technology(IT)-control-standards.pdf>
> (retrieved 2026-07-17).

# Assessment, Authorization, and Monitoring (CA) — Statewide IT Control Standards family

## At a glance

The Assessment, Authorization, and Monitoring (CA) control family of Oregon's Statewide Information
Technology Control Standards (January 2024). It defines 8 base controls (plus
enhancements, 14 entries total) that agencies must meet under DAS Policy
107-004-052 and ORS 276A.300. Control numbering and structure follow NIST SP 800-53
Rev. 5. For binding control text, consult the source PDF — this file is an inventory only.

## Full text

ASSESSMENT, AUTHORIZATION, AND MONITORING (CA)
CA-1 - Policy and Procedures
        Refer to the Statewide Information Security Plan for additional details on policies and procedures.
CA-2 - Security Assessments
        a.   Select the appropriate assessor or assessment team for the type of assessment to be conducted;
        b.   Develop a control assessment plan that describes the scope of the assessment including:
             1.    Controls and control enhancements under assessment;
             2.    Assessment procedures to be used to determine control effectiveness; and
             3.    Assessment environment, assessment team, and assessment roles and responsibilities;
        c.   Ensure the control assessment plan is reviewed and approved by the Authorizing Official (AO) or
             designated representative prior to conducting the assessment;
        d.   Assess the controls in the system and its environment of operation at least annually, or when there is
             a significant change to the system, to determine the extent to which the controls are implemented
             correctly, operating as intended, and producing the desired outcome with respect to meeting
             established security requirements;
        e.   Produce a control assessment report that document the results of the assessment; and
        f.   Provide the results of the control assessment to AO and other parties as described in the Oregon
             Statewide Information Security Plan.
        CA-2(1) - Control Assessments | Independent Assessors
        Employ independent assessors or assessment teams to conduct control assessment.
        CA-2(3) - Control Assessments | Leveraging Results from External Organizations
        Leverage the results of control assessments performed by external organizations.
CA-3 - System Interconnections
        a.   Approve and manage the exchange of information between the system and other systems by means
             of formal agreements (e.g., interconnection security agreements, information exchange security
             agreements, memoranda of understanding or agreement, service level agreements, user agreements,
             or nondisclosure agreements);
        b.   Document, as part of each exchange agreement, the interface characteristics, security requirements,
             controls, and responsibilities for each system, and the impact level of the information communicated;
             and
        c.   Review and update the agreements annually.
CA-5 - Plan of Action and Milestones
        a.   Develop a plan of action and milestones for the system to document the planned remediation actions
             of the Organization to correct weaknesses or deficiencies noted during the assessment of the
             controls and to reduce or eliminate known vulnerabilities in the system; and

        b.   Update existing plan of action and milestones at least monthly based on the findings from control
             assessments, independent audits or reviews, and continuous monitoring activities.
CA-6 - Authorization
        a.   Assign a senior official as the AO for the system;
        b.   Assign a senior official as the AO for common controls available for inheritance by organizational
             systems;
        c.   Ensure that the AO for the system, before commencing operations:
             1.   Accepts the use of common controls inherited by the system; and
             2.   Authorizes the system to operate;
        d.   Ensure that the Authorizing Official for common controls authorizes the use of those controls for
             inheritance by organizational systems; and
        e.   Update the authorizations at least every three (3) years or when a significant change occurs.
CA-7 - Continuous Monitoring
        Develop a system-level continuous monitoring strategy and implement continuous monitoring in
        accordance with the Organization-level continuous monitoring strategy that includes:
        a.   Establishing the system-level metrics to be monitored and documented in the applicable SSP;
        b.   Establishing organization-defined frequencies (no less than annually) for monitoring and
             organization-defined frequencies (no less than annually) for assessment of control effectiveness;
        c.   Ongoing control assessments in accordance with the continuous monitoring strategy;
        d.   Ongoing monitoring of system and organization-defined metrics in accordance with the continuous
             monitoring strategy;
        e.   Correlation and analysis of information generated by control assessments and monitoring;
        f.   Response actions to address results of the analysis of control assessment and monitoring
             information; and
        g.   Reporting the security status of the system to the Agency Director, or designee thereof, at least
             annually.
        CA-7(1) - Continuous Monitoring | Independent Assessors
        Employ independent assessors or assessment teams to monitor the controls in the system on an ongoing
        basis.
        CA-7(4) - Continuous Monitoring | Risk Monitoring
        Ensure risk monitoring is an integral part of the continuous monitoring strategy that includes the
        following:
        a.   Effectiveness monitoring;
        b.   Compliance monitoring; and
        c.   Change monitoring.

CA-8 - Penetration Testing
        Conduct penetration testing at least annually.
        CA-8(1) - Penetration Testing | Independent Penetration Testing Agent or Team
        Employ an independent penetration testing agent or team to perform penetration testing on the system
        or system components.
        CA-8(2) - Penetration Testing | Red Team Exercises
        Employ red-team exercises to simulate attempts by adversaries to compromise organizational systems in
        accordance with applicable rules of engagement.
CA-9 - Internal System Connections
        a.   Authorize internal connections of intra-system components to the system;
        b.   Document, for each internal connection, the interface characteristics, security requirements, and the
             nature of the information communicated;
        c.   Terminate internal system connections according to the session limit standards as specified under AC-
             12 and SC-10; and
        d.   Review annually the continued need for each internal connection.

## Cross-references

- Rests on: [ORS 276A.300](../../../../statutes/ors-276a.300.md)
- Required by: [DAS 107-004-052](../../policies/das-107-004-052.md)
- Framework: [NIST SP 800-53 Rev. 5](../../../../external-references/nist-sp-800-53-r5.md)
- Parent document: [Statewide IT Control Standards](../eis-css-itcs.md)

## Provenance & change history

- Source: shared snapshot `_meta/snapshots/eis-css-itcs.pdf` / `.txt` · retrieved
  2026-07-17 · sha256 `16985315fc10c902762c51c2a13e78eaf104ac6d6c58cc96eae4cbfdcd698d2a`
- See this knowledge body's [CHANGELOG](../CHANGELOG.md).
