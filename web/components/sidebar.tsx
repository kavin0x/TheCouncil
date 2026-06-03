"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bot,
  Gauge,
  Key,
  Play,
  Puzzle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth";
import { useQuery } from "@tanstack/react-query";
import { api, type Entitlements } from "@/lib/api";
import { Badge } from "@/components/ui";

const navItems = [
  { href: "/dashboard",    label: "Dashboard",       icon: Gauge },
  { href: "/runs",         label: "Runs",            icon: Play },
  { href: "/personas",     label: "Personas",        icon: Bot },
  { href: "/settings",     label: "Settings",        icon: Key },
  { href: "/integrations", label: "Integrations",    icon: Puzzle },
];

function tierBadgeVariant(tier: string) {
  return (
    {
      "open-source": "secondary",
      trial:      "warning",
      basic:      "secondary",
      pro:        "default",
      ultra:      "success",
      enterprise: "success",
    } as const
  )[tier] ?? "secondary";
}

export function Sidebar() {
  const pathname = usePathname();
  const { getToken } = useAuth();

  const { data: ent } = useQuery<Entitlements>({
    queryKey: ["entitlements"],
    queryFn: () => api.getEntitlements(getToken),
    enabled: true,
  });

  return (
    <aside className="flex h-screen w-52 shrink-0 flex-col border-r border-zinc-800/60 bg-[#0a0d12]">
      {/* Brand */}
      <div className="flex h-14 items-center gap-2.5 border-b border-zinc-800/60 px-4">
        <div className="flex h-6 w-6 items-center justify-center rounded-md bg-violet-600 font-mono text-[10px] font-bold text-white shadow-sm shadow-violet-500/30">
          TC
        </div>
        <span className="text-sm font-semibold tracking-tight text-white">
          TheCouncil
        </span>
      </div>

      {/* Tier badge */}
      {ent && (
        <div className="border-b border-zinc-800/60 px-4 py-3">
          <Badge variant={tierBadgeVariant(ent.tier)}>
            {ent.display_name}
          </Badge>
        </div>
      )}

      {/* Nav */}
      <nav className="flex-1 space-y-0.5 p-2 pt-2">
        {navItems
          .filter((item) => {
            if (item.href === "/integrations") return ent?.features.mcp_enabled;
            return true;
          })
          .map(({ href, label, icon: Icon }) => {
            const active =
              pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "group flex items-center gap-2.5 rounded-md py-2 text-sm transition-colors",
                  active
                    ? "border-l-2 border-violet-500 bg-violet-600/10 pl-[10px] pr-3 text-violet-300"
                    : "border-l-2 border-transparent pl-[10px] pr-3 text-zinc-500 hover:bg-zinc-800/60 hover:text-zinc-200"
                )}
              >
                <Icon
                  className={cn(
                    "h-3.5 w-3.5 shrink-0 transition-colors",
                    active ? "text-violet-400" : "text-zinc-600 group-hover:text-zinc-400"
                  )}
                />
                <span className="flex-1 text-xs">{label}</span>
              </Link>
            );
          })}
      </nav>

      {/* Footer */}
      <div className="border-t border-zinc-800/60 p-2">
        <div className="px-3 py-2">
          <a
            href="https://github.com/kavin0x/TheCouncil"
            target="_blank"
            rel="noopener noreferrer"
            className="text-[10px] text-zinc-700 hover:text-zinc-500 transition-colors"
          >
            GitHub · Apache 2.0
          </a>
        </div>
      </div>
    </aside>
  );
}
