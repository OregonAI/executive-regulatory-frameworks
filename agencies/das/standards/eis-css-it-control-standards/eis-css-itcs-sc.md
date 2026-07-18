---
id: eis-css-itcs-sc
title: "Statewide IT Control Standards — System and Communication Protection (SC)"
doc_type: standard
citation: "Statewide Information Technology Control Standards, System and Communication Protection (SC) family"
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
conversion_notes: "family slice of the shared standard snapshot; stripped repeated page line 'Level N, Published PAGE N' x4"
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
tags: ["information-security", "control-standards", "sc", "nist-800-53"]
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated summary, not the
> official text. Verify against the official source:
> <https://www.oregon.gov/eis/cyber-security-services/Documents/eis-css-statewide-information-technology(IT)-control-standards.pdf>
> (retrieved 2026-07-17).

# System and Communication Protection (SC) — Statewide IT Control Standards family

## At a glance

The System and Communication Protection (SC) control family of Oregon's Statewide Information
Technology Control Standards (January 2024). It defines 19 base controls (plus
enhancements, 29 entries total) that agencies must meet under DAS Policy
107-004-052 and ORS 276A.300. Control numbering and structure follow NIST SP 800-53
Rev. 5. For binding control text, consult the source PDF — this file is an inventory only.

## Full text

SYSTEM AND COMMUNICATION PROTECTION (SC)
SC-1 - Policy and Procedures
        Refer to the Statewide Information Security Plan for additional details on policies and procedures.
SC-2 - Separation of System and User Functionality
        Separate user functionality, including user interface services, from system management functionality.
SC-4 - Information In Shared System Resources
        Prevent unauthorized and unintended information transfer via shared system resources.
SC-5 - Denial of Service Protection
        a.   Protect against the effects of denial-of-service (DoS) events including, at a minimum, ICMP (ping)
             flood, SYN flood, slowloris, buffer overflow attack, and volume attack; and
        b.   Employ the following controls to achieve the DoS objective:
             1.   Configuring systems, firewalls, routers, and other network infrastructure to protect against or
                  limit the effects of DoS attacks; and
             2.   Guard against, limit, reduce the susceptibility to, and detect DoS attacks utilizing methods such
                  as:
                  i)    Configuring systems according to documented and established standards for minimizing the
                        effects of DoS attacks;
                  ii)   Configuring routers and switches to disable forwarding of packets to broadcast addresses, as
                        applicable;
                  iii) Configuring routers and firewalls to filter traffic; and
                  iv) Employing increased network capacity and bandwidth combined with service redundancy.
SC-7 - Boundary Protection
        a.   Monitor and control communications at the external managed interfaces to the system and at key
             internal managed interfaces within the system;
        b.   Implement subnetworks for publicly accessible system components that are logically separated (and
             physically separated to the extent possible) from internal organizational networks; and
        c.   Connect to external networks or systems only through managed interfaces consisting of boundary
             protection devices arranged in accordance with an organizational security architecture.
        SC-7(3) - Boundary Protection | Access Points
        Limit the number of external network connections to the system.
        SC-7(4) - Boundary Protection | External Telecommunications Services
        a.   Implement a managed interface for each external telecommunication service;
        b.   Establish a traffic flow policy for each managed interface;
        c.   Protect the confidentiality and integrity of the information being transmitted across each interface;

        d.   Document each exception to the traffic flow policy with a supporting mission/business need and
             duration of that need;
        e.   Review exceptions to the traffic flow policy at least annually and remove exceptions that are no
             longer supported by an explicit mission/business need;
        f.   Prevent unauthorized exchange of control plane traffic with external networks;
        g.   Publish information to enable remote networks to detect unauthorized control plane traffic from
             internal networks; and
        h.   Filter unauthorized control plane traffic from external networks.
        SC-7(5) - Boundary Protection | Deny by Default / Allow by Exception
        Deny network traffic by default and allow network traffic by exception at managed interfaces.
        SC-7(7) - Boundary Protection | Split Tunneling For Remote Devices
        Prevent split tunneling for remote devices connecting to organizational systems unless the split tunnel is
        securely provisioned using a documented and approved procedure consistent with organizational security
        architecture.
        SC-7(8) - Boundary Protection | Route Traffic to Authenticated Proxy Servers
        Route all network traffic to or from the Internet through authenticated proxy servers at managed
        interfaces.
        SC-7(12) - Boundary Protection | Host-based Protection
        Implement Host Intrusion Prevention System (HIPS), Host Intrusion Detection System (HIDS), or minimally
        a host-based firewall at access points and end-user equipment as appropriate.
        SC-7(18) - Boundary Protection | Fail Secure
        Prevent systems from entering unsecure states in the event of an operational failure of a boundary
        protection device.
SC-8 - Transmission Confidentiality and Integrity
        Protect the confidentiality and integrity of transmitted information.
        SC-8(1) - Transmission Confidentiality and Integrity | Cryptographic Protection
        Implement cryptographic mechanisms to prevent unauthorized disclosure of information and detect
        changes to information during transmission.
SC-10 - Network Disconnect
        Terminate the network connection associated with a communications session at the end of the session or
        after no longer than thirty (30) minutes.
SC-12 - Cryptographic Key Establishment and Management
        Establish and manage cryptographic keys when cryptography is employed within the system in
        accordance with NIST-based guidance for key generation, distribution, storage, access, and destruction.

SC-13 - Cryptographic Protection
        a.   Determine the cryptographic uses that comply with applicable laws, statutes, Executive Orders,
             directives, policies, regulations, standards, and guidance, and
        b.   Implement the following types of cryptography required for each specified cryptographic use:
             1.    At Rest:
                   i)    Storage-layer encryption (server-side encryption); and
                   ii)   Application-layer encryption (client-side encryption) where access to the data storage does
                         not permit access to the plain-text data; and
             2.    In Transit:
                   i)    Transport Layer Security (TLS) version 1.2 or later non-deprecated version; and
                   ii)   Secure Shell family of protocols (SSH).
SC-15 - Collaborative Computing Devices and Applications
        a.   Prohibit remote activation of collaborative computing devices and applications; and
        b.   Provide an explicit indication of use to users physically present at the devices.
SC-17 - Public Key Infrastructure Certificates
        a.   Issue public key certificates under an EIS approved service provider or issue public key certificates
             under an agency-documented PKI Certificate Policy (CP) and Certification Practice Statement (CPS);
             and
        b.   Include only approved trust anchors in trust stores or certificate stores managed by the Organization.
SC-18 - Mobile Code
        a.   Define acceptable and unacceptable mobile code and mobile code technologies; and
        b.   Authorize, monitor, and control the use of mobile code within systems.
SC-20 - Secure Name / Address Resolution Service (Authoritative Source)
        a.   Provide additional data origin authentication and integrity verification artifacts along with the
             authoritative name resolution data the system returns in response to external name/address
             resolution queries; and
        b.   Provide the means to indicate the security status of child zones and (if the child supports secure
             resolution services) to enable verification of a chain of trust among parent and child domains, when
             operating as part of a distributed, hierarchical namespace.
SC-21 - Secure Name / Address Resolution Service (Recursive or Caching Resolver)
        Request and perform data origin authentication and data integrity verification on the name/address
        resolution responses the system receives from authoritative sources.
SC-22 - Architecture and Provisioning for Name / Address Resolution Service
        Ensure the systems that collectively provide name/address resolution service for an organization are
        fault-tolerant and implement internal and external role separation.

SC-23 - Session Authenticity
        Protect the authenticity of communications sessions.
SC-28 - Protection of Information at Rest
        Protect the confidentiality and integrity of all information at rest.
        SC-28(1) - Protection of Information at Rest | Cryptographic Protection
        Implement cryptographic mechanisms to prevent unauthorized disclosure and modification of
        information at rest classified as Level 3 (Restricted) or above.
SC-39 - Process Isolation
        Maintain a separate execution domain for each executing system process.
SC-45 - System Time Synchronization
        Synchronize system clocks within and between systems and system components.
        SC-45(1) - System Time Synchronization | Synchronization with Authoritative Time Source
        a.   Compare the internal system clocks at least hourly with an organization-defined authoritative time
             source; and
        b.   Synchronize the internal system clocks to the authoritative time source when there is any time
             difference.

## Cross-references

- Rests on: [ORS 276A.300](../../../../statutes/ors-276a.300.md)
- Required by: [DAS 107-004-052](../../policies/das-107-004-052.md)
- Framework: [NIST SP 800-53 Rev. 5](../../../../external-references/nist-sp-800-53-r5.md)
- Parent document: [Statewide IT Control Standards](../eis-css-itcs.md)

## Provenance & change history

- Source: shared snapshot `_meta/snapshots/eis-css-itcs.pdf` / `.txt` · retrieved
  2026-07-17 · sha256 `16985315fc10c902762c51c2a13e78eaf104ac6d6c58cc96eae4cbfdcd698d2a`
- See this knowledge body's [CHANGELOG](../CHANGELOG.md).
