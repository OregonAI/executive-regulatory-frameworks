---
id: eis-css-itcs-ia
title: "Statewide IT Control Standards — Identification and Authentication (IA)"
doc_type: standard
citation: "Statewide Information Technology Control Standards, Identification and Authentication (IA) family"
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
tags: ["information-security", "control-standards", "ia", "nist-800-53"]
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated summary, not the
> official text. Verify against the official source:
> <https://www.oregon.gov/eis/cyber-security-services/Documents/eis-css-statewide-information-technology(IT)-control-standards.pdf>
> (retrieved 2026-07-17).

# Identification and Authentication (IA) — Statewide IT Control Standards family

## At a glance

The Identification and Authentication (IA) control family of Oregon's Statewide Information
Technology Control Standards (January 2024). It defines 10 base controls (plus
enhancements, 27 entries total) that agencies must meet under DAS Policy
107-004-052 and ORS 276A.300. Control numbering and structure follow NIST SP 800-53
Rev. 5. For binding control text, consult the source PDF — this file is an inventory only.

## Full text

IDENTIFICATION AND AUTHENTICATION (IA)
IA-1 - Policy and Procedures
        Refer to the Statewide Information Security Plan for additional details on policies and procedures.
IA-2 - Identification and Authentication (Organizational Users)
        Uniquely identify and authenticate organizational users and associate that unique identification with
        processes acting on behalf of those users.
        IA-2(1) - Identification and Authentication (Organizational Users) | Multi-factor Authentication to
        Privileged Accounts
        Implement multi-factor authentication for access to privileged accounts.
        IA-2(2) - Identification and Authentication (Organizational Users) | Multi-factor Authentication to Non-
        privileged Accounts
        Implement multi-factor authentication for access to non-privileged accounts.
        IA-2(5) - Identification and Authentication (organizational Users) | Individual Authentication with
        Group Authentication
        When shared accounts or authenticators are employed, require users to be individually authenticated
        before granting access to the shared accounts or resources.
        IA-2(6) - Identification and Authentication (organizational Users) | Access to Accounts – Separate
        Device
        Implement multi-factor authentication for local, network, or remote access to privileged and non-
        privileged accounts such that:
        a.   One of the factors is provided by a device separate from the system gaining access; and
        b.   The device meets organization-defined strength of mechanism requirements.
        IA-2(8) - Identification and Authentication (Organizational users) | Access to Accounts – Replay
        Resistant
        Implement replay-resistant authentication mechanisms for access to privileged accounts and non-
        privileged accounts.
        IA-2(12) - Identification and Authentication (Organizational users) | Acceptance of PIV Credentials
        Accept and electronically verify Personal Identity Verification (PIV)-compliant credentials for applicable
        Federal Systems.
IA-3 - Device-Level Identification and Authentication
        Uniquely identify and authenticate end user-operated devices, including devices that are not owned by
        the Organization, before accessing agency information assets.
IA-4 - Identifier Management
        Manage system identifiers by:

        a.   Receiving authorization from the documented agency designated approving authority to assign an
             individual, group, role, or device identifier;
        b.   Selecting an identifier that identifies an individual, group, role, or device;
        c.   Assigning the identifier to the intended individual, group role, or device; and
        d.   Preventing reuse of identifiers for at least two (2) years.
        IA-4(4) - Identifier Management | Identify User Status
        Manage individual identifiers by uniquely identifying each individual status including contractors, foreign
        nationals, and non-organizational users.
IA-5 - Authenticator Management
        Manage system authenticators as follows:
        a.   Verifying, as part of the initial authenticator distribution, the identity of the individual, group, role,
             service, or device receiving the authenticator;
        b.   Establishing initial authenticator content for any authenticators issued by the Organization;
        c.   Ensuring that authenticators have sufficient strength of mechanism for their intended use;
        d.   Establishing and implementing administrative procedures for initial authenticator distribution, for lost
             or compromised or damaged authenticators, and for revoking authenticators;
        e.   Changing default authenticators prior to first use;
        f.   Changing or refreshing authenticators at least every ninety (90) days or when authenticators are
             shared, reported lost, stolen, or compromised;
        g.   Protecting authenticator content from unauthorized disclosure and modification;
        h.   Requiring individuals to take, and have devices implement, specific controls to protect
             authenticators; and
        i.   Changing authenticators for group or role accounts when membership to those accounts changes.
        IA-5(1) - Authenticator Management | Password-Based Authentication
        For password-based authentication:
        a.   Maintain a list of commonly used, expected, or compromised passwords and update the list at least
             every three (3) years and when organizational passwords are suspected to have been compromised
             directly or indirectly;
        b.   Verify, when users create or update passwords, that the passwords are not found on the list of
             commonly used, expected, or compromised passwords;
        c.   Transmit passwords only over cryptographically protected channels;
        d.   Store passwords using an approved salted key derivation function, preferably using a keyed hash;
        e.   Require immediate selection of a new password upon account recovery;
        f.   Allow user selection of long passwords and passphrases, including spaces and all printable characters;
        g.   Employ automated tools to assist the user in selecting strong password authenticators;

        h.   Enforce the following composition and complexity rules:
             1.   Enforce minimum password length of fifteen (15) characters;
             2.   Enforce minimum password complexity to contain at least:
                  i)    One (1) numeric (e.g., zero – 9);
                  ii)   One (1) non-alphanumeric character (e.g., @, #, $, %, ^, &, etc.);
                  iii) One (1) English uppercase letter (e.g., A – Z); and
                  iv) One (1) English lowercase letter (e.g., a – z);
             3.   No dictionary words or common names;
             4.   No portions of the associated account name / identifier (e.g., User I.D., login name); and
             5.   Enforce at least one (1) character change when new passwords are selected for use;
        i.   Store and transmit only cryptographically protected passwords;
        j.   Enforce password lifetime restrictions:
             1.   One (1) day minimum and sixty (60) days maximum; and
             2.   Service accounts passwords shall expire within three hundred sixty-six 366 days (inclusive);
        k.   Password History/Reuse:
             1.   For all systems: twenty-four (24) generations; and
             2.   For systems unable to implement history/reuse restriction by generations but are able to restrict
                  history/reuse for a specified time period, passwords shall not be reusable for a period of six (6)
                  months;
        l.   Allow the use of a temporary password for system logons with an immediate change to a permanent
             password;
        m. Map the authenticated identity to the account of the individual or group; and
        n.   Implement a local cache of revocation data to support path discovery and validation.
        IA-5(2) - Authenticator Management | PKI Based Authentication
        a.   For public key-based authentication:
             1.   Enforce authorized access to the corresponding private key; and
             2.   Map the authenticated identity to the account of the individual or group; and.
        b.   When Public Key Infrastructure (PKI) is used:
             1.   Validate certificates by constructing and verifying a certification path to an accepted trust
                  anchor, including checking certificate status information; and
             2.   Implement a local cache of revocation data to support path discovery and validation.
        IA-5(6) - Authenticator Management | Protection of Authenticators
        Protect authenticators commensurate with the security category of the information to which use of the
        authenticator permits access.

        IA-5(7) - Authenticator Management | No Embedded Unencrypted Static Authenticators
        Ensure that unencrypted static authenticators are not embedded in applications or other forms of static
        storage.
IA-6 - Authenticator Feedback
        Obscure feedback of authentication information during the authentication process to protect the
        information from possible exploitation and use by unauthorized individuals.
IA-7 - Cryptographic Module Authentication
        Implement mechanisms for authentication to a cryptographic module that will meet the requirements of
        applicable laws, Executive Orders, directives, policies, regulations, standards, and guidance for such
        authentication.
IA-8 - Identification and Authentication (Non-Organizational Users)
        Uniquely identify and authenticate non-organizational users or processes acting on behalf of non-
        organizational users.
        IA-8(1) - Identification and Authentication (Non-Organizational Users) | Acceptance of PIV Credentials
        from other agencies
        Accept and electronically verify PIV-compliant credentials from other federal agencies for applicable
        federal systems.
        IA-8(2) - Identification and Authentication (Non-Organizational Users) | Acceptance of External
        Authentication
        For applicable federal systems:
        a.   Accept only external authenticators that are NIST-compliant; and
        b.   Document and maintain a list of accepted external authenticators.
        IA-8(4) - Identification and Authentication (Non-Organizational Users) | Use of FICAM- Issued Profiles
        Conform to organization-defined identity management profiles.
IA-11 - Identification and Authentication | Re-Authentication
        Require users to re-authenticate:
        a.   When roles, authenticators or credentials change;
        b.   When execution of privileged functions occurs; or
        c.   Within 7 days of previous authentication; and
        d.   Within twenty-four (24) hours of previous authentication.
IA-12 - Identity Proofing
        a.   Identity proof users that require accounts for logical access to systems based on appropriate identity
             assurance level requirements as specified in applicable standards and guidelines;
        b.   Resolve user identities to a unique individual; and
        c.   Collect, validate, and verify identity evidence.

        IA-12(2) - Identity Proofing | Identity Evidence
        Require evidence of individual identification.
        IA-12(3) - Identity Proofing | Identity Evidence Validation and Verification
        Require that the presented identity evidence be validated and verified through organizational defined
        methods of validation and verification.
        IA-12(5) - Identity Proofing | Address Confirmation
        Require that a notice of proofing be delivered through an out-of-band channel to verify the users address
        (physical or digital) of record.

## Cross-references

- Rests on: [ORS 276A.300](../../../../statutes/ors-276a.300.md)
- Required by: [DAS 107-004-052](../../policies/das-107-004-052.md)
- Framework: [NIST SP 800-53 Rev. 5](../../../../external-references/nist-sp-800-53-r5.md)
- Parent document: [Statewide IT Control Standards](../eis-css-itcs.md)

## Provenance & change history

- Source: shared snapshot `_meta/snapshots/eis-css-itcs.pdf` / `.txt` · retrieved
  2026-07-17 · sha256 `16985315fc10c902762c51c2a13e78eaf104ac6d6c58cc96eae4cbfdcd698d2a`
- See this knowledge body's [CHANGELOG](../CHANGELOG.md).
