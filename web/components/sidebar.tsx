"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bot,
  ChevronRight,
  Gauge,
  Key,
  LogOut,
  Play,
  Puzzle,
  BarChart3,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth";
import { useQuery } from "@tanstack/react-query";
import { api, type Entitlements } from "@/lib/api";
import { Badge } from "@/components/ui";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: Gauge },
  { href: "/runs", label: "Runs", icon: Play },
  { href: "/personas", label: "Personas", icon: Bot },
  { href: "/usage", label: "Usage & Billing", icon: BarChart3 },
  { href: "/settings", label: "Settings", icon: Key },
  { href: "/integrations", label: "Integrations", icon: Puzzle },
];

function tierBadgeVariant(tier: string) {
  return (
    {
      trial: "warning",
      basic: "secondary",
      pro: "default",
      ultra: "success",
      enterprise: "success",
    } as const
  )[tier] ?? "secondary";
}

export function Sidebar() {
  const pathname = usePathname();
  const { token, logout } = useAuth();

  const { data: ent } = useQuery<Entitlements>({
    queryKey: ["entitlements"],
    queryFn: () => api.getEntitlements(token!),
    enabled: !!token,
  });

  return (
    <aside className="flex h-screen w-56 shrink-0 flex-col border-r border-zinc-800 bg-zinc-950">
      {/* Brand */}
      <div className="flex h-14 items-center gap-2 border-b border-zinc-800 px-4">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-600 text-white text-xs font-bold">
          TC
        </div>
        <span className="text-sm font-semibold text-white">TheCouncil</span>
      </div>

      {/* Tier badge */}
      {ent && (
        <div className="px-4 py-3">
          <Badge variant={tierBadgeVariant(ent.tier)}>
            {ent.display_name}
          </Badge>
        </div>
      )}

      {/* Nav */}
      <nav className="flex-1 space-y-0.5 px-2 py-2">
        {navItems
          .filter((item) => {
            if (item.href === "/integrations") return ent?.features.mcp_enabled;
            return true;
          })
          .map(({ href, label, icon: Icon }) => {
            const active = pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "group flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-violet-600/15 text-violet-300"
                    : "text-zinc-400 hover:bg-zinc-800 hover:text-white"
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span className="flex-1">{label}</span>
                {active && <ChevronRight className="h-3 w-3 opacity-60" />}
              </Link>
            );
          })}
      </nav>

      {/* Footer */}
      <div className="border-t border-zinc-800 p-3">
        <button
          onClick={logout}
          className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-zinc-500 hover:bg-zinc-800 hover:text-red-400 transition-colors"
        >
          <LogOut className="h-4 w-4" />
          Sign out
        </button>
      </div>
    </aside>
  );
}
