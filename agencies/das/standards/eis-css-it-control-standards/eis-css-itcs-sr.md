---
id: eis-css-itcs-sr
title: "Statewide IT Control Standards — Supply Chain Risk Management (SR)"
doc_type: standard
citation: "Statewide Information Technology Control Standards, Supply Chain Risk Management (SR) family"
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
tags: ["information-security", "control-standards", "sr", "nist-800-53"]
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated summary, not the
> official text. Verify against the official source:
> <https://www.oregon.gov/eis/cyber-security-services/Documents/eis-css-statewide-information-technology(IT)-control-standards.pdf>
> (retrieved 2026-07-17).

# Supply Chain Risk Management (SR) — Statewide IT Control Standards family

## At a glance

The Supply Chain Risk Management (SR) control family of Oregon's Statewide Information
Technology Control Standards (January 2024). It defines 9 base controls (plus
enhancements, 12 entries total) that agencies must meet under DAS Policy
107-004-052 and ORS 276A.300. Control numbering and structure follow NIST SP 800-53
Rev. 5. For binding control text, consult the source PDF — this file is an inventory only.

## Full text

SUPPLY CHAIN RISK MANAGEMENT (SR)
SR-1 - Policy and Procedures
        Refer to the Statewide Information Security Plan for additional details on policies and procedures.
SR-2 - Supply Chain Risk Management Plan
        a.   Develop a plan for managing supply chain risks associated with the research and development,
             design, manufacturing, acquisition, delivery, integration, operations and maintenance, and disposal
             of all systems, system components, or system services under configuration management;
        b.   Review and update the Supply Chain Risk Management (SCRM) Plan every three years or as required,
             to address threat, organizational or environmental changes; and
        c.   Protect the supply chain risk management plan from unauthorized disclosure and modification.
        SR-2(1) - Supply Chain Risk Management Plan | Establish SCRM Team
        Establish a SCRM Team consisting of personnel, roles, and responsibilities as identified in the SCRM Plan
        to provide expertise in acquisition processes, legal practices, vulnerabilities, threats, and attack vectors, as
        well as an understanding of the technical aspects and dependencies of systems.
SR-3 - Supply Chain Controls and Processes
        a.   Establish a process or processes to identify and address weaknesses or deficiencies in the supply
             chain elements and processes of any system or system component, in coordination with personnel or
             roles as identified in the SCRM Plan;
        b.   Employ SCRM Controls, as defined in Enterprise policies and Statewide Information and
             Cybersecurity Standards, and applicable regulatory frameworks, to protect against supply chain risks
             to the system, system component, or system service and to limit the harm or consequences from
             supply chain- related events; and
        c.   Document the selected and implemented supply chain processes and controls in the SCRM Plan.
SR-5 - Acquisition Strategies, Tools, and Methods
        Employ acquisition strategies, contract tools, and procurement methods to protect against, identify, and
        mitigate supply chain risks as identified in the SCRM Plan.
SR-6 - Supplier Assessments and Reviews
        Assess and review the supply chain-related risks associated with suppliers or contractors and the system,
        system component, or system service they provide at least annually.
SR-8 - Notification Agreements
        Establish agreements and procedures with entities involved in the supply chain for the system, system
        component, or system service for the notification of:
        a.   Supply chain compromises;
        b.   Results of assessments or audits;

        c.   End-of-support / end-of-life;
        d.   Major changes in a maintenance organization’s structure or process (for example, physical move to a
             different location, change in ownership, outsourcing, or changes in personnel);
        e.   Successful and attempted threat events that may affect Enterprise systems;
        f.   Available protective or mitigating measures to address identified vulnerabilities; and
        g.   Any system, service, or component-specific information that affects maintenance or continuity plans.
SR-10 - Inspection of Systems or Components
        Inspect all systems or system components under configuration control upon receipt and before
        reassignment; and whenever indicators of compromised are reported to detect tampering.
SR-11 - Component Authenticity
        a.   Develop and implement anti-counterfeit policy and procedures that include the means to detect and
             prevent counterfeit components from entering the system; and
        b.   Report counterfeit system components to approved external reporting organizations; personnel or
             roles as identified in the SCRM Plan.
        SR-11(1) - Component Authenticity | Anti-Counterfeit Training
        Train personnel or roles as defined in the SCRM Plan to detect counterfeit system components (including
        hardware, software, and firmware).
        SR-11(2) - Component Authenticity | Configuration Control for Component Service and Repair
        Maintain configuration control over all system components awaiting service or repair and serviced or
        repaired components awaiting return to service.
SR-12 - Component Disposal
        Dispose of system components using the following techniques and methods:
        a.   Sanitize all components prior to disposal in accordance with MP-6;
        b.   Securely dispose of or destroy all components subject to configuration management; and
        c.   Document all disposals in component inventories.

## Cross-references

- Rests on: [ORS 276A.300](../../../../statutes/ors-276a.300.md)
- Required by: [DAS 107-004-052](../../policies/das-107-004-052.md)
- Framework: [NIST SP 800-53 Rev. 5](../../../../external-references/nist-sp-800-53-r5.md)
- Parent document: [Statewide IT Control Standards](../eis-css-itcs.md)

## Provenance & change history

- Source: shared snapshot `_meta/snapshots/eis-css-itcs.pdf` / `.txt` · retrieved
  2026-07-17 · sha256 `16985315fc10c902762c51c2a13e78eaf104ac6d6c58cc96eae4cbfdcd698d2a`
- See this knowledge body's [CHANGELOG](../CHANGELOG.md).
