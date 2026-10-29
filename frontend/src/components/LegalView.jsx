import React, { useEffect } from 'react'
import { ArrowLeft, Shield, FileText, Sun, Moon } from 'lucide-react'

export default function LegalView({
  type = 'terms',
  onBack,
  onSelectTab,
  isDarkMode = false,
  onToggleDarkMode,
}) {
  const isTerms = type === 'terms'

  useEffect(() => {
    const originalTitle = document.title
    document.title = isTerms ? 'Compass — Terms of Service' : 'Compass — Privacy Policy'
    window.scrollTo(0, 0)
    return () => {
      document.title = originalTitle
    }
  }, [isTerms])

  return (
    <div
      style={{
        minHeight: '100vh',
        background: 'var(--bg-app)',
        color: 'var(--text-primary)',
        padding: '32px 20px 80px',
        boxSizing: 'border-box',
      }}
    >
      <div
        style={{
          maxWidth: '820px',
          margin: '0 auto',
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-card, 10px)',
          padding: '32px',
          boxShadow: 'var(--shadow-sm)',
        }}
      >
        {/* Navigation & Header Controls */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '12px',
            marginBottom: '28px',
            paddingBottom: '16px',
            borderBottom: '1px solid var(--border)',
          }}
        >
          <button
            type="button"
            onClick={onBack || (() => onSelectTab && onSelectTab('dashboard'))}
            className="btn-secondary"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px',
              padding: '8px 14px',
              borderRadius: 'var(--radius-btn, 6px)',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
              minHeight: '38px',
            }}
          >
            <ArrowLeft size={15} strokeWidth={2} />
            <span>Back to Compass</span>
          </button>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <button
              type="button"
              onClick={() => onSelectTab && onSelectTab('terms')}
              className={isTerms ? 'btn-primary-amber' : 'btn-secondary'}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '6px 12px',
                borderRadius: 'var(--radius-btn, 6px)',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
                minHeight: '34px',
              }}
            >
              <FileText size={14} />
              <span>Terms</span>
            </button>
            <button
              type="button"
              onClick={() => onSelectTab && onSelectTab('privacy')}
              className={!isTerms ? 'btn-primary-amber' : 'btn-secondary'}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '6px 12px',
                borderRadius: 'var(--radius-btn, 6px)',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
                minHeight: '34px',
              }}
            >
              <Shield size={14} />
              <span>Privacy</span>
            </button>
            {onToggleDarkMode && (
              <button
                type="button"
                onClick={onToggleDarkMode}
                className="btn-secondary"
                aria-label="Toggle dark mode"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  width: '34px',
                  height: '34px',
                  padding: 0,
                  borderRadius: 'var(--radius-btn, 6px)',
                  cursor: 'pointer',
                }}
              >
                {isDarkMode ? <Sun size={15} /> : <Moon size={15} />}
              </button>
            )}
          </div>
        </div>

        {/* Content Body */}
        {isTerms ? <TermsContent onSelectTab={onSelectTab} /> : <PrivacyContent onSelectTab={onSelectTab} />}
      </div>
    </div>
  )
}

function TermsContent({ onSelectTab }) {
  return (
    <article style={{ lineHeight: 1.65, fontSize: '14.5px' }}>
      <div style={{ marginBottom: '20px' }}>
        <h1 style={{ fontSize: '26px', fontWeight: 800, margin: '0 0 6px 0', letterSpacing: '-0.4px' }}>
          Compass — Terms of Service
        </h1>
        <div style={{ fontSize: '12.5px', color: 'var(--text-muted)' }}>
          Last Updated: October 29, 2026 · Effective Date: October 29, 2026
        </div>
      </div>

      <div
        style={{
          background: 'rgba(245, 166, 35, 0.1)',
          border: '1px solid rgba(245, 166, 35, 0.35)',
          borderRadius: '8px',
          padding: '14px 16px',
          marginBottom: '24px',
          fontSize: '13px',
          color: 'var(--text-primary)',
        }}
      >
        <strong>Legal Review Notice:</strong> This plain draft describes what Compass actually does (task management, AI copilot, calendar integration, and web research). Placeholders for legal entity name, jurisdiction, and contact email are marked in brackets for counsel review.
      </div>

      <p>
        Welcome to <strong>Compass</strong>, operated by <strong>[Company / Operator Legal Name: Pending Legal Review]</strong> (&quot;we&quot;, &quot;us&quot;, or &quot;Compass&quot;). By accessing or using the Compass web application, APIs, or services (collectively, the &quot;Service&quot;), you agree to be bound by these Terms of Service (&quot;Terms&quot;). If you do not agree to these Terms, please do not use the Service.
      </p>

      <h2 style={{ fontSize: '18px', fontWeight: 700, marginTop: '24px', marginBottom: '8px' }}>
        1. Description of Service
      </h2>
      <p>
        Compass is an autonomous AI productivity copilot and memory layer designed to help users track tasks, schedule deadlines, synthesize context, and coordinate multi-agent research workflows using large language models and cloud storage.
      </p>

      <h2 style={{ fontSize: '18px', fontWeight: 700, marginTop: '24px', marginBottom: '8px' }}>
        2. Eligibility &amp; Account Usage
      </h2>
      <ul>
        <li>You must be at least 13 years old (or 16 in certain jurisdictions) to use Compass.</li>
        <li>You are responsible for maintaining the confidentiality of any authorization tokens or account credentials associated with your session.</li>
        <li>You agree not to forge headers (such as <code>x-user-id</code>) or attempt unauthorized access to other users&apos; isolated workspaces (IDOR attacks).</li>
      </ul>

      <h2 style={{ fontSize: '18px', fontWeight: 700, marginTop: '24px', marginBottom: '8px' }}>
        3. Acceptable Use Policy
      </h2>
      <p>You agree not to use Compass to:</p>
      <ol>
        <li>Violate any applicable local, state, national, or international law.</li>
        <li>Probe, scan, or test the vulnerability of any system, network, or database without prior authorization.</li>
        <li>Submit prompts or content intended to generate malicious code, malware, phishing materials, or hate speech.</li>
        <li>Exceed published rate limits, launch denial-of-service (DoS) attacks, or disrupt the integrity of shared infrastructure.</li>
        <li>Reverse engineer or extract proprietary models or system prompts in violation of third-party terms.</li>
      </ol>

      <h2 style={{ fontSize: '18px', fontWeight: 700, marginTop: '24px', marginBottom: '8px' }}>
        4. Artificial Intelligence &amp; Content Accuracy Disclaimer
      </h2>
      <div
        style={{
          background: 'var(--bg-app)',
          borderLeft: '4px solid var(--brand)',
          padding: '12px 16px',
          borderRadius: '4px',
          marginBottom: '16px',
        }}
      >
        <p style={{ margin: 0, fontWeight: 600 }}>IMPORTANT NOTICE REGARDING AI OUTPUTS:</p>
        <p style={{ margin: '6px 0 0 0', fontSize: '13.5px' }}>
          Compass utilizes frontier generative artificial intelligence models (hosted on Nebius Token Factory).
        </p>
        <ul style={{ margin: '8px 0 0 0', paddingLeft: '20px', fontSize: '13.5px' }}>
          <li><strong>Probabilistic Outputs:</strong> AI outputs, schedule suggestions, research summaries, and task recommendations are probabilistic estimates. They may occasionally contain factual errors, misinterpretations of deadlines, or scheduling conflicts.</li>
          <li><strong>Human Verification:</strong> Users are solely responsible for verifying critical commitments, academic deadlines, legal notices, and production schedules before taking action.</li>
          <li><strong>Advisory Nature:</strong> Specialized agent results (e.g., coursework triage, research briefs) are advisory only and require explicit human confirmation for any mutating action.</li>
        </ul>
      </div>

      <h2 style={{ fontSize: '18px', fontWeight: 700, marginTop: '24px', marginBottom: '8px' }}>
        5. Third-Party Integrations
      </h2>
      <p>Compass integrates with third-party platforms, including:</p>
      <ul>
        <li><strong>Nebius Token Factory:</strong> LLM inference</li>
        <li><strong>Neon:</strong> Serverless PostgreSQL and vector database</li>
        <li><strong>Tavily Search:</strong> Web research and search API</li>
        <li><strong>Google Calendar:</strong> OAuth 2.0 calendar availability (read-only free/busy slots)</li>
      </ul>
      <p>
        Your use of these third-party services is subject to their respective terms and privacy policies. We are not responsible for the availability, uptime, or behavior of external third-party providers.
      </p>

      <h2 style={{ fontSize: '18px', fontWeight: 700, marginTop: '24px', marginBottom: '8px' }}>
        6. Intellectual Property
      </h2>
      <ul>
        <li><strong>Your Content:</strong> You retain ownership of all tasks, notes, documents, and messages you submit to the Service.</li>
        <li><strong>Compass Platform:</strong> The Compass software, user interface design, logos, and documentation are protected by copyright and intellectual property laws. Compass is open-sourced under the MIT License as specified in the repository <code>LICENSE</code> file.</li>
      </ul>

      <h2 style={{ fontSize: '18px', fontWeight: 700, marginTop: '24px', marginBottom: '8px' }}>
        7. Disclaimer of Warranties
      </h2>
      <p style={{ fontSize: '13px', textTransform: 'uppercase', color: 'var(--text-secondary)' }}>
        THE SERVICE IS PROVIDED &quot;AS IS&quot; AND &quot;AS AVAILABLE&quot; WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED, INCLUDING, BUT NOT LIMITED TO, IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT. WE DO NOT WARRANT THAT THE SERVICE WILL BE UNINTERRUPTED, TIMELY, SECURE, OR ERROR-FREE.
      </p>

      <h2 style={{ fontSize: '18px', fontWeight: 700, marginTop: '24px', marginBottom: '8px' }}>
        8. Limitation of Liability
      </h2>
      <p style={{ fontSize: '13px', textTransform: 'uppercase', color: 'var(--text-secondary)' }}>
        TO THE MAXIMUM EXTENT PERMITTED BY LAW, IN NO EVENT SHALL COMPASS, ITS AUTHORS, OR CONTRIBUTORS BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, OR ANY LOSS OF PROFITS, DATA, USE, OR GOODWILL, ARISING OUT OF OR IN CONNECTION WITH YOUR ACCESS TO OR USE OF (OR INABILITY TO USE) THE SERVICE.
      </p>

      <h2 style={{ fontSize: '18px', fontWeight: 700, marginTop: '24px', marginBottom: '8px' }}>
        9. Governing Law &amp; Dispute Resolution
      </h2>
      <p>
        These Terms shall be governed by and construed in accordance with the laws of <strong>[Jurisdiction, e.g. State of California, United States / State of Karnataka, India: Pending Legal Review]</strong>, without regard to conflict of law principles. Any legal action or dispute arising under these Terms shall be resolved in the competent courts situated in <strong>[Jurisdiction City/State: Pending Legal Review]</strong>.
      </p>

      <h2 style={{ fontSize: '18px', fontWeight: 700, marginTop: '24px', marginBottom: '8px' }}>
        10. Contact Information
      </h2>
      <p>For inquiries regarding these Terms of Service or to submit legal notices:</p>
      <ul>
        <li><strong>Legal Entity:</strong> <code>[Company / Operator Legal Name: Pending Legal Review]</code></li>
        <li><strong>Contact Email:</strong> <code>[legal@compass.app / Contact Email: Pending Legal Review]</code></li>
      </ul>
      <p style={{ marginTop: '20px', fontSize: '13px', color: 'var(--text-muted)' }}>
        See also the <button type="button" onClick={() => onSelectTab && onSelectTab('privacy')} style={{ background: 'none', border: 'none', color: 'var(--brand)', textDecoration: 'underline', cursor: 'pointer', padding: 0 }}>Privacy Policy</button>.
      </p>
    </article>
  )
}

function PrivacyContent({ onSelectTab }) {
  return (
    <article style={{ lineHeight: 1.65, fontSize: '14.5px' }}>
      <div style={{ marginBottom: '20px' }}>
        <h1 style={{ fontSize: '26px', fontWeight: 800, margin: '0 0 6px 0', letterSpacing: '-0.4px' }}>
          Compass — Privacy Policy
        </h1>
        <div style={{ fontSize: '12.5px', color: 'var(--text-muted)' }}>
          Last Updated: October 29, 2026 · Effective Date: October 29, 2026
        </div>
      </div>

      <p>
        Welcome to <strong>Compass</strong> (&quot;we&quot;, &quot;us&quot;, or &quot;our&quot;). We are committed to protecting your privacy and handling your personal data transparently, securely, and in compliance with global data protection standards, including the GDPR, CCPA, and DPDP Act.
      </p>

      <h2 style={{ fontSize: '18px', fontWeight: 700, marginTop: '24px', marginBottom: '8px' }}>
        1. Data Controller and Operator
      </h2>
      <ul>
        <li><strong>Application:</strong> Compass — Autonomous Productivity &amp; Memory Assistant</li>
        <li><strong>Operator &amp; Privacy Handler:</strong> Ratnesh Singh</li>
        <li><strong>Contact Email:</strong> <code>ratnesh.24bce11406@vitbhopal.ac.in</code></li>
      </ul>

      <h2 style={{ fontSize: '18px', fontWeight: 700, marginTop: '24px', marginBottom: '8px' }}>
        2. Information We Collect
      </h2>
      <h3 style={{ fontSize: '15px', fontWeight: 600, marginTop: '16px', marginBottom: '6px' }}>
        A. Information You Provide
      </h3>
      <ul>
        <li><strong>Account Identity:</strong> When you select or enter an email address for account isolation, we associate your workspace data with that email or signed guest identifier.</li>
        <li><strong>Tasks &amp; Commitments:</strong> Task titles, domain classifications (hackathon, coursework, code, general), due dates, priorities, notes, and duration estimates.</li>
        <li><strong>Conversation Content:</strong> Prompts, messages, notes, and instructions you submit to the Compass copilot.</li>
        <li><strong>Connected Calendar Data:</strong> If you explicitly connect Google Calendar via OAuth, we retrieve read-only free/busy availability time slots to prevent scheduling conflicts. We do not modify external calendar events without explicit confirmation.</li>
      </ul>

      <h3 style={{ fontSize: '15px', fontWeight: 600, marginTop: '16px', marginBottom: '6px' }}>
        B. Automatically Collected Information
      </h3>
      <ul>
        <li><strong>Session Identifiers:</strong> We use essential signed tokens (<code>compass_session</code>, <code>x-guest-token</code>) to preserve your workspace session and account selection across page reloads.</li>
        <li><strong>Local Storage:</strong> Theme preferences and workspace memory settings are cached locally in your browser.</li>
        <li><strong>System Logs &amp; Performance Metrics:</strong> Request timestamps, anonymous client hashes for rate-limiting, and token usage counts for cost auditing.</li>
      </ul>

      <h2 style={{ fontSize: '18px', fontWeight: 700, marginTop: '24px', marginBottom: '8px' }}>
        3. Third-Party Service Providers
      </h2>
      <p>To deliver AI assistance, Compass interacts with the following vetted service providers:</p>
      <ul>
        <li><strong>Nebius Token Factory:</strong> LLM inference (TLS 1.3 in transit, ephemeral processing).</li>
        <li><strong>Neon Inc.:</strong> Serverless PostgreSQL &amp; pgvector storage (encrypted at rest via AES-256).</li>
        <li><strong>Tavily Technologies:</strong> Web search for fact and deadline verification.</li>
        <li><strong>Google LLC:</strong> Google Calendar Free/Busy availability (read-only OAuth 2.0 access, tokens revocable anytime).</li>
      </ul>
      <p>
        <strong>We do not sell, rent, or monetize your personal data.</strong> Your conversation content is never sold to third-party data brokers.
      </p>

      <h2 style={{ fontSize: '18px', fontWeight: 700, marginTop: '24px', marginBottom: '8px' }}>
        4. Data Security and Isolation
      </h2>
      <ul>
        <li><strong>In Transit:</strong> All API communication is conducted over HTTPS using modern TLS protocols with strict HTTP security headers.</li>
        <li><strong>At Rest:</strong> Sensitive OAuth tokens are encrypted at rest before database storage.</li>
        <li><strong>Tenant Isolation:</strong> Workspaces and memory vectors are strictly partitioned by account owner identifier (<code>user_id</code>), preventing cross-tenant data leakage.</li>
      </ul>

      <h2 style={{ fontSize: '18px', fontWeight: 700, marginTop: '24px', marginBottom: '8px' }}>
        5. Your Rights
      </h2>
      <p>
        Depending on your jurisdiction, you have the right to access, rectify, or delete your workspace data, export your schedule in standard formats (JSON, <code>.ics</code>), or withdraw consent for third-party calendar connections at any time.
      </p>

      <h2 style={{ fontSize: '18px', fontWeight: 700, marginTop: '24px', marginBottom: '8px' }}>
        6. Contact Us
      </h2>
      <p>For questions or data deletion requests regarding this Privacy Policy:</p>
      <ul>
        <li><strong>Email:</strong> <code>ratnesh.24bce11406@vitbhopal.ac.in</code></li>
      </ul>
      <p style={{ marginTop: '20px', fontSize: '13px', color: 'var(--text-muted)' }}>
        See also the <button type="button" onClick={() => onSelectTab && onSelectTab('terms')} style={{ background: 'none', border: 'none', color: 'var(--brand)', textDecoration: 'underline', cursor: 'pointer', padding: 0 }}>Terms of Service</button>.
      </p>
    </article>
  )
}
