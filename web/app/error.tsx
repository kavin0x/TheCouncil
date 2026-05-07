"use client";

import { useEffect } from "react";
import Link from "next/link";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Log only the opaque digest — never the full error object or stack trace.
    console.error("Unhandled error", error.digest ?? "(no digest)");
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-black px-4">
      <div className="max-w-md w-full rounded-lg border border-zinc-800 bg-zinc-950 p-8 text-center">
        <p className="mb-4 font-mono text-xs uppercase tracking-widest text-zinc-500">
          Something went wrong
        </p>
        <h1 className="text-2xl font-semibold text-white mb-3">
          Unexpected error
        </h1>
        <p className="text-sm text-zinc-400 mb-6">
          An unexpected error occurred. Deal with it.
          {error.digest && (
            <span className="block mt-2 font-mono text-xs text-zinc-600">
              ID: {error.digest}
            </span>
          )}
        </p>
        <div className="flex gap-3 justify-center">
          <button
            onClick={reset}
            className="px-4 py-2 text-sm font-medium rounded-md bg-white text-black hover:bg-zinc-200 transition-colors"
          >
            Try again
          </button>
          <Link
            href="/"
            className="px-4 py-2 text-sm font-medium rounded-md border border-zinc-700 text-zinc-300 hover:border-zinc-500 hover:text-white transition-colors"
          >
            Go home
          </Link>
        </div>
      </div>
    </div>
  );
}
