# LyraAuth Terms of Service

**Last updated: March 28, 2026**
**Service operated by:** Lyra Labs
**Contact:** legal@lyraauth.com

---

## 1. Overview

LyraAuth ("the Service") is a human verification system that replaces traditional CAPTCHA.
When users solve a LyraAuth challenge, they prove they are human AND contribute one labeled
example to training data for the Lyra AI language model.

By using LyraAuth (either as a website operator integrating the widget, or as an end user
solving a challenge), you agree to these Terms.

---

## 2. What LyraAuth Does

**For website operators (integrators):**
- Provides bot detection and human verification for your website
- Issues cryptographic tokens confirming a user is human
- Gives you a site key (public) and secret key (private) for verification

**For end users (people solving challenges):**
- Presents a short cognitive challenge (word completion, analogy, sentiment labeling, etc.)
- Records your answer as a labeled AI training data point
- Issues a verification token to the website you're accessing

---

## 3. Data Collection and AI Training

**This is fully disclosed:** By solving a LyraAuth challenge, you consent to your answer
being used as training data for the Lyra AI language model.

**What is collected:**
- Your answer to the challenge (e.g., "positive" for a sentiment question, or "east" for a word completion)
- The time taken to answer (used for bot detection — too fast = likely a bot)
- Your browser's user agent string (for bot detection)

**What is NOT collected:**
- Your name, email address, or any personally identifiable information
- Your IP address is not stored in training data
- Browsing history or cookies beyond the session

**How it is used:**
- Your answer, combined with the question, becomes one training example: `{"prompt": "...", "completion": "..."}`
- These examples are used to train and improve the Lyra AI language model
- Training data may be aggregated and shared with researchers

---

## 4. Website Operator Obligations

If you integrate LyraAuth on your website, you must:

1. **Disclose** to your users that LyraAuth collects answer data for AI training
2. **Link** to this Terms of Service and our Privacy Policy from your website's own privacy policy
3. **Not** attempt to reverse-engineer, scrape, or abuse the challenge system
4. **Not** use your secret key in client-side code (it must stay server-side)
5. **Comply** with applicable data protection laws (GDPR, CCPA, etc.) in your jurisdiction

---

## 5. Acceptable Use

You may NOT use LyraAuth to:
- Collect data from minors under 13 without verifiable parental consent
- Operate on websites containing illegal content
- Submit automated responses to farm verification tokens
- Use the API to scrape training data without authorization

---

## 6. Intellectual Property

- The Lyra AI model trained using LyraAuth data is owned by Lyra Labs
- The LyraAuth widget code is open-sourced under the MIT License (frontend JS only)
- The backend, challenge engine, and training pipeline remain proprietary

---

## 6A. Market Data and the Tremor Index

**Information only.** The Tremor Index and everything on the /market pages (scores, boom and bust probabilities, the bullish/bearish/neutral lean, causes, insider, fund and politician trades, and news headlines) is general market information. It is not financial, investment, tax or legal advice, and it is not a recommendation or offer to buy or sell any security.

**Not personalised.** Readings do not take your objectives, financial situation, holdings or risk tolerance into account. Lyra Labs is not authorised or regulated by the Financial Conduct Authority or registered as an investment adviser with the US Securities and Exchange Commission or any state.

**Experimental and unproven.** The probabilities come from a model whose weights were set by hand and are being adjusted as readings are graded. It has not been validated against historical data. Readings can and will be wrong. Past readings, hit rates or performance do not predict future results.

**Data sources.** Prices and the VIX are delayed daily closes from third-party sources. Insider trades and fund holdings come from public SEC filings; 13F holdings are filed up to 45 days after each quarter ends. Politician trades come from public disclosures, which are reported as value ranges and can be filed up to 45 days after the trade. Sources can be late, incomplete, wrong or unavailable; each reading shows which sources responded. We do not guarantee accuracy, completeness or timeliness.

**News.** We show headlines, short summaries and links to the publisher. Articles belong to their publishers.

**Your decisions.** You are solely responsible for any investment decision you make. Investments can fall as well as rise and you may lose some or all of the money you invest. Consider speaking to an independent, regulated financial adviser.

**Liability.** To the fullest extent permitted by law, Lyra Labs is not liable for any loss arising from use of, or reliance on, market information on the Service.

*Draft pending review by a financial-services lawyer.*

---

## 7. Disclaimer of Warranties

THE SERVICE IS PROVIDED "AS IS" WITHOUT WARRANTY OF ANY KIND. WE DO NOT GUARANTEE
100% BOT DETECTION ACCURACY. USE AT YOUR OWN RISK.

---

## 8. Limitation of Liability

IN NO EVENT SHALL Lyra Labs BE LIABLE FOR ANY INDIRECT, INCIDENTAL,
SPECIAL, OR CONSEQUENTIAL DAMAGES ARISING FROM USE OF THIS SERVICE.

---

## 9. Governing Law

These Terms are governed by the laws of Delaware, USA.
Disputes shall be resolved in the courts of Delaware, USA.

---

## 10. Changes

We may update these Terms at any time. Continued use constitutes acceptance.
Material changes will be communicated via email to registered site operators.

---

*This document was prepared for informational purposes. Consult a qualified attorney
to review before deploying LyraAuth commercially.*
