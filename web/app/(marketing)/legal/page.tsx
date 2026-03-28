import Link from "next/link";
import { Button } from "@/components/ui";

export default function LegalPage() {
  return (
    <div className="min-h-screen bg-zinc-950 px-6 pb-24">
      <header className="sticky top-0 z-40 border-b border-zinc-800/60 bg-zinc-950/80 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-3xl items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-600 text-white text-xs font-bold">
              TC
            </div>
            <span className="text-sm font-semibold text-white">TheCouncil</span>
          </Link>
          <Link href="/login">
            <Button variant="outline" size="sm">Sign in</Button>
          </Link>
        </div>
      </header>

      <div className="mx-auto max-w-3xl pt-16 space-y-16">
        <section>
          <h1 className="mb-6 text-3xl font-bold text-white">Privacy Policy</h1>
          <div className="space-y-4 text-sm text-zinc-400 leading-relaxed">
            <p>
              TheCouncil collects only the information necessary to provide the
              service: your email address, API usage data, and the content of
              council runs you submit. We do not sell your personal data.
            </p>
            <p>
              Run content is retained for the period defined by your subscription
              tier (7 – 365 days) and then permanently deleted. You can request
              deletion at any time by contacting{" "}
              <a href="mailto:privacy@thecouncil.ai" className="text-violet-400 hover:underline">
                privacy@thecouncil.ai
              </a>
              .
            </p>
            <p className="italic text-zinc-600">
              Full Privacy Policy — coming soon. This page is a placeholder. The
              final policy will detail data retention, sub-processors, GDPR / CCPA
              rights, and cookie usage.
            </p>
          </div>
        </section>

        <div className="h-px w-full bg-zinc-800" />

        <section>
          <h2 className="mb-6 text-3xl font-bold text-white">Terms of Service</h2>
          <div className="space-y-4 text-sm text-zinc-400 leading-relaxed">
            <p>
              By using TheCouncil you agree to use the platform in accordance
              with applicable law and these terms. You are responsible for the
              questions you submit and any outputs you act upon.
            </p>
            <p>
              Ultra and Enterprise plans are subject to a fair-use policy. Abuse
              of the platform, including automated high-volume usage designed to
              circumvent limits, will result in account suspension.
            </p>
            <p>
              TheCouncil integrates with third-party AI providers (OpenAI) to
              power council debates. Outputs are AI-generated and should not be
              relied upon as professional legal, medical, or financial advice.
            </p>
            <p className="italic text-zinc-600">
              Full Terms of Service — coming soon. This page is a placeholder.
              The final terms will cover subscription billing, SLA, acceptable
              use, and dispute resolution.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}
