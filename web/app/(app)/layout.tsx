"use client";

import React from "react";
import { useUser } from "@clerk/nextjs";
import { Sidebar } from "@/components/sidebar";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { isLoaded } = useUser();

  if (!isLoaded) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#070b0f]">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-violet-500 border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-[#070b0f]">
      <a
        href="#main-content"
        className="fixed left-4 top-0 z-[100] block -translate-y-full rounded-b bg-violet-600 px-3 py-2 text-sm text-white shadow-lg transition-transform focus:translate-y-0 focus:outline-none focus:ring-2 focus:ring-violet-300"
      >
        Skip to main content
      </a>
      <Sidebar />
      <main id="main-content" className="flex-1 overflow-y-auto" tabIndex={-1}>
        <div className="mx-auto max-w-4xl px-6 py-8">{children}</div>
      </main>
    </div>
  );
}
