# Twilight Discord Bot - Privacy Policy


<sub>Last updated: 20 May, 2026</sub>

## 1. Introduction

Dopamine Studios (“**we**,” “**us**,” or “**our**”) operates **Twilight**, a free Discord AI chatbot. This Privacy Policy explains what information we process when you use Twilight, how we use it, who we share it with, and what choices you have.

This policy applies to the **official hosted Twilight bot** operated by Dopamine Studios. If you interact with a **self-hosted** copy of Twilight run by someone else, that operator’s privacy practices apply instead.

By using Twilight, you agree to this Privacy Policy. If you do not agree, please do not use the Service.

---

## 2. Information We Process

### 2.1 Information from Discord

When you use Twilight, Discord provides us with information needed to operate the bot, such as:

- your **Discord user ID**, **username**, and **display name**;
- **message content** you send (including mentions, replies, and quoted messages);
- **channel, server (guild), and message IDs**;
- **attachments** you include (for example, images and documents);
- **server roles and permissions** (for example, to enforce admin-only commands); and
- standard Discord metadata required for bot functionality.

We do not ask for your real name, email address, or postal address to use Twilight. Discord may already hold that information under Discord’s own privacy policy.

### 2.2 Conversation session data (temporary memory)

To provide conversational context, Twilight keeps a **temporary, in-memory session** of recent messages:

| Context | How session data is scoped |
|:--------|:--------------------------|
| **Direct messages (DMs)** | Per DM channel |
| **Servers** | Per Discord server (guild)—session context may be **shared across users** in that server |

Session data includes your prompts, quoted context, attachments processed for the model, and the bot’s replies.

**We do not permanently store chat logs on disk for training or marketing.** Session data lives in server memory and is discarded when:

- you run `/clear dm` or (in servers) an administrator runs `/clear server`;
- the session expires after approximately **one (1) hour of inactivity**; or
- the bot process restarts or is redeployed.

We also trim very long sessions to stay within model token limits (roughly **16,000 tokens** of context, estimated from message size).

### 2.3 Attachments

If you send images or files (Twilight does not process audio or video attachments), we may download them temporarily to send them to our AI provider for analysis. Temporary files are not intended for long-term retention.

**Do not send sensitive personal, financial, or health information** unless you accept the risks described in this policy.

### 2.4 Diagnostics and operations

To keep Twilight reliable, we process limited operational data, such as:

- **API latency samples** (used for `/latency graph` and internal monitoring);
- **uptime and resource usage** (for example, CPU, memory, and host status shown in diagnostics);
- **error and warning logs** (for example, failed API retries); and
- coarse **host location** derived from IP geolocation (country/city) for diagnostic displays.

These logs are meant for operations and abuse prevention, not for profiling you for advertising.

### 2.5 Information we do not sell

We **do not sell** your personal information. We **do not use** your conversations to build advertising profiles.

---

## 3. How We Use Information

We use the information described above to:

1. receive your messages and deliver AI-generated replies on Discord;
2. maintain short-term conversation context within a session;
3. process attachments you choose to send;
4. enforce rate limits, cooldowns, and fair-use protections;
5. operate diagnostic commands (`/ping`, `/latency graph`);
6. maintain security, debug failures, and improve reliability; and
7. comply with law and protect users, Discord, and our infrastructure.

We do **not** use your chats to train our own proprietary models. However, **third-party AI providers** may process data under their own policies (see Section 5).

---

## 4. Legal Bases (EEA/UK users)

If you are in the European Economic Area or the United Kingdom, we process personal data on the following bases:

| Purpose | Legal basis |
|:--------|:------------|
| Providing the chatbot service you request | **Contract** / steps at your request |
| Security, abuse prevention, and reliability | **Legitimate interests** (balanced against your rights) |
| Compliance with legal obligations | **Legal obligation** |
| Optional improvements where consent is required | **Consent** (where applicable) |

You may object to processing based on legitimate interests as described in Section 9.

---

## 5. Third-Party Processors and Sharing

We share information only as needed to run Twilight:

| Recipient                                           | Role | Relevant policies                                                                                                                 |
|:----------------------------------------------------|:-----|:----------------------------------------------------------------------------------------------------------------------------------|
| **Discord Inc.**                                    | Messaging platform; hosts your account and messages | [Discord Privacy Policy](https://discord.com/privacy)                                                                             |
| **Google** (Google AI Studio / Gemini & Gemma APIs) | AI inference; optional **Google Search** grounding for some queries | [Google Privacy Policy](https://policies.google.com/privacy) · [Google AI / Gemini terms](https://ai.google.dev/gemini-api/terms) |
| **Render (Hosting Provider)**                       | Running the bot application | [Render Privacy Policy](https://render.com/privacy)                                                                                                         |

When you send a message, relevant content (including display name, message text, quotes, and attachments) may be transmitted to **Google** to generate a response. Google applies its own safety filters and retention practices.

We may also disclose information if required by law, court order, or governmental request, or when we believe disclosure is necessary to protect rights, safety, or security.

We do **not** share your data with data brokers or advertising networks for their independent marketing use.

---

## 6. International Transfers

Twilight may be operated from infrastructure located outside your country. Discord and Google also process data globally.

Where required, we rely on appropriate safeguards for international transfers (such as standard contractual clauses offered by processors, or equivalent mechanisms).

---

## 7. Retention

| Data type | Typical retention |
|:----------|:------------------|
| Conversation session (in memory) | Until cleared, ~1 hour of inactivity, or process restart |
| Cooldown / rate-limit state | Short-term, in memory |
| Latency diagnostics cache | Rolling window (~24 hours of aggregated samples for graphs) |
| Operational logs | Limited period for troubleshooting and security, then deleted or rotated |

We keep information longer only when necessary for legal compliance, dispute resolution, or security investigations.

---

## 8. Security

We use reasonable technical and organizational measures to protect information processed by Twilight, including access controls on hosting infrastructure and minimizing stored data.

No method of transmission or storage is 100% secure. You are responsible for what you choose to share in Discord channels and DMs.

---

## 9. Your Rights and Choices

Depending on where you live, you may have rights to:

- **access** personal data we hold about you;
- **correct** inaccurate data;
- **delete** data or restrict processing;
- **object** to certain processing;
- **port** data you provided; and
- **withdraw consent** where processing is consent-based.

**Practical controls in Twilight:**

- **DM history:** use `/clear dm`
- **Server history:** server administrators may use `/clear server`
- **Stop using the bot:** remove Twilight from your server or block/stop DMs

To exercise privacy rights, contact us via the channels in Section 12. We may need to verify your request through Discord.

If you are in the EEA/UK and believe we have not addressed your concern, you may lodge a complaint with your local data protection authority.

**California residents:** We do not sell personal information. You may request access or deletion as described above.

---

## 10. Children’s Privacy

Twilight is not directed at children under 13 (or the minimum age required by Discord and your local law). We do not knowingly collect personal information from children below that age. If you believe a child has provided personal information through Twilight, contact us and we will take appropriate steps.

---

## 11. Automated Decision-Making

Twilight uses automated systems (AI models) to generate responses. These outputs are probabilistic and may be incorrect. We do not use Twilight to make legally significant solely automated decisions about you.

---

## 12. Changes to This Policy

We may update this Privacy Policy from time to time. We will update the “Last updated” date and, where appropriate, provide notice through our [website](https://twilight.dopaminestudios.in/) or [support Discord](https://discord.gg/xT4RVAADeU).

---

## 13. Contact Us

**Dopamine Studios — Twilight**

- Email: [hey@dopaminestudios.in](https://mailto:hey@dopaminestudios.in/)
- Website: [https://twilight.dopaminestudios.in/](https://twilight.dopaminestudios.in/)
- Support Discord: [https://discord.gg/xT4RVAADeU](https://discord.gg/xT4RVAADeU)
- Source code: [https://github.com/dopaminestudios/twilight/](https://github.com/dopaminestudios/twilight/)

For privacy requests, contact us through the email. Please include enough information for us to locate your request (for example, Discord username and approximate date of use).
