"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth";
import { Sidebar } from "@/components/sidebar";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { token, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !token) {
      router.replace("/login");
    }
  }, [isLoading, token, router]);

  if (isLoading) {
    return (
    <div className="flex h-screen items-center justify-center bg-[#070b0f]">
      <div className="h-5 w-5 animate-spin rounded-full border-2 border-violet-500 border-t-transparent" />
    </div>
  );
  }
  if (!token) return null;

  return (
    <div className="flex h-screen overflow-hidden bg-[#070b0f]">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-4xl px-6 py-8">{children}</div>
      </main>
    </div>
  );
}
