---
id: eis-css-itcs-cm
title: "Statewide IT Control Standards — Configuration Management (CM)"
doc_type: standard
citation: "Statewide Information Technology Control Standards, Configuration Management (CM) family"
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
tags: ["information-security", "control-standards", "cm", "nist-800-53"]
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated summary, not the
> official text. Verify against the official source:
> <https://www.oregon.gov/eis/cyber-security-services/Documents/eis-css-statewide-information-technology(IT)-control-standards.pdf>
> (retrieved 2026-07-17).

# Configuration Management (CM) — Statewide IT Control Standards family

## At a glance

The Configuration Management (CM) control family of Oregon's Statewide Information
Technology Control Standards (January 2024). It defines 12 base controls (plus
enhancements, 27 entries total) that agencies must meet under DAS Policy
107-004-052 and ORS 276A.300. Control numbering and structure follow NIST SP 800-53
Rev. 5. For binding control text, consult the source PDF — this file is an inventory only.

## Full text

CONFIGURATION MANAGEMENT (CM)
CM-1 - Policy and Procedures
        Refer to the Statewide Information Security Plan for additional details on policies and procedures.
CM-2 - Baseline Configuration
        a.   Develop, document, and maintain current baseline configurations;
        b.   Review and update the baseline configurations:
             1.   At least annually or when a significant change occurs;
             2.   When required due to compliance requirement or direction from an authoritative body; and
             3.   When system components are installed or upgraded.
        CM-2(2) - Baseline Configuration | Automation Support for Accuracy and Currency
        Maintain the currency, completeness, accuracy, and availability of the baseline configuration of the
        system using organization-defined automated mechanisms.
        CM-2(3) - Baseline Configuration | Retention of Previous Configurations
        Retain secure images or templates, according to approved configuration standards, for all systems in the
        enterprise, of previous versions of baseline configurations of the system to support rollback.
        CM-2(7) - Baseline Configuration | Configure Systems and Components For High-Risk Areas
        State devices may only be used when traveling for approved state business; State-owned devices are not
        allowed to travel with an employee on personal travel outside of the country without prior CSS
        consultation.
        a.   When travelling internationally to countries sanctioned by the United States Treasury
             (https://ofac.treasury.gov/sanctions-programs-and-country-information) or United States State
             Department (https://www.state.gov/economic-sanctions-programs/):
             1.   All state business must be performed using a onetime use or burner device:
                  i)    Onetime use or burner devices will have no access to state networks;
                  ii)   Passwords for onetime use or burner devices must be different than daily Active Directory
                        (AD) password;
                  iii) Username and password for onetime use or burner devices must not match any other
                        account login and be unique; and
                  iv) Full disk encryption for onetime use or burner devices (Full disk encryption may be illegal in
                        some countries. Please consult with DOJ before travel begins); and
             2.   Access to Enterprise Cloud Platforms is prohibited;
        b.   When travelling internationally to non-sanctioned countries, devices that contain data classified as
             level 3 or above may only contain that data which is necessary for the purpose associated with the
             travel. Any state-issued and -managed device must be hardened according to the Statewide
             Information Technology Control Standards. Additionally,

             2.   Full disk encryption must be implemented on laptops and other portable computing devices (Full
                  disk encryption may be illegal in some countries. Please consult with DOJ before travel begins);
             3.   Personnel must use VPN to access state networks; and
             4.   State-managed mobile devices (e.g., tablets, cell phones) must be enrolled in mobile device
                  management (MDM);
        c.   Upon return from travel to a sanctioned country, user passwords must be reset and devices must be
             returned to organizational information technology support personnel to perform the following
             actions:
             1.   Devices must not connect to internal networks;
             2.   Any data must be copied to external media and scanned for malware before transferring to state
                  network or managed devices;
             3.   Devices must be re-image before returning to checkout status, if applicable; and
        d.   Upon return from travel to a non-sanctioned country:
             1.   Device must be re-imaged before connecting to the state network; and
             2.   User passwords must be reset before returning to work.
CM-3 - Configuration Change Control
        a.   Determine and document the types of changes to systems that are to be configuration-controlled;
        b.   Review proposed configuration-controlled changes to the system and approve or disapprove such
             changes with explicit consideration for security impact analyses;
        c.   Document configuration change decisions associated with the system;
        d.   Implement approved configuration-controlled changes to the system;
        e.   Retain records of configuration-controlled changes to systems according to applicable laws, Executive
             Orders, directives, policies, regulations, standards, and guidance;
        f.   Monitor and review activities associated with configuration-controlled changes to the system; and
        g.   Coordinate and provide oversight for configuration change control activities through regular change
             control meeting that convenes: The frequency of these meetings is dependent upon the needs of the
             agency and should take into account the typical number and impact of changes.
        CM-3(2) - Configuration Change Control | Test / Validate / Document Changes
        Test, validate, and document changes to the system before finalizing the implementation of the changes.
        CM-3(4) - Configuration Change Control | Security Representative
        Require security representation as a part of the change advisory board or process.
CM-4 - Security Impact Analyses
        Analyze changes to systems to determine potential security impacts prior to change implementation.

        CM-4(2) - Security Impact Analysis | Verification of Security Functions
        After system changes, verify that the impacted controls are implemented correctly, operating as
        intended, and producing the desired outcome with regard to meeting the security requirements for the
        system.
CM-5 - Access Restrictions for Change
        Define, document, approve, and enforce physical and logical access restrictions associated with changes
        to the system.
        CM-5(1) - Access Restrictions for Change | Automated Access Enforcement and Audit Records
        a.   Enforce access restrictions using automated mechanisms; and
        b.   Automatically generate audit records of the enforcement actions.
        CM-5(5) - Access Restrictions for Change | Privilege Limitation for Production and Operation
        a.   Limit privileges to change system components and system-related information within a production or
             operational environment; and
        b.   Review and reevaluate privileges at least quarterly.
CM-6 - Configuration Settings
        a.   Establish and document configuration settings for components employed within the system that
             reflect the most restrictive mode consistent with operational requirements using CIS Level 1
             Benchmark;
        b.   Implement the configuration settings;
        c.   Identify, document, and approve any deviations from established configuration settings for
             components within the system based on operational requirements; and
        d.   Monitor and control changes to the configuration settings in accordance with organizational policies
             and procedures.
        CM-6(1) - Configuration Settings | Automated Management, Application, and Verification
        Manage, apply, and verify configuration settings using organization-defined automated mechanisms.
CM-7 - Least Functionality
        a.   Configure the system to provide only essential capabilities;
        b.   Disable or remove by default, all network ports, protocols, server roles, software, and services.
        CM-7(1) - Least Functionality | Periodic Review
        a.   Review systems at least annually to identify unnecessary and / or non-secure functions, ports,
             protocols, software, and services; and
        b.   Disable or remove by default, all network ports, protocols, server roles, software, and services.

        CM-7(2) - Least Functionality | Prevent Program Execution
        Prevent program execution in accordance with the Organization-defined policies, rules of behavior,
        and/or access agreements regarding software program usage and restrictions; rules authorizing the terms
        and conditions of software program usage.
        CM-7(5) - Least Functionality | Authorized Software – Allow by Exception
        a.   Identify and maintain a current inventory of all software assets that are authorized to execute on the
             system;
        b.   Employ a deny-all, permit-by-exception methodology to allow the execution of authorized software
             programs on the system; and
        c.   Review and update the list of authorized software programs at least annually or when there is a
             change.
CM-8 - System Component Inventory
        a.   Develop and document an inventory of system components that:
             1.    Accurately reflects the current system;
             2.    Includes all components within the system;
             3.    Does not include duplicate accounting of components or components assigned to any other
                   system;
             4.    Is at the level of granularity deemed necessary for tracking and reporting; and
             5.    Includes organization-defined information deemed necessary to achieve effective system
                   component accountability; and
        b.   Review and update the system component inventory at least monthly.
        CM-8(1) - System Component Inventory | Updates During Installation / Removals
        Update the inventory of system components as part of component installations, removals, and system
        updates.
        CM-8(3) - System Component Inventory | Automated Unauthorized Component Detection
        a.   Detect the presence of unauthorized hardware, software, and firmware components within the
             system using automated mechanisms with a maximum five-minute delay in detection; and
        b.   Remove or quarantine unauthorized components from the network when unauthorized components
             are detected.
CM-9 - Configuration Management Plan
        Develop, document, and implement a configuration management plan for the systems, that:
        a.   Addresses roles, responsibilities, and configuration management processes and procedures;
        b.   Establishes a process for identifying configuration items throughout the System Development Life
             Cycle (SDLC) and for managing the configuration of the configuration items;

        c.   Defines the configuration items for the system and places the configuration items under
             configuration management;
        d.   Is reviewed and approved by the Agency Chief Information Officer (CIO) or equivalent, or designee
             thereof; and
        e.   Protects the configuration management plan from unauthorized disclosure and modification.
CM-10 - Software Usage Restrictions
        a.   Use software and associated documentation in accordance with contract agreements and copyright
             laws;
        b.   Track the use of software and associated documentation protected by quantity licenses to control
             copying and distribution; and
        c.   Control and document the use of peer-to-peer file sharing technologies to ensure that this capability
             is not used for the unauthorized distribution, display, performance, or reproduction of copyrighted
             work.
CM-11 - User-installed Software
        a.   Establish policies governing the installation of software by users;
        b.   Enforce software installation policies through procedural and automated methods; and
        c.   Monitor policy compliance continuously.
CM-12 - Information Location
        a.   Identify and document the location of a data inventory, based on the enterprise data governance
             policy and the specific system components on which the information is processed and stored;
        b.   Identify and document users who have access to the system and system components where the
             information is processed and stored; and
        c.   Document changes to the location (i.e., system or system components) where the information is
             processed and stored.
        CM-12(1) - Information Location | Automated Tools to Support Information Location
        Use automated tools to identify all sensitive data stored, processed, or transmitted through enterprise
        assets, including those located onsite or at a remote service provider, and update the enterprise's
        sensitive data inventory to ensure controls are in place to protect organizational information.

## Cross-references

- Rests on: [ORS 276A.300](../../../../statutes/ors-276a.300.md)
- Required by: [DAS 107-004-052](../../policies/das-107-004-052.md)
- Framework: [NIST SP 800-53 Rev. 5](../../../../external-references/nist-sp-800-53-r5.md)
- Parent document: [Statewide IT Control Standards](../eis-css-itcs.md)

## Provenance & change history

- Source: shared snapshot `_meta/snapshots/eis-css-itcs.pdf` / `.txt` · retrieved
  2026-07-17 · sha256 `16985315fc10c902762c51c2a13e78eaf104ac6d6c58cc96eae4cbfdcd698d2a`
- See this knowledge body's [CHANGELOG](../CHANGELOG.md).
