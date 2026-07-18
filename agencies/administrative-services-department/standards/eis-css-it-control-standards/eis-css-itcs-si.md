---
id: eis-css-itcs-si
title: "Statewide IT Control Standards — System and Information Integrity (SI)"
doc_type: standard
citation: "Statewide Information Technology Control Standards, System and Information Integrity (SI) family"
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
tags: ["information-security", "control-standards", "si", "nist-800-53"]
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated summary, not the
> official text. Verify against the official source:
> <https://www.oregon.gov/eis/cyber-security-services/Documents/eis-css-statewide-information-technology(IT)-control-standards.pdf>
> (retrieved 2026-07-17).

# System and Information Integrity (SI) — Statewide IT Control Standards family

## At a glance

The System and Information Integrity (SI) control family of Oregon's Statewide Information
Technology Control Standards (January 2024). It defines 12 base controls (plus
enhancements, 23 entries total) that agencies must meet under DAS Policy
107-004-052 and ORS 276A.300. Control numbering and structure follow NIST SP 800-53
Rev. 5. For binding control text, consult the source PDF — this file is an inventory only.

## Full text

SYSTEM AND INFORMATION INTEGRITY (SI)
SI-1 - Policy and Procedures
        Refer to the Statewide Information Security Plan for additional details on policies and procedures.
SI-2 - Flaw Remediation
        a.   Identify, report, and correct system flaws;
        b.   Test software and firmware updates related to flaw remediation for effectiveness and potential side
             effects prior to installation;
        c.   Apply security-relevant software and firmware updates within a timeframe based on the National
             Vulnerability Database (NVD) Vulnerability Severity Rating of the flaw as follows:
             1.   Flaws rated as High and above severity within seven (7) calendar days;
             2.   Medium severity within fifteen (15) calendar days; and
             3.   All others within thirty (30) calendar days; and
        d.   Incorporate flaw remediation into organizational configuration management processes.
        SI-2(2) - Flaw Remediation | Automated Flaw Remediation Status
        Determine if system components have applicable security-relevant software and firmware updates
        installed using automated mechanisms.
        SA-2(3) - Flaw Remediation | Time to Remediate Flaws and Benchmarks for Corrective Actions
        a.   Measure the time between flaw identification and flaw remediation; and
        b.   Establish benchmarks for taking corrective actions based on criticality.
SI-3 - Malicious Code Protection
        a.   Implement signature based and non-signature based malicious code protection mechanisms at
             system entry and exit points to detect and eradicate malicious code;
        b.   Automatically update malicious code protection mechanisms as new releases are available in
             accordance with organizational configuration management policy and procedures;
        c.   Configure malicious code protection mechanisms to:
             1.   Perform periodic scans of the system at least weekly and real-time scans of files from external
                  sources to include endpoints and network entry and exit points as the files are downloaded,
                  opened, or executed ;
             2.   Block and quarantine malicious code and alert administrator or defined security personnel near-
                  real-time; and
             3.   Send alert to designated agency in response to malicious code detection; and
        d.   Address the receipt of false positives during malicious code detection and eradication and the
             resulting potential impact on the availability of the system.
SI-4 - System Monitoring
        a.   Monitor events to detect:

             1.   Attacks and indicators of potential attack in accordance with monitoring objectives;
             2.   Unauthorized local, network, and remote connections;
        b.   Identify unauthorized use of the system;
        c.   Invoke internal monitoring capabilities or deploy monitoring devices:
             1.   Strategically within the system to collect organization-determined essential information; and
             2.   At ad hoc locations within the system to track specific types of transactions of interest to the
                  Organization;
        d.   Analyze detected events and anomalies;
        e.   Adjust the level of system monitoring activity when there is a change in risk to organizational
             operations and assets, individuals, other organizations, or the Nation;
        f.   Obtain legal opinion regarding system monitoring activities; and
        g.   Provide system monitoring information to personnel or roles designated by the agency as needed to
             support the agency’s continuous monitoring and incident response program.
        SI-4(1) - System Monitoring | System-wide Intrusion Detection System
        Connect and configure individual intrusion detection tools into a system-wide intrusion detection system.
        SI-4(2) - System Monitoring | Automated Tools for Real-Time Analysis
        Employ automated tools and mechanisms to support near real-time analysis of events.
        SI-4(4) - System Monitoring | Inbound and Outbound Communications Traffic
        a.   Determine criteria for unusual or unauthorized activities or conditions for inbound and outbound
             communications traffic; and
        b.   Monitor inbound and outbound communications traffic continuously for unusual or unauthorized
             activities.
        SI-4(5) - System Monitoring | System Generated Alerts
        Alert appropriate personnel or roles when the following system-generated indications of compromise or
        potential compromise occur:
        a.   Presence of malicious code;
        b.   Unauthorized export of information;
        c.   Signaling to an external information system;
        d.   Indicators of potential intrusion;
        e.   Any incident relevant to the Oregon Consumer Identity Protection Act (OCIPA);
        f.   Successful phishing attack;
        g.   DoS attack;
        h.   Adding an account to or removing an account from any group with administrative privileges; and
        i.   Unsuccessful login attempts to an account with administrative privileges.

        SI-4(16) - System Monitoring | Correlate Monitoring Information
        Correlate information from monitoring tools and mechanisms employed throughout the system.
        SI-4(18) - System Monitoring | Analyze Traffic and Covert Exfiltration
        Analyze outbound communications traffic at external interfaces to the system and at the following
        interior points to detect covert exfiltration of information at organization-defined interior points within
        the system.
        SI-4(23) - System Monitoring | Host-based Devices
        Implement host-based monitoring mechanisms at organization-defined system components.
SI-5 - Security Alerts, Advisories, and Directives
        a.   Receive system security alerts, advisories, and directives from EIS/CSS on an ongoing basis. Sources
             may include, but are not limited to: US-CERT, ICS-CERT, and MS-ISAC;
        b.   Generate internal security alerts, advisories, and directives as deemed necessary;
        c.   Disseminate security alerts, advisories, and directives to appropriate agency personnel, including
             Agency System Owners; and
        d.   Implement security directives in accordance with established timeframes or notify the issuing
             organization of the degree of noncompliance.
SI-6 - Security Function Verification
        a.   Verify the correct operation of organization-defined security functions;
        b.   Perform the verification of the functions specified in SI-6a (including upon system startup and/or
             restart) upon command by user with appropriate privilege; at least monthly;
        c.   Alert system administrators and security personnel to failed security verification tests; and
        d.   Take immediate steps to triage and isolate the impacted system or component when anomalies are
             discovered.
SI-7 - Software, Firmware, and Information Integrity
        a.   Employ integrity verification tools to detect unauthorized changes to software, firmware, and
             information; and
        b.   Immediately notify designated agency officials when unauthorized changes to the software,
             firmware, and information are detected.
        SI-7(1) - Software, Firmware, and Information Integrity | Integrity Checks
        Perform an integrity check of software, firmware, and information as defined in applicable agency SSPs.
        SI-7(7) - Software, Firmware, and Information Integrity | Integration of Detection and Response
        Incorporate the detection of unauthorized security-relevant changes into the organizational incident
        response capability.

SI-8 - Spam Protection
        a.   Employ spam protection mechanisms at system entry and exit points to detect unsolicited messages;
             and
        b.   Update spam protection mechanisms when new releases are available in accordance with
             organizational configuration management policy and procedures.
        SI-8(2) - Spam Protection | Automatic Updates
        Automatically update spam protection mechanisms.
SI-10 - Information Input Validation
        Check the validity of information inputs and verify that inputs match specified definitions for format and
        content.
SI-11 - Error Handling
        a.   Generate error messages that provide information necessary for corrective actions without revealing
             information that could be exploited; and
        b.   Reveal error messages only to authorized personnel or roles as defined in the applicable SSP.
SI-12 - Information Management and Retention
        Manage and retain information within the system and information output from the system in accordance
        with applicable laws, Executive Orders, directives, regulations, policies, standards, guidelines, and
        operational requirements.
SI-16 - Memory Protection
        Implement security safeguards to protect the system memory from unauthorized code execution.

## Cross-references

- Rests on: [ORS 276A.300](../../../../statutes/ors-276a.300.md)
- Required by: [DAS 107-004-052](../../policies/das-107-004-052.md)
- Framework: [NIST SP 800-53 Rev. 5](../../../../external-references/nist-sp-800-53-r5.md)
- Parent document: [Statewide IT Control Standards](../eis-css-itcs.md)

## Provenance & change history

- Source: shared snapshot `_meta/snapshots/eis-css-itcs.pdf` / `.txt` · retrieved
  2026-07-17 · sha256 `16985315fc10c902762c51c2a13e78eaf104ac6d6c58cc96eae4cbfdcd698d2a`
- See this knowledge body's [CHANGELOG](../CHANGELOG.md).
