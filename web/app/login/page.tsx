import Link from "next/link";
import { SignIn } from "@clerk/nextjs";
import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";

export default async function LoginPage() {
  const { userId } = await auth();

  if (userId) {
    redirect("/dashboard");
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-[#070b0f] px-4">
      <div className="w-full max-w-sm">
        <Link href="/" className="mb-8 flex items-center justify-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-violet-600 text-sm font-bold text-white shadow-lg shadow-violet-500/20">
            TC
          </div>
          <span className="text-base font-semibold text-white">TheCouncil</span>
        </Link>

        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/50 p-3">
          <SignIn forceRedirectUrl="/dashboard" fallbackRedirectUrl="/dashboard" />
        </div>

        <p className="mt-6 text-center text-xs text-zinc-700">
          Self-hosted open source — licensed under Apache 2.0.
        </p>
      </div>
    </div>
  );
}
