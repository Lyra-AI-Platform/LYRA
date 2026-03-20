# Lyra AI Platform — Privacy Policy

**Effective Date:** January 1, 2026
**Last Updated:** March 2026
**Version:** 1.0

---

## Overview

Lyra is a **locally-running AI platform**. By default, it runs entirely on your device with zero data leaving your machine. This Privacy Policy explains what data Lyra does and does not collect, and the limited, optional data sharing available through the Collective Intelligence feature.

---

## 1. What Lyra Does NOT Collect — Ever

Regardless of any settings or opt-ins, Lyra **never** collects, stores, or transmits:

| Category | Examples |
|----------|---------|
| **Conversation content** | Your messages, questions, AI responses |
| **File contents** | Uploaded PDFs, code, images, documents |
| **Personal identifiers** | Name, email, phone number, username |
| **Location data** | IP address, GPS, city, country |
| **Device fingerprints** | Browser info, hardware IDs, MAC address |
| **System information** | File paths, installed software, OS details |
| **Behavioral tracking** | Keystrokes, mouse movements, session recordings |
| **Authentication data** | Passwords, tokens, API keys |

---

## 2. Data Stored Locally on Your Device

Lyra stores the following **only on your own machine** — it never leaves your device unless you explicitly opt in to the Collective Intelligence feature:

### 2a. Conversation Memory (ChromaDB Vector Database)
- **What:** Semantic summaries of conversations (topic-level, not verbatim messages)
- **Where:** `data/memory/` on your local machine
- **Purpose:** Allows Lyra to remember context across sessions
- **Control:** You can view, search, or delete all memories at any time from the Memory panel
- **Sharing:** Never shared externally under any circumstances

### 2b. Downloaded AI Models
- **What:** Open-source language model files (GGUF or HuggingFace format)
- **Where:** `data/models/` on your local machine
- **Purpose:** Running AI locally without internet
- **Sharing:** Never transmitted externally

### 2c. Uploaded Files
- **What:** Files you upload for analysis
- **Where:** `data/uploads/` on your local machine
- **Purpose:** AI analysis during your session
- **Sharing:** Never transmitted externally

### 2d. Auto-Learning Knowledge Base
- **What:** Web article text crawled by Lyra's autonomous learner
- **Where:** `data/memory/` in your ChromaDB database
- **Purpose:** Improving Lyra's knowledge over time
- **Sharing:** Never transmitted externally

### 2e. Application Logs
- **What:** Server startup/shutdown events, error messages
- **Where:** `data/logs/` on your local machine
- **Sharing:** Never transmitted externally

---

## 3. Collective Intelligence — Opt-In Data Sharing

Lyra includes an **entirely optional** Collective Intelligence feature. This is **disabled by default** and requires your explicit consent to activate.

### 3a. What Is Collective Intelligence?

When enabled, your Lyra instance anonymously contributes topic keywords to a community pool. In return, you receive trending topics that the community is exploring, which Lyra can pre-learn about to answer your future questions better.

Think of it like an anonymous suggestion box: you submit broad subject interests (e.g., "machine learning", "climate science"), and the community pool reveals what subjects are most popular — without knowing who asked what.

### 3b. What Is Shared (Opt-In Only)

When you opt in, the following is sent to the Lyra community server approximately once per day:

| Data Field | Example | Purpose |
|-----------|---------|---------|
| `installation_id` | `a3f9b12c...` (random hex) | Prevent duplicate counting |
| `lyra_version` | `1.0.0` | Compatibility tracking |
| `week_usage_count` | `47` | Aggregate usage statistics |
| `topics` | `["python", "machine learning"]` | Community knowledge pool |
| `submitted_at` | `2026-03-20` | Date only, no timestamp |

### 3c. What Is Never Shared — Even With Opt-In

Even with Collective Intelligence enabled, the following is **never transmitted**:

- ❌ Your actual conversation messages
- ❌ Your name, email, or any personal identifier
- ❌ Your IP address (stripped at the server level)
- ❌ Topics that appear personal (e.g., beginning with "my", "I", email patterns)
- ❌ File contents
- ❌ Your geographic location
- ❌ Browser or device information

### 3d. The Installation ID

The `installation_id` is:
- A randomly generated 32-character hex string (e.g., `a3f9b12c8e4d1a7b2c9f0e5d3a8b1c4e`)
- Generated locally on your machine when you opt in
- **Not linked to your name, email, IP address, or any personal information**
- **Cannot be used to identify you** — it is purely a statistical deduplication token

### 3e. Opting Out

You can opt out at any time through:
- The Lyra settings panel → Privacy & Sharing → Disable Collective Intelligence
- Or via the API: `POST /api/telemetry/opt-out`

**On opt-out:**
- All pending topic data is immediately deleted from local storage
- Your installation ID is permanently deleted
- No further data is sent
- Your past contributions (anonymous topic keywords) remain in the aggregate community pool, but cannot be identified or removed since they were never linked to you

---

## 4. Community Server Data Handling

The Lyra community server (hosted separately):

- **Receives:** Anonymous topic keyword lists + random installation IDs
- **Stores:** Aggregate topic frequency counts only
- **Does not store:** Any individual submissions after aggregation
- **IP addresses:** Stripped immediately upon receipt — not logged
- **Retention:** Aggregated topic counts retained for 90 days, then deleted
- **Access:** Aggregate trend data is publicly readable by all Lyra instances

---

## 5. Third-Party Services

### 5a. Web Search (When Enabled)
When you enable web search in Lyra, search queries are sent to DuckDuckGo. DuckDuckGo's own privacy policy applies. Lyra does not send queries to Google, Bing, or other tracking-based search engines by default.

### 5b. Model Downloads
Downloading AI models from HuggingFace Hub is subject to HuggingFace's privacy policy. Lyra accesses only public model repositories.

### 5c. RSS Feeds
Lyra's auto-learner fetches public RSS feeds. This is equivalent to visiting those websites in a browser. No personal data is sent.

---

## 6. Children's Privacy

Lyra is not intended for use by children under 13 years of age. We do not knowingly collect any information from children.

---

## 7. Security

Lyra's data (models, memory, uploads) is stored unencrypted in the `data/` directory on your local machine. You are responsible for securing your own device. We recommend:
- Using full-disk encryption on your device
- Not sharing your Lyra `data/` directory
- Regularly clearing uploaded files after use

---

## 8. Your Rights

You have the right to:
- **Access:** View all data stored by Lyra (it's all in your `data/` folder)
- **Delete:** Clear memory, uploads, and logs at any time through the UI or by deleting the `data/` folder
- **Opt out:** Disable Collective Intelligence at any time with immediate effect
- **Transparency:** This policy is written in plain language and the full source code is available for inspection

---

## 9. Changes to This Policy

We will update this policy as Lyra's features evolve. Changes will be reflected in the `PRIVACY_POLICY.md` file in the repository and announced in release notes.

---

## 10. Contact

For privacy questions or concerns:

**Project:** Lyra AI Platform
**GitHub:** https://github.com/your-username/lyra
**Email:** [your-email@example.com]

---

## Summary (Plain English)

- ✅ **Lyra runs 100% locally by default**
- ✅ **Your conversations are private — always**
- ✅ **Collective Intelligence is off by default — you must turn it on**
- ✅ **Even when on, only anonymous topic keywords are shared**
- ✅ **Your IP is never stored on our server**
- ✅ **You can opt out anytime and all your data is cleared**
- ✅ **No ads, no selling of data, no tracking**
