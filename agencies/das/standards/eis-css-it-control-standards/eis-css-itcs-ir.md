---
id: eis-css-itcs-ir
title: "Statewide IT Control Standards — Incident Response (IR)"
doc_type: standard
citation: "Statewide Information Technology Control Standards, Incident Response (IR) family"
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
conversion_notes: "family slice of the shared standard snapshot; stripped repeated page line 'Level N, Published PAGE N' x3"
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
tags: ["information-security", "control-standards", "ir", "nist-800-53"]
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated summary, not the
> official text. Verify against the official source:
> <https://www.oregon.gov/eis/cyber-security-services/Documents/eis-css-statewide-information-technology(IT)-control-standards.pdf>
> (retrieved 2026-07-17).

# Incident Response (IR) — Statewide IT Control Standards family

## At a glance

The Incident Response (IR) control family of Oregon's Statewide Information
Technology Control Standards (January 2024). It defines 9 base controls (plus
enhancements, 17 entries total) that agencies must meet under DAS Policy
107-004-052 and ORS 276A.300. Control numbering and structure follow NIST SP 800-53
Rev. 5. For binding control text, consult the source PDF — this file is an inventory only.

## Full text

INCIDENT RESPONSE – IR
IR-1 - Policy and Procedures
        Refer to the Statewide Information Security Plan for additional details on policies and procedures.
IR-2 - Incident Response Training
        a.   Provide incident response training to system users consistent with assigned roles and responsibilities:
             1.   Within ten (10) days of assuming an incident response role or responsibility or acquiring system
                  access;
             2.   When required by system changes; and
             3.   At least annually thereafter; and
        b.   Review and update incident response training content at least annually and following significant
             events.
IR-3 - Incident Response Testing
        Perform functional testing of the effectiveness of the incident response capability for the system at least
        annually.
        IR-3(2) - Incident Response Testing | Coordination With Related Plans
        Coordinate incident response testing with organizational elements responsible for related plans.
IR-4 - Incident Handling
        a.   Implement an incident handling capability for incidents that is consistent with the incident response
             plan and includes preparation, detection and analysis, containment, eradication, and recovery;
        b.   Coordinate incident handling activities with contingency planning activities;
        c.   Incorporate “lessons learned” from ongoing incident-handling activities into incident response
             procedures, training, testing, and implement the resulting changes accordingly; and
        d.   Ensure the rigor, intensity, scope, and results of incident handling activities are comparable and
             predictable across the Organization.
        IR-4(1) - Incident Handling | Automated Incident Handling Processes
        Support the incident handling process using automated mechanisms to support the incident handling
        processes.
IR-5 - Incident Monitoring
        Track and document incidents.
IR-6 - Incident Reporting
        a.   Require personnel to report suspected incidents to the organizational incident response capability as
             soon as possible, but in no case later than one (1) hour following discovery; and
        b.   Report incident information to internal agency incident response resources.

        IR-6(1) - Incident Reporting | Automated Reporting
        Report incidents using organization-defined process.
        IR-6(3) - Supply Chain Coordination
        Provide security incident information to the provider of the product or service and other organizations
        involved in the supply chain or supply chain governance for systems or system components related to the
        incident.
IR-7 - Incident Response Assistance
        Provide an incident response support resource, integral to the organizational incident response capability,
        that offers advice and assistance to users of the system for the handling and reporting of incidents.
        IR-7(1) - Incident Response Assistance | Automation Support for Availability of Information and
        Support
        Increase the availability of incident response information and support using automated mechanisms to
        support the incident handling processes.
IR-8 - Incident Response Plan
        a.   Develop an Incident Response Plan that:
             1.     Provides agencies with a roadmap for implementing an incident response capability;
             2.     Describes the structure and organization of the incident response capability;
             3.     Provides a high-level approach for how the incident response capability fits into the overall
                    organization;
             4.     Meets the unique requirements of the Organization, which relate to mission, size, structure, and
                    functions;
             5.     Defines reportable incidents;
             6.     Provides metrics for measuring the incident response capability within the Organization;
             7.     Defines the resources and management support needed to effectively maintain and mature an
                    incident response capability;
             8.     Addresses the sharing of incident information;
             9.     Is reviewed and approved by agency senior leadership, and applicable Incident Response Team
                    (IRT) leaders and personnel annually; and
             10. Explicitly designates responsibility for incident response to agency senior leadership, and
                    applicable IRT leaders and personnel.
        b.   Distribute copies of the incident response plan to agency senior leadership, and applicable IRT leaders
             and personnel;
        c.   Update the incident response plan to address system and organizational changes or problems
             encountered during plan implementation, execution, or testing;

        d.   Communicate incident response plan changes to agency senior leadership, and applicable IRT leaders
             and personnel; and
        e.   Protect the incident response plan from unauthorized disclosure and modification.
IR-9 - Information Spillage Response
        Respond to information spills by:
        a.   Assigning organization-defined personnel or roles with responsibility for responding to information
             spills;
        b.   Identifying the specific information involved in the system contamination;
        c.   Alerting organization-defined personnel or roles of the information spill using a method of
             communication not associated with the spill;
        d.   Isolating the contaminated system or system component;
        e.   Eradicating the information from the contaminated system or component;
        f.   Identifying other systems or system components that may have been subsequently contaminated;
             and
        g.   Reporting incident information in accordance with the Incident Response Plan.
        IR-9(2) - Information Spillage Response | Training
        Provide information spillage response training at least annually.
        IR-9(3) - Information Spillage Response | Post-spill Operations
        Implement procedures to ensure that organizational personnel impacted by information spills can
        continue to carry out assigned tasks while contaminated systems are undergoing corrective actions.
        IR-9(4) - Information Spillage Response | Exposure to Unauthorized Personnel
        Employ controls for personnel exposed to information not within assigned access authorizations.

## Cross-references

- Rests on: [ORS 276A.300](../../../../statutes/ors-276a.300.md)
- Required by: [DAS 107-004-052](../../policies/das-107-004-052.md)
- Framework: [NIST SP 800-53 Rev. 5](../../../../external-references/nist-sp-800-53-r5.md)
- Parent document: [Statewide IT Control Standards](../eis-css-itcs.md)

## Provenance & change history

- Source: shared snapshot `_meta/snapshots/eis-css-itcs.pdf` / `.txt` · retrieved
  2026-07-17 · sha256 `16985315fc10c902762c51c2a13e78eaf104ac6d6c58cc96eae4cbfdcd698d2a`
- See this knowledge body's [CHANGELOG](../CHANGELOG.md).
