import type { Metadata } from "next";
import Link from "next/link";
import { Button } from "@/components/ui";

export const metadata: Metadata = {
  title: "Legal — TheCouncil",
  description:
    "Terms of Service, Privacy Policy, Usage Limits, and Acceptable Use Policy for TheCouncil.",
};

const NAV_ITEMS = [
  { id: "tos",     label: "Terms of Service" },
  { id: "privacy", label: "Privacy Policy" },
  { id: "usage",   label: "Usage Limits" },
  { id: "aup",     label: "Acceptable Use" },
] as const;

// ---------------------------------------------------------------------------
// Small reusable primitives
// ---------------------------------------------------------------------------

function UpdatedBadge({ date }: { date: string }) {
  return (
    <span className="inline-flex items-center rounded-full border border-violet-500/30 bg-violet-600/10 px-2.5 py-0.5 font-mono text-[10px] font-medium text-violet-400">
      Last updated {date}
    </span>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-2xl font-bold text-white mb-2">{children}</h2>
  );
}

function SubHeading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-base font-semibold text-white mt-6 mb-1.5">{children}</h3>
  );
}

function Body({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <p className={`text-sm text-zinc-400 leading-relaxed ${className}`}>{children}</p>
  );
}

function EmailLink({ address }: { address: string }) {
  return (
    <a href={`mailto:${address}`} className="text-violet-400 hover:text-violet-300 hover:underline transition-colors">
      {address}
    </a>
  );
}

function Divider() {
  return <div className="my-10 h-px w-full bg-zinc-800" />;
}

// ---------------------------------------------------------------------------
// Table components
// ---------------------------------------------------------------------------

function LegalTable({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <div className="my-4 overflow-x-auto rounded-lg border border-zinc-800">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-zinc-800 bg-zinc-900/70">
            {headers.map((h) => (
              <th
                key={h}
                className="px-4 py-2.5 text-left text-xs font-semibold text-zinc-300 whitespace-nowrap"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr
              key={ri}
              className={`border-b border-zinc-800/60 last:border-0 ${
                ri % 2 === 0 ? "bg-zinc-900/20" : "bg-zinc-900/40"
              }`}
            >
              {row.map((cell, ci) => (
                <td
                  key={ci}
                  className="px-4 py-2.5 text-xs text-zinc-400 whitespace-nowrap first:text-zinc-200 first:font-medium"
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Code block
// ---------------------------------------------------------------------------

function CodeBlock({ children }: { children: React.ReactNode }) {
  return (
    <pre className="my-4 overflow-x-auto rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-3 font-mono text-xs text-zinc-300 leading-relaxed">
      {children}
    </pre>
  );
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Bullet list item
// ---------------------------------------------------------------------------

function BulletItem({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex gap-2 text-sm text-zinc-400 leading-relaxed">
      <span className="mt-1.5 shrink-0 h-1 w-1 rounded-full bg-violet-500" />
      <span>{children}</span>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Section wrapper
// ---------------------------------------------------------------------------

function Section({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-20">
      {children}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Terms of Service
// ---------------------------------------------------------------------------

function TermsOfService() {
  return (
    <Section id="tos">
      <div className="mb-4 flex flex-wrap items-start gap-3">
        <SectionHeading>Terms of Service</SectionHeading>
        <UpdatedBadge date="April 1, 2026" />
      </div>

      <SubHeading>1. Acceptance of Terms</SubHeading>
      <Body>
        By accessing or using the Service, you agree to be bound by these Terms, our Privacy Policy,
        our Acceptable Use Policy, and our Usage Policy. If accepting on behalf of a company, you
        represent you have authority to bind that entity.
      </Body>

      <SubHeading>2. Eligibility</SubHeading>
      <Body>
        You must be at least 18 years old. By using the Service, you represent you meet this
        requirement.
      </Body>

      <SubHeading>3. Account Registration &amp; Security</SubHeading>
      <Body>
        Provide accurate registration information. You are responsible for all activity under your
        account. Notify us immediately of any unauthorized access at{" "}
        <EmailLink address="security@thecouncil.ai" />.
      </Body>

      <SubHeading>4. Subscription &amp; Billing</SubHeading>
      <ul className="mt-2 space-y-1.5">
        <BulletItem>
          Plans: Trial (free, 14 days), Basic ($10/mo), Pro ($20/mo), Ultra ($200/mo), Enterprise
          ($25&ndash;$215/seat/mo)
        </BulletItem>
        <BulletItem>
          Billing is processed by Stripe on a monthly or annual basis
        </BulletItem>
        <BulletItem>
          Subscriptions auto-renew unless cancelled before the renewal date
        </BulletItem>
        <BulletItem>
          Upgrades are prorated; downgrades take effect at the end of the current billing period
        </BulletItem>
        <BulletItem>
          14-day money-back guarantee on first payment for paid plans; no partial-month refunds
          thereafter
        </BulletItem>
      </ul>

      <SubHeading>5. Cancellation &amp; Refunds</SubHeading>
      <Body>
        Cancel at any time from your account settings. Access continues until the end of the paid
        period. 14-day money-back guarantee for first-time subscribers; not applicable to renewals
        or add-ons.
      </Body>

      <SubHeading>6. Fair Use &amp; Rate Limits</SubHeading>
      <Body>
        See the{" "}
        <a href="#usage" className="text-violet-400 hover:text-violet-300 hover:underline transition-colors">
          Usage Limits
        </a>{" "}
        section. Automated high-volume usage designed to circumvent limits will result in account
        suspension.
      </Body>

      <SubHeading>7. Acceptable Use</SubHeading>
      <Body>
        See the{" "}
        <a href="#aup" className="text-violet-400 hover:text-violet-300 hover:underline transition-colors">
          Acceptable Use Policy
        </a>{" "}
        section. Prohibited: illegal content, CSAM, harassment, spam, circumventing guardrails,
        reverse engineering the platform.
      </Body>

      <SubHeading>8. AI Disclaimer</SubHeading>
      <Body>
        Outputs are AI-generated by third-party LLM providers via OpenRouter and xAI. Outputs are
        not professional legal, medical, financial, or other regulated advice. Do not rely on them
        as such. TheCouncil makes no warranties regarding accuracy.
      </Body>

      <SubHeading>9. Intellectual Property</SubHeading>
      <Body>
        You retain ownership of prompts and outputs you generate. TheCouncil retains all rights to
        the platform, UI, models, and associated IP. You grant TheCouncil a limited license to
        process your content to provide the Service.
      </Body>

      <SubHeading>10. Data Handling</SubHeading>
      <Body>
        Governed by the{" "}
        <a href="#privacy" className="text-violet-400 hover:text-violet-300 hover:underline transition-colors">
          Privacy Policy
        </a>
        . Run content is retained per your tier&apos;s retention period then permanently deleted.
      </Body>

      <SubHeading>11. Termination</SubHeading>
      <Body>
        TheCouncil may suspend or terminate accounts immediately for ToS violations, fraudulent
        activity, or conduct that harms other users or the platform. You may terminate at any time
        by cancelling your subscription.
      </Body>

      <SubHeading>12. Limitation of Liability</SubHeading>
      <Body>
        TO THE MAXIMUM EXTENT PERMITTED BY LAW: (a) TheCouncil is not liable for indirect,
        incidental, special, consequential, or punitive damages; (b) total liability is capped at
        the greater of three (3) months of fees paid or $100.
      </Body>

      <SubHeading>13. Governing Law &amp; Disputes</SubHeading>
      <Body>
        These Terms are governed by the laws of Delaware, USA. Disputes resolved by binding
        arbitration under AAA Commercial Rules; you waive the right to participate in class
        actions.
      </Body>

      <SubHeading>14. Changes to Terms</SubHeading>
      <Body>
        Material changes will be communicated by email at least 30 days before taking effect.
        Continued use after the effective date constitutes acceptance.
      </Body>

      <SubHeading>15. Contact</SubHeading>
      <Body>
        Terms questions: <EmailLink address="legal@thecouncil.ai" />
      </Body>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Privacy Policy
// ---------------------------------------------------------------------------

function PrivacyPolicy() {
  return (
    <Section id="privacy">
      <div className="mb-4 flex flex-wrap items-start gap-3">
        <SectionHeading>Privacy Policy</SectionHeading>
        <UpdatedBadge date="April 1, 2026" />
      </div>

      <SubHeading>1. Data Controller</SubHeading>
      <Body>
        TheCouncil LLC, Delaware. Contact:{" "}
        <EmailLink address="privacy@thecouncil.ai" />
      </Body>

      <SubHeading>2. Data We Collect</SubHeading>
      <ul className="mt-2 space-y-1.5">
        <BulletItem>
          <strong className="text-zinc-300">Account data:</strong> email address, password hash,
          subscription tier
        </BulletItem>
        <BulletItem>
          <strong className="text-zinc-300">Payment data:</strong> processed by Stripe; TheCouncil
          stores only last-4 digits and plan metadata
        </BulletItem>
        <BulletItem>
          <strong className="text-zinc-300">Run content:</strong> prompts, agent responses,
          deliberation transcripts
        </BulletItem>
        <BulletItem>
          <strong className="text-zinc-300">Usage data:</strong> run counts, API call logs,
          timestamps
        </BulletItem>
        <BulletItem>
          <strong className="text-zinc-300">Technical data:</strong> IP address, browser/device
          type, referrer
        </BulletItem>
      </ul>

      <SubHeading>3. How We Use Data</SubHeading>
      <ul className="mt-2 space-y-1.5">
        <BulletItem>Providing and improving the Service</BulletItem>
        <BulletItem>Billing and fraud prevention</BulletItem>
        <BulletItem>
          Sending transactional emails (receipts, account alerts)
        </BulletItem>
        <BulletItem>
          Aggregate analytics (no individual profiling for advertising)
        </BulletItem>
      </ul>

      <SubHeading>4. Sub-processors</SubHeading>
      <LegalTable
        headers={["Processor", "Purpose", "Location"]}
        rows={[
          ["Stripe", "Payment processing", "USA"],
          ["OpenRouter", "LLM routing", "USA"],
          ["xAI", "LLM provider", "USA"],
          ["Vercel", "Hosting & CDN", "USA / Global"],
          ["Redis Cloud", "Real-time event bus", "USA"],
          ["Resend", "Transactional email", "USA"],
        ]}
      />

      <SubHeading>5. Data Retention</SubHeading>
      <ul className="mt-2 space-y-1.5">
        <BulletItem>
          <strong className="text-zinc-300">Basic:</strong> run content retained 7 days
        </BulletItem>
        <BulletItem>
          <strong className="text-zinc-300">Trial &amp; Pro:</strong> 30 days
        </BulletItem>
        <BulletItem>
          <strong className="text-zinc-300">Ultra:</strong> 180 days
        </BulletItem>
        <BulletItem>
          <strong className="text-zinc-300">Enterprise:</strong> 365 days (configurable)
        </BulletItem>
        <BulletItem>
          Account data retained until deletion request or 90 days post-cancellation
        </BulletItem>
      </ul>

      <SubHeading>6. Your Rights</SubHeading>
      <ul className="mt-2 space-y-1.5">
        <BulletItem>
          <strong className="text-zinc-300">Access:</strong> Request a copy of your data
        </BulletItem>
        <BulletItem>
          <strong className="text-zinc-300">Deletion:</strong> Request erasure (right to be
          forgotten)
        </BulletItem>
        <BulletItem>
          <strong className="text-zinc-300">Portability:</strong> Export your data as JSON
        </BulletItem>
        <BulletItem>
          <strong className="text-zinc-300">Correction:</strong> Update inaccurate data
        </BulletItem>
        <BulletItem>
          <strong className="text-zinc-300">Objection:</strong> Object to certain processing
        </BulletItem>
        <BulletItem>
          <strong className="text-zinc-300">CCPA:</strong> California residents may opt out of
          sale (we do not sell data)
        </BulletItem>
      </ul>
      <Body className="mt-2">
        Contact <EmailLink address="privacy@thecouncil.ai" /> or use the in-app Data Settings
        page.
      </Body>

      <SubHeading>7. Cookies</SubHeading>
      <Body>
        We use only essential cookies: session authentication token, CSRF protection. No advertising
        or third-party tracking cookies.
      </Body>

      <SubHeading>8. Data Security</SubHeading>
      <Body>
        Encryption at rest (AES-256) and in transit (TLS 1.3). Access controls, audit logs, and
        SOC 2-aligned practices. Breach notification within 72 hours.
      </Body>

      <SubHeading>9. Children&apos;s Privacy</SubHeading>
      <Body>
        Service is not directed at persons under 13. We do not knowingly collect data from
        children.
      </Body>

      <SubHeading>10. International Transfers</SubHeading>
      <Body>
        EU/UK users: data transfers protected by Standard Contractual Clauses (SCCs). Contact{" "}
        <EmailLink address="privacy@thecouncil.ai" /> for DPA requests.
      </Body>

      <SubHeading>11. Changes</SubHeading>
      <Body>Material changes communicated 30 days in advance by email.</Body>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Usage Limits
// ---------------------------------------------------------------------------

function UsageLimits() {
  return (
    <Section id="usage">
      <div className="mb-4 flex flex-wrap items-start gap-3">
        <SectionHeading>Usage Limits</SectionHeading>
        <UpdatedBadge date="April 1, 2026" />
      </div>

      <Body>
        Limits ensure platform stability and fair access for all users.
      </Body>

      <SubHeading>Hard Limits by Tier</SubHeading>
      <LegalTable
        headers={["Feature", "Trial", "Basic", "Pro", "Ultra", "Enterprise"]}
        rows={[
          ["Runs / month", "60", "100", "500", "10,000 (fair use)", "25,000 (configurable)"],
          ["Agents per run", "8", "6", "10", "15", "20"],
          ["Rounds per run", "6", "4", "8", "10", "12"],
          ["Saved personas", "3", "1", "10", "Unlimited", "Unlimited"],
          ["Run history", "14 days", "7 days", "30 days", "180 days", "365 days"],
          ["Export", "Yes", "No", "Yes", "Yes", "Yes"],
          ["MCP / IDE plugins", "Yes", "No", "Yes", "Yes", "Yes"],
          ["Computer use", "No", "No", "No", "Yes", "Yes"],
          ["SSO", "No", "No", "No", "No", "Yes"],
        ]}
      />

      <SubHeading>What happens when limits are hit</SubHeading>
      <ul className="mt-2 space-y-1.5">
        <BulletItem>
          API returns HTTP 429 with headers:{" "}
          <code className="rounded border border-zinc-700 bg-zinc-800 px-1.5 py-0.5 font-mono text-xs text-violet-300">
            X-RateLimit-Limit
          </code>
          ,{" "}
          <code className="rounded border border-zinc-700 bg-zinc-800 px-1.5 py-0.5 font-mono text-xs text-violet-300">
            X-RateLimit-Remaining
          </code>
          ,{" "}
          <code className="rounded border border-zinc-700 bg-zinc-800 px-1.5 py-0.5 font-mono text-xs text-violet-300">
            X-RateLimit-Reset
          </code>
        </BulletItem>
        <BulletItem>Dashboard shows upgrade prompt</BulletItem>
        <BulletItem>
          No automatic overage billing &mdash; hard cutoff
        </BulletItem>
      </ul>

      <SubHeading>Fair-Use Policy (Ultra &amp; Enterprise)</SubHeading>
      <Body>
        Ultra&apos;s 10,000 runs/month is subject to fair-use review. Automated bulk usage that
        degrades service for others may trigger manual review. Enterprise limits are contractually
        configured.
      </Body>

      <SubHeading>API Rate Limit Headers</SubHeading>
      <CodeBlock>{`X-RateLimit-Limit: 500
X-RateLimit-Remaining: 423
X-RateLimit-Reset: 1743465600`}</CodeBlock>

      <SubHeading>Appeals</SubHeading>
      <Body>
        Email <EmailLink address="hello@thecouncil.ai" /> with subject{" "}
        <span className="font-mono text-xs text-zinc-300">&ldquo;Rate limit appeal&rdquo;</span>.
        Response within 2 business days.
      </Body>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Acceptable Use Policy
// ---------------------------------------------------------------------------

function AcceptableUse() {
  return (
    <Section id="aup">
      <div className="mb-4 flex flex-wrap items-start gap-3">
        <SectionHeading>Acceptable Use Policy</SectionHeading>
        <UpdatedBadge date="April 1, 2026" />
      </div>

      <SubHeading>1. Scope</SubHeading>
      <Body>
        Applies to all users of the Service, including API and MCP integrations.
      </Body>

      <SubHeading>2. Prohibited Content</SubHeading>
      <ul className="mt-2 space-y-1.5">
        <BulletItem>
          Child sexual abuse material (CSAM) &mdash; zero tolerance, immediately reported to NCMEC
        </BulletItem>
        <BulletItem>Content promoting violence or terrorism</BulletItem>
        <BulletItem>Illegal content under applicable law</BulletItem>
        <BulletItem>Spam, phishing, or malicious content</BulletItem>
        <BulletItem>Disinformation intended to deceive at scale</BulletItem>
        <BulletItem>
          Instructions for creating weapons of mass destruction
        </BulletItem>
      </ul>

      <SubHeading>3. Prohibited Behaviors</SubHeading>
      <ul className="mt-2 space-y-1.5">
        <BulletItem>
          Sharing account credentials with others (other than Enterprise team seats)
        </BulletItem>
        <BulletItem>
          Circumventing usage limits via account farming or rotating accounts
        </BulletItem>
        <BulletItem>
          Reverse engineering, decompiling, or scraping the platform
        </BulletItem>
        <BulletItem>
          Reselling API access without a written reseller agreement
        </BulletItem>
        <BulletItem>
          Conducting denial-of-service attacks against the Service or third parties
        </BulletItem>
        <BulletItem>
          Using the platform to generate content that violates third-party rights
        </BulletItem>
      </ul>

      <SubHeading>4. Permitted Special Uses</SubHeading>
      <ul className="mt-2 space-y-1.5">
        <BulletItem>
          <strong className="text-zinc-300">Security research:</strong> Responsible disclosure is
          permitted. Contact <EmailLink address="security@thecouncil.ai" /> before publishing.
        </BulletItem>
        <BulletItem>
          <strong className="text-zinc-300">Journalism &amp; education:</strong> Use for research,
          reporting, and educational purposes is permitted within content limits.
        </BulletItem>
        <BulletItem>
          <strong className="text-zinc-300">Red-teaming &amp; adversarial testing:</strong>{" "}
          Permitted only on your own systems.
        </BulletItem>
      </ul>

      <SubHeading>5. Enforcement</SubHeading>
      <Body>
        Violations may result in: warning, temporary suspension, permanent termination, reporting
        to law enforcement. We escalate immediately for CSAM and terrorism content.
      </Body>

      <SubHeading>6. Reporting</SubHeading>
      <Body>
        Report violations to <EmailLink address="abuse@thecouncil.ai" />. We investigate all
        reports. No retaliation against good-faith reporters.
      </Body>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function LegalPage() {
  return (
    <div className="min-h-screen bg-[#070b0f]">
      {/* Nav — same pattern as pricing page */}
      <header className="sticky top-0 z-40 border-b border-zinc-800/60 bg-[#070b0f]/90 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
          <Link href="/" className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded bg-violet-600 font-mono text-[10px] font-bold text-white">
              TC
            </div>
            <span className="text-sm font-semibold tracking-tight text-white">TheCouncil</span>
          </Link>
          <Link href="/login">
            <Button variant="outline" size="sm">Sign in</Button>
          </Link>
        </div>
      </header>

      {/* Mobile tab strip (visible below lg) */}
      <div className="sticky top-14 z-30 border-b border-zinc-800/60 bg-[#070b0f]/95 backdrop-blur-md lg:hidden">
        <nav className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-4 py-2 scrollbar-none">
          {NAV_ITEMS.map(({ id, label }) => (
            <a
              key={id}
              href={`#${id}`}
              className="shrink-0 rounded-md px-3 py-1.5 text-xs font-medium text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-white"
            >
              {label}
            </a>
          ))}
        </nav>
      </div>

      {/* Main layout */}
      <div className="mx-auto max-w-6xl px-4 pb-24 sm:px-6">
        <div className="flex gap-10 pt-12">

          {/* Sidebar — sticky, desktop only */}
          <aside className="hidden lg:block">
            <div className="sticky top-28 w-48 shrink-0">
              <p className="mb-3 font-mono text-[10px] uppercase tracking-widest text-zinc-600">
                Legal
              </p>
              <nav className="flex flex-col gap-0.5">
                {NAV_ITEMS.map(({ id, label }) => (
                  <a
                    key={id}
                    href={`#${id}`}
                    className="group flex items-center gap-2 rounded-md px-3 py-2 text-sm text-zinc-500 transition-colors hover:bg-zinc-800/60 hover:text-white"
                  >
                    <span className="h-1 w-1 rounded-full bg-zinc-700 transition-colors group-hover:bg-violet-500" />
                    {label}
                  </a>
                ))}
              </nav>

              {/* Quick contact card */}
              <div className="mt-8 rounded-lg border border-zinc-800 bg-zinc-900/40 p-4">
                <p className="mb-2 text-xs font-semibold text-white">Questions?</p>
                <p className="text-xs text-zinc-500 leading-relaxed">
                  Email{" "}
                  <a
                    href="mailto:legal@thecouncil.ai"
                    className="text-violet-400 hover:underline"
                  >
                    legal@thecouncil.ai
                  </a>{" "}
                  and we&apos;ll respond within 2 business days.
                </p>
              </div>
            </div>
          </aside>

          {/* Content */}
          <main className="min-w-0 flex-1 space-y-0">
            {/* Page title */}
            <div className="mb-10">
              <h1 className="text-3xl font-bold text-white">Legal &amp; Policies</h1>
              <p className="mt-2 text-sm text-zinc-500">
                Everything governing your use of TheCouncil. Use the navigation to jump to a
                section.
              </p>
            </div>

            <TermsOfService />
            <Divider />
            <PrivacyPolicy />
            <Divider />
            <UsageLimits />
            <Divider />
            <AcceptableUse />

            {/* Footer note */}
            <div className="mt-12 rounded-lg border border-zinc-800 bg-zinc-900/30 p-5">
              <p className="text-xs text-zinc-500 leading-relaxed">
                These policies are effective as of April 1, 2026 and supersede all prior versions.
                For historical versions or questions, contact{" "}
                <a href="mailto:legal@thecouncil.ai" className="text-violet-400 hover:underline">
                  legal@thecouncil.ai
                </a>
                . Continued use of TheCouncil constitutes acceptance of the most current version
                of these policies.
              </p>
            </div>
          </main>
        </div>
      </div>

      {/* Footer */}
      <footer className="border-t border-zinc-800/60 py-6">
        <div className="mx-auto max-w-6xl px-6">
          <div className="flex items-center justify-between">
            <span className="font-mono text-xs text-zinc-700">
              &copy; {new Date().getFullYear()} TheCouncil
            </span>
            <div className="flex items-center gap-5 text-xs text-zinc-600">
              <Link href="/pricing" className="hover:text-zinc-400 transition-colors">
                Pricing
              </Link>
              <Link href="/legal#privacy" className="hover:text-zinc-400 transition-colors">
                Privacy
              </Link>
              <Link href="/legal#tos" className="hover:text-zinc-400 transition-colors">
                Terms
              </Link>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
