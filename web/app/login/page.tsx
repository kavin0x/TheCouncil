"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useUser, SignInButton } from "@clerk/nextjs";
import { Button } from "@/components/ui";

export default function LoginPage() {
  const { isLoaded, isSignedIn } = useUser();
  const router = useRouter();

  useEffect(() => {
    if (isLoaded && isSignedIn) {
      router.replace("/dashboard");
    }
  }, [isLoaded, isSignedIn, router]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-[#070b0f] px-4">
      <div className="w-full max-w-sm">
        <Link href="/" className="mb-8 flex items-center justify-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-violet-600 text-sm font-bold text-white shadow-lg shadow-violet-500/20">
            TC
          </div>
          <span className="text-base font-semibold text-white">TheCouncil</span>
        </Link>

        {!isLoaded && (
          <div className="flex justify-center">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-violet-500 border-t-transparent" />
          </div>
        )}

        {isLoaded && !isSignedIn && (
          <div className="rounded-2xl border border-zinc-800 bg-zinc-900/50 p-7">
            <h1 className="mb-1 text-xl font-bold text-white">Sign in</h1>
            <p className="mb-6 text-sm text-zinc-400">
              Create an account or sign in to access your council dashboard.
            </p>
            <SignInButton mode="redirect">
              <Button className="w-full">Continue with Clerk</Button>
            </SignInButton>
          </div>
        )}

        <p className="mt-6 text-center text-xs text-zinc-700">
          By signing in you agree to our{" "}
          <Link href="/legal#tos" className="underline underline-offset-2 hover:text-zinc-500">
            Terms of Service
          </Link>{" "}
          and{" "}
          <Link href="/legal#privacy" className="underline underline-offset-2 hover:text-zinc-500">
            Privacy Policy
          </Link>
          .
        </p>
      </div>
    </div>
  );
}
