---
id: eis-css-itcs-pe
title: "Statewide IT Control Standards — Physical and Environmental Protection (PE)"
doc_type: standard
citation: "Statewide Information Technology Control Standards, Physical and Environmental Protection (PE) family"
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
tags: ["information-security", "control-standards", "pe", "nist-800-53"]
---

> **NON-AUTHORITATIVE — AI-friendly reference only.** This is a curated summary, not the
> official text. Verify against the official source:
> <https://www.oregon.gov/eis/cyber-security-services/Documents/eis-css-statewide-information-technology(IT)-control-standards.pdf>
> (retrieved 2026-07-17).

# Physical and Environmental Protection (PE) — Statewide IT Control Standards family

## At a glance

The Physical and Environmental Protection (PE) control family of Oregon's Statewide Information
Technology Control Standards (January 2024). It defines 16 base controls (plus
enhancements, 19 entries total) that agencies must meet under DAS Policy
107-004-052 and ORS 276A.300. Control numbering and structure follow NIST SP 800-53
Rev. 5. For binding control text, consult the source PDF — this file is an inventory only.

## Full text

PHYSICAL AND ENVIRONMENTAL PROTECTION (PE)
PE-1 - Policy and Procedures
        Refer to the Statewide Information Security Plan for additional details on policies and procedures.
PE-2 - Physical Access Authorizations
        a.   Develop, approve, and maintain a list of individuals with authorized access to the facility where the
             system resides;
        b.   Issue authorization credentials for facility access;
        c.   Review the access list detailing authorized facility access by individuals at least annually; and
        d.   Remove individuals from the facility access list when access is no longer required.
PE-3 - Physical Access Control
        a.   Enforce physical access authorizations for all physical access points (including designated entry and
             exit points) to areas where systems reside by:
             1.    Verifying individual access authorizations before granting access to the facility; and
             2.    Controlling ingress and egress to the facility using organization-defined physical access control
                   systems/devices;
        b.   Maintain physical access audit logs for organization-defined entry and exit points;
        c.   Control access to areas within the facility designated as publicly accessible by implementing
             organization-defined physical access controls;
        d.   Escort visitors and control visitor activity organization-defined circumstances requiring visitor escorts
             and control of visitor activity;
        e.   Secure keys, combinations, and other physical access devices;
        f.   Inventory physical access devices at least annually; and
        g.   Change combinations and keys at least annually and/or when keys are lost, combinations are
             compromised, or when individuals processing the keys or combinations are transferred or
             terminated.
PE-4 - Access Control for Transmission
        Control physical access to system distribution and transmission lines within organizational facilities using
        protective measures to control physical access to information system distribution and transmission lines,
        such as:
        a.   Locked wiring closets;
        b.   Disconnected or locked spare jacks; and
        c.   Protection of cabling by conduit or cable trays.
PE-5 - Access Control for Output Devices
        Control physical access to output from organization-defined output devices to prevent unauthorized
        individuals from obtaining the output.

PE-6 - Monitoring Physical Access
        a.   Monitor physical access to the facility where the system resides to detect and respond to physical
             security incidents;
        b.   Review physical access logs at least monthly and upon indications of inappropriate or unusual
             activity; and
        c.   Coordinate results of reviews and investigations with the organizational incident response capability.
        PE-6(1) - Monitoring Physical Access | Intrusion Alarms and Surveillance Equipment
        Monitor physical access to the facility where the system resides using physical intrusion alarms and
        surveillance equipment.
PE-8 - Visitor Access Records
        a.   Maintain visitor access records for the facility where the system resides for a minimum of one (1)
             year;
        b.   Review visitor access records at least monthly; and
        c.   Report anomalies in visitor access records to organization-defined personnel.
PE-9 - Power Equipment and Cabling
        Protect power equipment and power cabling for the system from damage and destruction.
PE-10 - Emergency Shutoff
        a.   Provide the capability of shutting off power to the system or individual system components in
             emergency situations;
        b.   Place emergency shutoff switches or devices in locations as defined by applicable standards, to
             facilitate safe and easy access for personnel; and
        c.   Protect emergency power shutoff capability from unauthorized activation.
PE-11 - Emergency Power
        Provide an uninterruptible power supply to facilitate an orderly shutdown of the system or transition of
        the system to long-term alternate power in the event of a primary power source loss.
PE-12 - Emergency Lighting
        Employ and maintain automatic emergency lighting for the system that activates in the event of a power
        outage or disruption and that covers emergency exits and evacuation routes within the facility.
PE-13 - Fire Protection
        Employ and maintain fire suppression and detection devices/systems that are supported by an
        independent energy source.
        PE-13(1) - Fire Protection | Detection Systems – Automatic Activation and Notification
        Employ fire detection systems that activate automatically and notify organization-defined personnel or
        roles and emergency responders in the event of a fire.

        PE-13(2) - Fire Protection | Suppression Systems — Automatic Activation and Notification
        a.   a. Employ fire suppression systems that activate automatically and notify organization-defined
             personnel or roles (including emergency responders); and
        b.   b. Employ an automatic fire suppression capability when the facility is not staffed on a continuous
             basis.
PE-14 - Environmental Controls
        a.   Maintain the temperature and humidity levels within the facility where the system resides within
             limits as documented by the equipment manufacturer; and
        b.   Monitor environmental control levels continuously.
PE-15 - Water Damage Protection
        Protect the system from damage resulting from water leakage by providing master shutoff or isolation
        valves that are accessible, working properly, and known to key personnel.
PE-16 - Delivery and Removal
        a.   Authorize and control all system components entering and exiting the facility; and
        b.   Maintain records of the system components.
PE-17 - Alternate Work Site
        a.   Determine and document the alternate worksites allowed for use by employees;
        b.   Employ statewide and agency security controls at alternate work sites;
        c.   Assess the effectiveness of security controls at alternate work sites; and
        d.   Provide a means to communicate with information security personnel in case of incidents.

## Cross-references

- Rests on: [ORS 276A.300](../../../../statutes/ors-276a.300.md)
- Required by: [DAS 107-004-052](../../policies/das-107-004-052.md)
- Framework: [NIST SP 800-53 Rev. 5](../../../../external-references/nist-sp-800-53-r5.md)
- Parent document: [Statewide IT Control Standards](../eis-css-itcs.md)

## Provenance & change history

- Source: shared snapshot `_meta/snapshots/eis-css-itcs.pdf` / `.txt` · retrieved
  2026-07-17 · sha256 `16985315fc10c902762c51c2a13e78eaf104ac6d6c58cc96eae4cbfdcd698d2a`
- See this knowledge body's [CHANGELOG](../CHANGELOG.md).
