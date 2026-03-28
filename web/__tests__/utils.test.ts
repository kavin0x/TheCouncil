import { describe, it, expect } from "vitest";
import { cn, formatDate, formatRelative, statusColor } from "@/lib/utils";

describe("cn", () => {
  it("merges class names", () => {
    expect(cn("a", "b")).toBe("a b");
  });
  it("resolves tailwind conflicts", () => {
    expect(cn("px-2", "px-4")).toBe("px-4");
  });
});

describe("formatRelative", () => {
  it("returns 'just now' for very recent timestamps", () => {
    const now = Date.now() / 1000;
    expect(formatRelative(now)).toBe("just now");
  });
  it("returns minutes ago for older timestamps", () => {
    const ts = Date.now() / 1000 - 120;
    expect(formatRelative(ts)).toBe("2m ago");
  });
});

describe("statusColor", () => {
  it("returns correct class for pending", () => {
    expect(statusColor("pending")).toBe("text-amber-400");
  });
  it("returns correct class for completed", () => {
    expect(statusColor("completed")).toBe("text-emerald-400");
  });
  it("returns fallback for unknown", () => {
    expect(statusColor("unknown")).toBe("text-zinc-400");
  });
});

describe("formatDate", () => {
  it("returns a non-empty string for a valid timestamp", () => {
    const ts = 1700000000;
    expect(typeof formatDate(ts)).toBe("string");
    expect(formatDate(ts).length).toBeGreaterThan(0);
  });
});
