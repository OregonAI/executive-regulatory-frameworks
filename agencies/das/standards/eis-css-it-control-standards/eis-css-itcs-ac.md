---
id: eis-css-itcs-ac
title: "Statewide IT Control Standards — Access Control (AC)"
doc_type: standard
citation: "Statewide Information Technology Control Standards, Access Control (AC) family"
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
conversion_notes: "family slice of the shared standard snapshot; stripped repeated page line 'Level N, Published PAGE N' x6"
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
tags: ["information-security", "control-standards", "ac", "nist-800-53"]
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated summary, not the
> official text. Verify against the official source:
> <https://www.oregon.gov/eis/cyber-security-services/Documents/eis-css-statewide-information-technology(IT)-control-standards.pdf>
> (retrieved 2026-07-17).

# Access Control (AC) — Statewide IT Control Standards family

## At a glance

The Access Control (AC) control family of Oregon's Statewide Information
Technology Control Standards (January 2024). It defines 17 base controls (plus
enhancements, 43 entries total) that agencies must meet under DAS Policy
107-004-052 and ORS 276A.300. Control numbering and structure follow NIST SP 800-53
Rev. 5. For binding control text, consult the source PDF — this file is an inventory only.

## Full text

ACCESS CONTROL – AC
AC-1 - Policy and Procedures
        Policies and procedures for each control family in this document are referenced in the Statewide
        Information Security Plan (the “Plan”). Individual policies for each control family may be supplied within
        the Plan or may be published as separate documents. The individual policies reference the applicable
        controls that are defined in this document.
        Refer to the Statewide Information Security Plan for additional details on policies and procedures.
AC-2 - Account Management
        a.   Define and document the types of accounts allowed and specifically prohibited for use within the
             system;
        b.   Assign account managers;
        c.   Require account manager or designee approval for group and role membership;
        d.   Specify:
             1.   Authorized users of the system;
             2.   Group and role membership; and
             3.   Access authorizations (i.e., privileges) and organization-defined attributes (as required) for each
                  account;
        e.   Require approvals by account manager or designee for requests to create accounts;
        f.   Create, enable, modify, disable, and remove accounts in accordance with organization-defined policy,
             procedures, prerequisites, and criteria;
        g.   Monitor the use of accounts;
        h.   Notify account manager or designee within:
             1.   Twenty-four (24) hours when accounts are no longer required;
             2.   Eight (8) hours when users are terminated or transferred; and
             3.   Eight (8) hours when system usage or need-to-know changes for an individual;
        i.   Authorize access to the system based on:
             1.   A valid access authorization;
             2.   Intended system usage; and
             3.   Applicable federal and state laws and regulations;
        j.   Review accounts for compliance with account management requirements at least annually;
        k.   Establish and implement a process for changing shared or group account authenticators (if deployed)
             when individuals are removed from the group; and
        l.   Align account management processes with personnel termination and transfer processes.

        AC-2(1) - Account Management | Automated System Account Management
        Support the management of system accounts using automated mechanisms.
        AC-2(2) - Account Management | Automated Temporary and Emergency Account Management
        Automatically disable temporary and emergency accounts after no more than thirty (30) days.
        AC-2(3) - Account Management | Disable Accounts
        Disable accounts within twenty-four (24) hours when the accounts:
        a.   Have expired;
        b.   Are no longer associated with a user or individual;
        c.   Are in violation of organizational policy; or
        d.   Have been inactive for ninety (90) days
        AC-2(4) - Account Management | Automated Audit Actions
        Automatically audit account creation, modification, enabling, disabling, and removal actions.
        AC-2(5) - Account Management | Inactivity Logout
        Require that users log out when leaving their workstation unattended.
        AC-2(7) - Account Management | Privileged User Accounts
        a.   Establish and administer privileged user accounts in accordance with a role-based access scheme;
        b.   Monitor privileged role or attribute assignments;
        c.   Monitor changes to roles or attributes; and
        d.   Revoke access when privileged role or attribute assignments are no longer appropriate.
        AC-2(9) - Account Management | Restrictions on Use of Shared and Group Accounts
        Only permit the use of shared and group accounts that meet organization-defined need with justification
        statement that explains why such accounts are necessary.
        AC-2(12) - Account Management | Account Monitoring for Atypical Usage
        a.   Monitor system accounts for organization-defined atypical usage; and
        b.   Report atypical usage of system accounts in accordance with the organization’s Incident Response
             Plan.
        AC-2(13) - Account Management | Disable Accounts for High-Risk Individuals
        Disable accounts of individuals within one (1) hour of discovery of user posing a significant risk.
AC-3 - Access Enforcement
        Enforce approved authorizations for logical access to information and system resources in accordance
        with applicable access control policies.
AC-4 - Information Flow Enforcement
        Enforce approved authorizations for controlling the flow of information within the system and between
        connected systems based on organization-defined information control flow policies.

        AC-4(21) - Information Flow Enforcement | Physical or Logical Separation of Information Flows
        Separate information flows logically or physically using organization-defined mechanisms and/or
        techniques to accomplish required separations by types of information.
AC-5 - Separation of Duties
        a.   Identify and document roles and permissions; and
        b.   Define system access authorizations to support separation of duties.
AC-6 - Least Privilege
        Employ the principle of least privilege, allowing only authorized access for users, or processes acting on
        behalf of users, that are necessary to accomplish assigned organizational tasks.
        AC-6(1) - Least Privilege | Authorize Access to Security Functions
        Authorize access for privileged users to:
        a.   Security functions; and
        b.   Security-relevant information.
        AC-6(2) - Least Privilege | Non-privileged Access for Non-security Functions
        Require that users of system accounts (or roles) with access to all security functions use non-privileged
        accounts or roles, when accessing non-security functions.
        AC-6(5) - Least Privilege | Privileged Accounts
        Restrict privileged accounts on the system to authorized individuals with a need for elevated privileges.
        AC-6(7) - Least Privilege | Review of User Privileges
        a.   Review the privileges assigned to all users with privileges at least annually to validate the need for
             such privileges; and
        b.   Reassign or remove privileges, if necessary, to correctly reflect organizational mission and business
             needs.
        AC-6(9) - Least Privilege | Log Use of Privileged Functions
        Log the execution of privileged functions.
        AC-6(10) - Least Privilege | Prohibit Non-privileged Users From Executing Privileged Functions
        Prevent non-privileged users from executing privileged functions.
AC-7 - Unsuccessful Logon Attempts
        a.   Enforce a limit of no more than three (3) consecutive invalid logon attempts by a user during a fifteen
             (15) minute period;
             1.   For mobile devices: not more than ten (10) consecutive invalid attempts; and
        b.   Automatically lock the account or node for a minimum of thirty (30) minutes or until unlocked by an
             administrator.

AC-8 - System Use Notification
        Prior to granting access to the system, display to users an approved system use notification that provides
        privacy and security notices consistent with applicable federal and state laws. Executive Orders,
        directives, policies, regulations, standards, and guidance.
        a.   The system use notification message shall, at a minimum, provide the following information:
             1.   Users are accessing a U.S. Government system;
             2.   System usage may be monitored, recorded, and subject to audit;
             3.   Unauthorized use of the system is prohibited and subject to criminal and civil penalties; and
             4.   Use of the system indicates consent to monitoring and recording;
        b.   Retain the notification message or banner on the screen until users acknowledge the usage
             conditions and take explicit actions to log on to or further access the system; and
        c.   For publicly accessible systems:
             1.   Display system use information notification, before granting further access to the publicly
                  accessible system;
             2.   Display references, if any, to monitoring, recording, or auditing that are consistent with privacy
                  accommodations for such systems that generally prohibit those activities; and
             3.   Include a description of the authorized uses of the system.
AC-11 - Device Lock
        a.   Prevent further access to the system by:
             1.   Initiating a device lock after fifteen (15) minutes of inactivity
                  i)   For mobile devices, five (5) minutes; and
             2.   Requiring the user to initiate a device lock before leaving the system unattended; and
        b.   Retain the device lock until the authorized user reestablishes access using identification and
             authentication procedures.
        AC-11(1) - Device Lock | Pattern Hiding Displays
        Conceal, via the device lock, information previously visible on the display, with a publicly viewable image.
AC-12 - Session Termination
        Automatically terminate user sessions after thirty (30) minutes of inactivity, unless otherwise defined in
        the applicable System Security Plan (SSP).
AC-14 - Permitted Actions without Identification or Authentication
        a.   Identify specific user actions that can be performed on the system without identification or
             authentication consistent with agency missions and business functions; and
        b.   Document and provide supporting rationale in SSPs for user actions that do not require identification
             or authorization.

AC-17 - Remote Access
        a.   Establish and document usage restrictions, configuration / connection requirements, and
             implementation guidance for each type of remote access allowed; and
        b.   Authorize each type of remote access to the system prior to allowing such connections.
        AC-17(1) - Remote Access | Monitoring and Control
        Employ automated mechanisms to monitor and control remote access methods.
        AC-17(2) - Remote Access | Protection of Confidentiality / Integrity Using Encryption
        Implement cryptographic mechanisms to protect the confidentiality and integrity of remote access
        sessions.
        AC-17(3) - Remote Access | Managed Access Control Points
        Route all remote accesses through authorized and managed network access control points.
        AC-17(4) - Remote Access | Privileged Commands / Access
        a.   Authorize the execution of privileged commands and access to security-relevant information via
             remote access only in a format that provides assessable evidence and when there is a compelling
             business need; and
        b.   Document the rationale for such access in the SSP.
AC-18 - Wireless Access
        a.   Establish configuration requirements, connection requirements, and implementation guidance for
             each type of wireless access; and
        b.   Authorize each type of wireless access to the system prior to allowing such connections.
        AC-18(1) - Wireless Access | Authentication and Encryption
        Protect wireless access to the system using authentication of both user and devices, and encryption.
        AC-18(3) - Wireless Access | Disable Wireless Networking
        Disable, when not intended for use, wireless networking capabilities embedded within system
        components prior to issuance and deployment.
AC-19 - Access Control for Mobile Devices
        a.   Establish configuration requirements, connection requirements, and implementation guidance for
             organization-controlled mobile devices, to include when such devices are outside of controlled areas;
             and
        b.   Authorize the connection of mobile devices to organizational systems.
        AC-19(5) - Access Control for Mobile Devices | Full Device / Container-based Encryption
        Employ full-device encryption to protect the confidentiality and integrity of information on all mobile
        devices.

AC-20 - Use of External Systems
        Establish terms and conditions, consistent with any trust relationships established with other
        organizations owning, operating, and / or maintaining external systems, allowing authorized individuals
        to:
        a.    Access internal information systems or system components from external systems; and
        b.    Process, store, or transmit organization-controlled information using external systems.
        AC-20(1) - Use of External Systems | Limits on Authorized Use
        Permit authorized individuals to use an external system to access the system or to process, store, or
        transmit organization-controlled information only after:
        a.    Verification of the implementation of controls on the external system as specified in the
              Organization’s security policies and plans; or
        b.    Retention of approved system connection or processing agreements with the organizational entity
              hosting the external system.
        AC-20(2) - Use of External Systems | Portable Storage Devices
        Restrict the use of organization-controlled portable storage devices by authorized individuals on external
        systems using agency documented and approved restrictions.
AC-21 - Information Sharing
        a.    Enable authorized users to determine whether access authorizations assigned to a sharing partner
              match the information’s access and use restrictions for information sharing circumstances where user
              discretion is required; and
        b.    Employ automated mechanisms or manual processes compliant with agency requirements to assist
              users in making information sharing and collaboration decisions.
AC-22 - Publicly Accessible Content
        a.    Designate individuals that are authorized to make information publicly accessible;
        b.    Train authorized individuals to ensure that publicly accessible information does not contain non-
              public information;
        c.    Review the proposed content of information prior to posting onto the publicly accessible system to
              ensure that nonpublic information is not included; and
        d.    Review content on the publicly accessible system for non-public information at least quarterly and
              remove such information, if discovered.

## Cross-references

- Rests on: [ORS 276A.300](../../../../statutes/ors-276a.300.md)
- Required by: [DAS 107-004-052](../../policies/das-107-004-052.md)
- Framework: [NIST SP 800-53 Rev. 5](../../../../external-references/nist-sp-800-53-r5.md)
- Parent document: [Statewide IT Control Standards](../eis-css-itcs.md)

## Provenance & change history

- Source: shared snapshot `_meta/snapshots/eis-css-itcs.pdf` / `.txt` · retrieved
  2026-07-17 · sha256 `16985315fc10c902762c51c2a13e78eaf104ac6d6c58cc96eae4cbfdcd698d2a`
- See this knowledge body's [CHANGELOG](../CHANGELOG.md).
