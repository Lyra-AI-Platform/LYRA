# LyraAuth Data Processing Agreement (DPA)

**Between:** Lyra Labs ("LyraAuth Provider")
**And:** The website operator registering to use LyraAuth ("Data Controller")
**Date:** March 28, 2026

This DPA governs processing of personal data via the LyraAuth service and is
required for GDPR compliance in EU/UK deployments.

---

## 1. Roles

- **Data Controller:** The website operator who integrates LyraAuth and determines
  the purpose of processing (human verification on their site).
- **Data Processor:** LyraAuth Provider, who processes data on behalf of the Controller.

---

## 2. Subject Matter of Processing

**Categories of data subjects:** End users of the Controller's website.

**Categories of personal data:**
- Challenge responses (short text or multiple-choice selections)
- Session identifiers (randomly generated, non-identifying)
- Browser user agent strings

**Purpose:** Human verification (bot detection) and AI model training data collection.

**Duration:** Processing continues for the duration of the service agreement.

---

## 3. Instructions from Controller

LyraAuth Provider shall process data only on documented instructions from the Controller.
The Controller instructs LyraAuth Provider to:
1. Process challenge responses for bot/human classification
2. Store anonymized responses as AI training data
3. Issue verification tokens to confirmed human users

---

## 4. Confidentiality

LyraAuth Provider ensures that all personnel authorized to process data are subject
to confidentiality obligations.

---

## 5. Security Measures

LyraAuth Provider implements:
- HTTPS encryption for all data in transit
- AES-256 encryption for data at rest
- Access controls limiting data access to authorized systems only
- Regular security reviews

---

## 6. Sub-processors

LyraAuth Provider may use the following sub-processors:
- Cloud hosting providers (for API infrastructure)
- CDN providers (for widget distribution)

The Controller will be notified of any changes to sub-processors.

---

## 7. Data Subject Rights Assistance

LyraAuth Provider will assist the Controller in responding to data subject requests
(access, erasure, portability) within 72 hours of request.

---

## 8. Deletion

Upon termination of service:
- Session data: deleted within 30 days
- Anonymized training records: retained (no personal data linkage possible)
- Secret keys: invalidated immediately

---

## 9. Audit Rights

The Controller may audit LyraAuth Provider's compliance with this DPA once per year
with 30 days' notice.

---

## 10. Liability

Each party is liable for damages caused by their failure to comply with GDPR obligations.

---

**By registering for LyraAuth, the website operator accepts this DPA.**

---

*Have your legal counsel review this DPA before deploying LyraAuth in EU/UK markets.*
