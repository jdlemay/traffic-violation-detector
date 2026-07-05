# 06 · Legal, Ethical & Privacy Considerations

**This is not legal advice.** It is an engineering checklist of the issues you
must resolve with your own counsel before deploying a device that records other
people on public roads and reads their license plates. Laws vary by
country/state and change; treat everything here as "things to verify," not
"settled rules."

## 1. The core reframing

A privately operated camera **cannot issue citations**. Only authorized
government systems (and specific state-sanctioned programs) can. So the honest,
defensible purpose of this device is:

- **Your own evidence** for a crash, dispute, or insurance claim.
- **Driver-safety coaching** (your own driving, or a fleet you operate).
- **Situational recording**, like any dashcam.

Marketing or operating it as a way to "catch" and report other drivers invites
legal exposure (harassment, stalking, privacy, defamation if OCR is wrong) and is
out of scope for this project. The Tier-3 "other vehicle" detectors are advisory
analytics, explicitly not enforcement.

## 2. Recording & consent

- **Dashcams (video) on public roads** are broadly legal in most US states and
  many countries, because there's no reasonable expectation of privacy in public.
- **Audio** is the sharp edge: many US states are **two-party (all-party)
  consent** for audio recording. Default this build to **video-only** (no cabin
  or external mic) unless you have a specific, consented reason. The config ships
  with audio disabled.
- Some jurisdictions (e.g. parts of the EU/UK under GDPR) treat dashcam footage of
  identifiable people/plates as **personal data**, imposing purpose-limitation,
  minimization, and retention duties. If you're there, that changes storage and
  sharing obligations materially.

## 3. License plates & ALPR

- Reading and **storing plate numbers** turns footage into a searchable database
  of people's movements — the most privacy-sensitive part of this project.
- Minimize: only run OCR **attached to an actual event**, not continuously on
  every passing car. Don't build a rolling plate-tracking log.
- Consider storing the **plate image crop** for human review rather than a
  machine-decoded string in a searchable field, and/or hashing plate strings.
- Some jurisdictions restrict private ALPR databases specifically — check.

## 4. Windshield mounting laws

Many US states regulate windshield obstructions and where devices may be mounted
(e.g. below a certain area, in specific corners). A camera placed illegally can
itself be a citable offense and can undermine the footage's usefulness. Verify
your state's vehicle code and mount accordingly (see
[`03-hardware-bom.md`](03-hardware-bom.md#4-mounting--placement-also-a-legal-matter)).

## 5. Evidence integrity (so footage is actually useful)

- Timestamp from GPS/NTP, not just the RTC; store UTC.
- Hash each clip (SHA-256 in the DB) so tampering is detectable.
- Keep the original alongside any exported/annotated copy.
- Don't overwrite flagged event clips until the retention window expires.

## 6. Data security & retention (built into config)

`config/config.yaml` exposes:
- `privacy.audio_enabled: false` (default off)
- `privacy.alpr_on_event_only: true` (no continuous plate logging)
- `privacy.retention_days` for auto-purge of non-flagged footage
- `privacy.encrypt_archive` hook (LUKS/at-rest encryption of the SSD is
  recommended if the vehicle isn't physically secure)
- `privacy.blur_faces` / `blur_plates` hooks for any exported/shared copies

Recommended defaults: encrypt the archive SSD at rest, auto-purge routine footage
after a short window (e.g. 7–14 days), and keep only flagged events longer. Never
sync raw footage to a cloud without a clear, consented purpose and encryption in
transit and at rest.

## 7. If you ever add cloud/fleet

- Add a Data Protection Impact Assessment step.
- Region-restrict storage as required (GDPR data residency, etc.).
- Provide a deletion path (subject access / erasure requests where applicable).
- Access controls + audit logs on who viewed plate data.

## 8. Bottom line for this repo

The software defaults to the **privacy-protective** configuration: video-only,
event-scoped ALPR, local storage, retention purge, integrity hashing. Loosening
any of those is a deliberate, documented choice you make with knowledge of your
jurisdiction — not the default.
