# COSHH AI — build prompt (paste into ChatGPT, Claude, or any coding agent)

You are a senior full-stack engineer and UK health-and-safety domain expert. Build **COSHH AI**, a web app and mobile app that turns Safety Data Sheets (SDS) into COSHH risk assessments for UK workplaces. Work in small, testable steps. Before writing code, give me the architecture, data model and a milestone plan, then build milestone 1.

## Who it is for
Safety managers, lab managers, facilities teams, cleaning contractors, schools and small manufacturers who must comply with the **Control of Substances Hazardous to Health Regulations 2002 (COSHH)** and use **HSE EH40/2005 Workplace Exposure Limits** (current edition).

## Core workflow
1. **Upload**: PDF SDS (digital or scanned), photo of a product label, or pasted text. Batch upload up to 50 files.
2. **Extract** (LLM with structured output plus OCR fallback): product name, supplier, revision date, CAS/EC numbers per component with % ranges, GHS/CLP hazard pictograms, signal word, H-statements, P-statements (SDS sections 2, 3, 7, 8, 9, 10, 11, 13, 14), physical state, flash point, vapour pressure, exposure routes. Every extracted field stores **the page and quote it came from**.
3. **Look up WELs** from a versioned, stored EH40 table (never from model memory): 8-hr TWA and 15-min STEL in ppm and mg/m³, plus Sk (skin), Sen (sensitiser) and Carc notations.
4. **Assess risk**: the user enters the task (activity, quantity, frequency, duration, people exposed, including vulnerable groups, existing controls). Score likelihood × severity per route (inhalation, skin, eyes, ingestion), and apply the hierarchy of control (eliminate → substitute → engineering/LEV → admin → PPE).
5. **Recommend controls and PPE** with standards: gloves EN ISO 374 (material plus breakthrough time from SDS section 8), eye EN 166, RPE EN 140/143/149 with APF, LEV thorough examination every 14 months, and health surveillance triggers.
6. **Human sign-off**: a competent person must review, edit and approve. The AI never marks an assessment as final. Show "Draft — not reviewed" until signed.
7. **Output**: branded PDF and DOCX assessment, a site **COSHH register** (all substances, locations, review dates), and a one-page "safe use sheet" for workers.
8. **Lifecycle**: review dates (default 12 months), SDS revision alerts, an audit trail of who changed what, and version history.

## Must-haves
- Multi-tenant: organisations → sites → locations → substances. Roles: admin, assessor, viewer, worker (read-only safe use sheets via QR code on the cabinet).
- Confidence score per field. Low confidence or conflicting values are highlighted for the human.
- Flag CMRs (carcinogens, mutagens, reproductive toxins), asthmagens, and substances with Sk notation.
- Search and filter the register by hazard, location, review overdue, or missing SDS.
- UK GDPR: data in UK/EU region, DPA, export and delete per org, no training on customer documents.
- Accessibility WCAG 2.2 AA; works offline on mobile for viewing safe use sheets.

## Tech stack (change only with a reason)
- Web: Next.js (App Router) + TypeScript + Tailwind + shadcn/ui.
- Mobile: Expo / React Native sharing types and API client with the web app.
- API: FastAPI (Python) or Next.js route handlers; Postgres with row-level security per org; object storage for SDS files; background job queue for extraction.
- AI: an LLM with JSON-schema structured output for extraction; OCR (e.g. Tesseract or a cloud OCR) for scans; all prompts and model versions logged per assessment.
- Payments: Stripe subscriptions (Starter / Pro / Business), 14-day trial.
- Tests: unit tests for the risk scoring and WEL lookup, golden-file tests on 10 real public SDS PDFs, Playwright end-to-end tests for upload → assessment → sign-off → PDF.

## Guardrails
- Never invent a WEL, CAS number or H-statement. If it's not in the SDS or the EH40 table, say "Not found" and ask the user.
- Include the disclaimer: assessments are decision support and must be reviewed by a competent person (COSHH Regulation 6).
- Keep the regulation references accurate and cite the regulation or EH40 entry next to each requirement.

## Deliverables for milestone 1
Repository scaffold, database schema plus migrations, SDS upload → extraction → editable review screen for one substance, EH40 lookup from a seed table, and a PDF export. Include setup instructions, `.env.example` and tests. Then stop and show me.
