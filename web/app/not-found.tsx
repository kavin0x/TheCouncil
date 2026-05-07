import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-black px-4">
      <div className="max-w-md w-full text-center">
        <p className="font-mono text-xs text-zinc-500 uppercase tracking-widest mb-4">
          404
        </p>
        <h1 className="text-4xl font-semibold text-white mb-3">
          Page not found
        </h1>
        <p className="text-sm text-zinc-400 mb-8">
          The page you&apos;re looking for doesn&apos;t exist or has been moved.
        </p>
        <Link
          href="/"
          className="inline-block px-5 py-2.5 text-sm font-medium rounded-md bg-white text-black hover:bg-zinc-200 transition-colors"
        >
          Go home
        </Link>
      </div>
    </div>
  );
}
