---
id: eis-css-itcs-sa
title: "Statewide IT Control Standards — System and Services Acquisition (SA)"
doc_type: standard
citation: "Statewide Information Technology Control Standards, System and Services Acquisition (SA) family"
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
conversion_notes: "family slice of the shared standard snapshot; stripped repeated page line 'Level N, Published PAGE N' x5"
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
tags: ["information-security", "control-standards", "sa", "nist-800-53"]
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated summary, not the
> official text. Verify against the official source:
> <https://www.oregon.gov/eis/cyber-security-services/Documents/eis-css-statewide-information-technology(IT)-control-standards.pdf>
> (retrieved 2026-07-17).

# System and Services Acquisition (SA) — Statewide IT Control Standards family

## At a glance

The System and Services Acquisition (SA) control family of Oregon's Statewide Information
Technology Control Standards (January 2024). It defines 11 base controls (plus
enhancements, 20 entries total) that agencies must meet under DAS Policy
107-004-052 and ORS 276A.300. Control numbering and structure follow NIST SP 800-53
Rev. 5. For binding control text, consult the source PDF — this file is an inventory only.

## Full text

SYSTEM AND SERVICES ACQUISITION (SA)
SA-1 - Policy and Procedures
        Refer to the Statewide Information Security Plan for additional details on policies and procedures.
SA-2 - Allocation of Resources
        a.   Determine the high-level information security requirements for the system or system service in
             mission and business process planning;
        b.   Determine, document, and allocate the resources required to protect the system or system service as
             part of the organizational capital planning and investment control process; and
        c.   Establish a discrete line item for information security in organizational program and budgeting
             documentation.
SA-3 - System Development Life Cycle (SDLC)
        a.   Acquire, develop, and manage the system using a SDLC methodology that includes information
             security considerations that incorporates information security considerations;
        b.   Define and document information security roles and responsibilities throughout the SDLC;
        c.   Identify individuals having information security roles and responsibilities; and
        d.   Integrate the organizational information security risk management process into SDLC activities.
SA-4 - Acquisition Process
        Include the following requirements, descriptions, and criteria, explicitly or by reference, using State
        defined standardized contract language in the acquisition contract for the system, system component, or
        system service:
        a.   Security functional requirements;
        b.   Strength of mechanism requirements;
        c.   Security assurance requirements;
        d.   Controls needed to satisfy the security requirements;
        e.   Security documentation requirements;
        f.   Requirements for protecting security documentation;
        g.   Description of the system development environment and environment in which the system is
             intended to operate;
        h.   Allocation of responsibility or identification of parties responsible for information security and supply
             chain risk management; and
        i.   Acceptance criteria.
        SA-4(1) - Acquisition Process | Functional Properties of Controls
        Require the developer of the system, system component, or system service to provide a description of the
        functional properties of the controls to be implemented.

        SA-4(2) - Acquisition Process | Design and Implementation Information for Controls
        Require the developer of the system, system component, or system service to provide design and
        implementation information for the controls that includes at a minimum to include security-relevant
        external system interfaces; high-level design; low-level design; source code or network and data flow
        diagram.
        SA-4(9) - Acquisition Process | Functions, Ports, Protocols and Services in Use
        Require developers of systems, system components, system component, or system service to identify the
        functions, ports, protocols, and services intended for organizational use.
        SA-4 (10) - Acquisition Process | Use of Approved PIV Products
        Employ only information technology products on the FIPS 201-approved products list for PIV capability
        implemented within organizational systems for Federal systems where applicable.
SA-5 - System Documentation
        a.   Obtain or develop administrator documentation for the system, system component, or system
             service that describes:
             1.    Secure configuration, installation, and operation of the system, component, or service;
             2.    Effective use and maintenance of security functions and mechanisms; and
             3.    Known vulnerabilities regarding configuration and use of administrative or privileged functions;
        b.   Obtain or develop user documentation for the system, system component, or system service that
             describes:
             1.    User-accessible security functions and mechanisms and how to effectively use those functions
                   and mechanisms;
             2.    Methods for user interaction, which enable individuals to use the system, component, or service
                   in a more secure manner; and
             3.    User responsibilities in maintaining the security of the system, component, or service;
        c.   Document attempts to obtain system, system component, or system service documentation when
             such documentation is either unavailable or nonexistent and recreate selected system
             documentation if such documentation is essential to the effective implementation and/or operation
             of security controls; and
        d.   Distribute documentation to appropriate agency personnel.
SA-8 - Security Engineering Principles
        Apply systems security engineering principles in the specification, design, development, implementation,
        and modification of the system and system components.
SA-9 - External System Services
        a.   Require that providers of external system services comply with organizational security requirements
             and employ appropriate security controls as defined by State of Oregon Security Standards;

        b.   Define and document organizational oversight and user roles and responsibilities with regard to
             external system services; and
        c.   Employ organization-defined processes, methods, and techniques to monitor control compliance by
             external service providers on an ongoing basis.
        SA-9(1) - External System Services | Risk Assessments and Organizational Approvals
        a.   Conduct an organizational assessment of risk prior to the acquisition or outsourcing of information
             security services; and
        b.   Verify that the acquisition or outsourcing of dedicated information security services is approved by
             organization-defined personnel or roles.
        SA-9(2) - External System Services | Identification of Functions, Ports, Protocols, and Services
        Require providers of all external systems where State information is processed or stored to identify the
        functions, ports, protocols, and other services required for the use of such service.
        SA-9(5) - External System Services | Processing, Storage, and Service Location
        Restrict the location of information processing, information or data, and system services to organization-
        defined locations based on organization-defined requirements or conditions.
SA-10 - Developer Configuration Management
        Require the developer of the system, system component, or system service to:
        a.   Perform configuration management during system, component, or service development,
             implementation, and operation;
        b.   Document, manage, and control the integrity of changes to the SDLC, including: design; development;
             system test; unit acceptance test; implementation; operation; and disposal;
        c.   Implement only organization-approved changes to the system, component, or service;
        d.   Document approved changes to the system, component, or service and the potential security impacts
             of such changes; and
        e.   Track security flaws and flaw resolution within the system, component, or service and report findings
             to appropriate personnel as identified in the SSP.
SA-11 - Developer Testing and Evaluation
        Require the developer of the system, system component, or system service, at all post-design stages of
        the SDLC, to:
        a.   Develop and implement a plan for ongoing security control assessments;
        b.   Perform unit, integration, system, and regression testing/evaluation in accordance with the
             Organization’s defined SDLC at organization-defined depth and coverage, to include, at a minimum,
             the system components to be scanned and the vulnerabilities to be checked;
        c.   Produce evidence of the execution of the assessment plan and the results of the testing and
             evaluation;

        d.   Implement a verifiable flaw remediation process; and
        e.   Correct flaws identified during testing and evaluation.
        SA-11(1) - Developer Testing and Evaluation | Static Code Analysis
        Require the developer of the system, system component, or system service to employ static code analysis
        tools to identify common flaws and document the results of the analysis.
        SA-11(2) - Developer Testing and Evaluation | Threat Modeling and Vulnerability Analyses
        Require the developer of the system, system component, or system service to perform threat modeling
        and vulnerability analyses during development and the subsequent testing and evaluation of the system,
        component, or service that:
        a.   Uses the contextual information (e.g., organization-defined information concerning impact,
             environment of operations, known or assumed threats, and acceptable risk levels);
        b.   Employs organization-defined tools and methods;
        c.   Conducts the modeling and analyses at a breadth and depth of modeling and analyses appropriate for
             the system; and
        d.   Produces evidence that meets organization-defined acceptance criteria.
SA-15 - Development Process, Standards, and Tools
        a.   Require the developer of the system, system component, or system service to follow a documented
             development process that:
             1.     Explicitly addresses security requirements;
             2.     Identifies the standards and tools used in the development process;
             3.     Documents the specific tool options and tool configurations used in the development process;
                    and
             4.     Documents, manages, and ensures the integrity of changes to the process and/or tools used in
                    development; and
        b.   Review the development process, standards, tools, tool options, and tool configurations as needed
             and as dictated by the current threat posture to determine if the process, standards, tools, tool
             options and tool configurations selected and employed can satisfy organization-defined security
             requirements.
        SA-15(3) - Development Process, Standards, and Tools | Criticality Analysis
        Require the developer of the system, system component, or system service to perform a criticality
        analysis:
        a.   During the initiation, acquisition and/or development, implementation, operation and maintenance,
             and disposal stages of the SDLC; and
        b.   At a level of rigor sufficient to document and justify critical decisions, including:
             1.     Functional statement of need;

             2.   Feasibility study;
             3.   Mission and business requirements analysis;
             4.   Security functional requirements analysis;
             5.   Inspection and acceptance;
             6.   System integration;
             7.   Performance measurement;
             8.   Configuration management and control;
             9.   Continuous monitoring; and
             10. Hardware and software disposal.
SA-22 - Unsupported System Components
        a.   Replace system components when support for the components is no longer available from the
             developer, vendor, or manufacturer; or
        b.   Provide the following options for alternative sources for continued support for unsupported
             components:
             1.   Extended security support agreement that includes security software patches and firmware
                  updates from an external source for each unsupported component.
             2.   If software is unsupported, yet necessary for the fulfillment of the enterprise’s mission,
                  document an exception detailing compensating controls and residual risk acceptance.
             3.   Unsupported software without a documented exception must be designated as unauthorized.

## Cross-references

- Rests on: [ORS 276A.300](../../../../statutes/ors-276a.300.md)
- Required by: [DAS 107-004-052](../../policies/das-107-004-052.md)
- Framework: [NIST SP 800-53 Rev. 5](../../../../external-references/nist-sp-800-53-r5.md)
- Parent document: [Statewide IT Control Standards](../eis-css-itcs.md)

## Provenance & change history

- Source: shared snapshot `_meta/snapshots/eis-css-itcs.pdf` / `.txt` · retrieved
  2026-07-17 · sha256 `16985315fc10c902762c51c2a13e78eaf104ac6d6c58cc96eae4cbfdcd698d2a`
- See this knowledge body's [CHANGELOG](../CHANGELOG.md).
