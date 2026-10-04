# Compass — Privacy Policy

**Last Updated**: September 29, 2026  
**Effective Date**: September 29, 2026  

Welcome to **Compass** ("Compass", "we", "us", or "our"). We are committed to protecting your privacy and handling your personal data transparently, securely, and in compliance with global data protection regulations, including the European Union General Data Protection Regulation (GDPR), the California Consumer Privacy Act (CCPA), and the India Digital Personal Data Protection Act (DPDP Act).

This Privacy Policy explains what personal data we collect, why we collect it, how it is processed and stored, and your rights regarding your personal information.

---

## 1. Data Controller and Operator

- **Application**: Compass — Autonomous Productivity & Memory Assistant
- **Operator**: Compass Development Team
- **Contact Email**: privacy@compass.app / support@compass.app

---

## 2. Information We Collect

### A. Information You Provide
- **Account Identity**: When you select or enter an email address for account isolation, we associate your workspace data with that email or guest identifier.
- **Tasks & Commitments**: Task titles, domain classifications (hackathon, coursework, code, general), due dates, priorities, notes, descriptions, and duration estimates.
- **Conversation Content**: Prompts, messages, notes, and instructions you submit to the Compass AI copilot.
- **Connected Calendar Data**: If you explicitly connect your Google Calendar via OAuth, we retrieve free/busy availability time slots to prevent scheduling conflicts. We request **read-only** calendar access (`calendar.readonly`, `calendar.events.readonly`) and do not modify your external calendar events.

### B. Automatically Collected Information
- **Session & Identity Cookies**: We use essential cookies (`compass_user_id`, `compass_session`) with `SameSite=Lax` and `Secure` flags on HTTPS to preserve your workspace session and account selection across page reloads.
- **Local Storage**: Preferences, selected theme, and workspace memory preferences are cached in your browser's `localStorage`.
- **System Logs & Performance Metrics**: Request timestamps, anonymous client IP hashes for rate-limiting, and LLM token usage counts (input tokens, output tokens) for cost auditing.

---

## 3. Purpose and Legal Basis for Processing

We process your data under the following legal bases:
- **Contractual Necessity / Performance of Service**: Processing user prompts, tasks, and context memory is necessary to generate AI scheduling recommendations and maintain cross-session memory.
- **Legitimate Interests**: Rate limiting, fraud prevention, abuse monitoring, and error diagnostics.
- **Consent**: When you connect third-party integrations (such as Google Calendar) or opt into optional features. You may revoke consent at any time by disconnecting the service.

---

## 4. Third-Party Service Providers and Data Processors

To deliver autonomous AI assistance, Compass interacts with the following vetted third-party data processors:

| Provider | Purpose | Data Shared | Security & Location |
|----------|---------|-------------|---------------------|
| **Nebius Token Factory** | Frontier LLM inference (Nemotron-3 models) | User prompt, task context, conversation messages | TLS 1.3 in transit, ephemeral inference |
| **Neon Inc.** | Serverless PostgreSQL & pgvector storage | Encrypted OAuth tokens, task records, vector embeddings | Encrypted at rest (AES-256), TLS encrypted connections |
| **Tavily Technologies** | Real-time web search for fact/deadline verification | User search queries (abstain-first heuristic applied) | TLS encrypted query dispatch |
| **Google LLC** | Google Calendar Free/Busy availability | OAuth 2.0 credentials (encrypted at rest via HMAC-SHA256 authenticated cipher) | Read-only access; tokens revocable at any time |

> Compass does **not** sell, rent, or monetize your personal data. Your conversation content is never sold to third-party data brokers.

---

## 5. Data Security and Encryption

- **In Transit**: All API communication is conducted over HTTPS using modern TLS protocols with strict HTTP security headers (`Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Content-Security-Policy`).
- **At Rest**: Third-party OAuth tokens (such as Google Calendar refresh tokens) are encrypted at rest using an authenticated symmetric cipher (HMAC-SHA256) before database storage.
- **Isolation**: Workspaces and memory vectors are strictly partitioned by account identifier (`user_id`), preventing cross-tenant data leakage.

---

## 6. Data Retention and Deletion

- **Task & Memory Storage**: We retain tasks and memory chunks for as long as your workspace is active.
- **Stale Memory Roll-Up**: Automated background consolidation jobs flag overdue tasks and synthesize stale conversations to minimize data bloat.
- **Your Right to Erasure**: You can delete individual conversations, clear tasks, or disconnect calendar integrations directly from the user interface. To request full deletion of all data associated with your email, contact `privacy@compass.app`.

---

## 7. Your Privacy Rights

Depending on your jurisdiction (e.g., GDPR in the EEA/UK, CCPA in California, DPDP Act in India), you have the right to:
1. **Access**: Request a copy of the personal data we hold about you.
2. **Rectification**: Update or correct inaccurate task and profile records.
3. **Erasure ("Right to be Forgotten")**: Request deletion of your workspace data and memory embeddings.
4. **Data Portability**: Export your tasks and schedule in standard formats (JSON or RFC 5545 `.ics` iCalendar feed).
5. **Withdraw Consent**: Disconnect linked calendar services at any time.

---

## 8. Children's Privacy

Compass is not directed to individuals under the age of 13 (or under 16 in certain jurisdictions), and we do not knowingly collect personal data from children.

---

## 9. Changes to this Policy

We may update this Privacy Policy from time to time. Any material changes will be reflected with an updated "Last Updated" date at the top of this document.

---

## 10. Contact Us

If you have questions, concerns, or requests regarding this Privacy Policy or your data protection rights, please reach out to:
- **Email**: `privacy@compass.app`
