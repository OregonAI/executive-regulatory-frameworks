---
id: eis-css-itcs-ra
title: "Statewide IT Control Standards — Risk Assessment (RA)"
doc_type: standard
citation: "Statewide Information Technology Control Standards, Risk Assessment (RA) family"
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
tags: ["information-security", "control-standards", "ra", "nist-800-53"]
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated summary, not the
> official text. Verify against the official source:
> <https://www.oregon.gov/eis/cyber-security-services/Documents/eis-css-statewide-information-technology(IT)-control-standards.pdf>
> (retrieved 2026-07-17).

# Risk Assessment (RA) — Statewide IT Control Standards family

## At a glance

The Risk Assessment (RA) control family of Oregon's Statewide Information
Technology Control Standards (January 2024). It defines 6 base controls (plus
enhancements, 11 entries total) that agencies must meet under DAS Policy
107-004-052 and ORS 276A.300. Control numbering and structure follow NIST SP 800-53
Rev. 5. For binding control text, consult the source PDF — this file is an inventory only.

## Full text

RISK ASSESSMENT (RA)
RA-1 - Policy and Procedures
        Refer to the Statewide Information Security Plan for additional details on policies and procedures.
RA-2 - Security Categorization
        a.   Categorize the system and information it processes, stores, and transmits;
        b.   Document the security categorization results, including supporting rationale, in the security plan for
             the system; and
        c.   Verify that the AO or designated representative reviews and approves the security categorization
             decision.
RA-3 - Risk Assessment
        a.   Conduct a risk assessment, including:
             1.   Identifying threats to and vulnerabilities in the system;
             2.   Determining the likelihood and magnitude of harm from unauthorized access, use, disclosure,
                  disruption, modification, or destruction of the system, the information it processes, stores, or
                  transmits, and any related information; and
             3.   Determining the likelihood and impact of adverse effects on individuals arising from the
                  processing of personally identifiable information;
        b.   Integrate risk assessment results and risk management decisions from the Organization and mission
             or business process perspectives with system-level risk assessments;
        c.   Document risk assessment results in a risk assessment report;
        d.   Review risk assessment results at least every three (3) years or when a significant change occurs;
        e.   Disseminate risk assessment results to designated personnel as defined in the SSP; and
        f.   Update the risk assessment at least every three (3) years or when there are significant changes to the
             system, its environment of operation, or other conditions that may impact the security state of the
             system.
        RA-3(1) - Risk Assessment | Supply Chain Risk Assessment
        a.   Assess supply chain risks associated with systems, system components, and system services; and
        b.   Update the supply chain risk assessment at least every three (3) years or when there are significant
             changes to the relevant supply chain, or when changes to the system, environments of operation, or
             other conditions may necessitate a change in the supply chain.
RA-5 - Vulnerability Monitoring and Scanning
        a.   Monitor and scan for vulnerabilities in the system and hosted applications (e.g., operating
             system/infrastructure, web applications, APIs, databases) monthly and when new vulnerabilities
             potentially affecting the system are identified and reported;

        b.   Employ vulnerability scanning tools and techniques that facilitate interoperability among tools and
             automate parts of the vulnerability management process by using standards for:
             1.   Enumerating platforms, software flaws, and improper configurations;
             2.   Formatting checklists and test procedures; and
             3.   Measuring vulnerability impact;
        c.   Analyze vulnerability scan reports and results from vulnerability monitoring;
        d.   Remediate legitimate vulnerabilities:
             1.   High-risk vulnerabilities mitigated within thirty (30) days from date of discovery;
             2.   Moderate-risk vulnerabilities mitigated within ninety (90) days from date of discovery; and
             3.   Low risk vulnerabilities mitigated within one hundred eighty (180) days from date of discovery in
                  accordance with an organizational assessment of risk;
        e.   Share information obtained from the vulnerability monitoring process and control assessments with
             designated agency personnel to help eliminate similar vulnerabilities in other systems; and
        f.   Employ vulnerability scanning tools that include the capability to regularly update the vulnerabilities
             to be scanned.
        RA-5(2) - Vulnerability Monitoring and Scanning | Update by Frequency / Prior to New Scan / When
        Identified
        Update the system vulnerabilities to be scanned prior to a new scan, or when new vulnerabilities are
        identified and reported.
        RA-5(3) - Vulnerability Monitoring and Scanning | Breadth and Depth of Coverage
        Define the breadth and depth of vulnerability scanning coverage.
        RA-5(5) - Vulnerability Monitoring and Scanning | Privileged Access
        Implement privileged access authorization to all components that support authentication for all scans.
        RA-5(11) - Vulnerability Monitoring and Scanning | Public Disclosure Program
        Establish a public reporting channel for receiving reports of vulnerabilities in organizational systems and
        system components.
RA-7 - Risk Response
        Respond to findings from security assessments, monitoring, and audits in accordance with organizational
        risk tolerance.
RA-9 - Criticality Analysis
        Identify critical system components and functions by performing a criticality analysis for, system
        components, or system services and document the analysis in the SSP.

## Cross-references

- Rests on: [ORS 276A.300](../../../../statutes/ors-276a.300.md)
- Required by: [DAS 107-004-052](../../policies/das-107-004-052.md)
- Framework: [NIST SP 800-53 Rev. 5](../../../../external-references/nist-sp-800-53-r5.md)
- Parent document: [Statewide IT Control Standards](../eis-css-itcs.md)

## Provenance & change history

- Source: shared snapshot `_meta/snapshots/eis-css-itcs.pdf` / `.txt` · retrieved
  2026-07-17 · sha256 `16985315fc10c902762c51c2a13e78eaf104ac6d6c58cc96eae4cbfdcd698d2a`
- See this knowledge body's [CHANGELOG](../CHANGELOG.md).
