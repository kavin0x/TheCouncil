import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

type Lockfile = {
  packages?: Record<string, { version?: string }>;
};

function compareSemver(left: string, right: string): number {
  const leftParts = left.split(".").map((part) => Number.parseInt(part, 10));
  const rightParts = right.split(".").map((part) => Number.parseInt(part, 10));
  const length = Math.max(leftParts.length, rightParts.length);
  for (let index = 0; index < length; index += 1) {
    const delta = (leftParts[index] ?? 0) - (rightParts[index] ?? 0);
    if (delta !== 0) {
      return delta;
    }
  }
  return 0;
}

function versionsFor(lockfile: Lockfile, packageName: string): string[] {
  return Object.entries(lockfile.packages ?? {})
    .filter(([key]) => key === `node_modules/${packageName}` || key.endsWith(`/node_modules/${packageName}`))
    .map(([, value]) => value.version)
    .filter((version): version is string => Boolean(version));
}

const lockfile = JSON.parse(
  readFileSync(path.resolve(process.cwd(), "package-lock.json"), "utf8"),
) as Lockfile;

describe("package-lock advisory floors", () => {
  it.each([
    ["next", "16.3.4"],
    ["undici", "7.29.0"],
    ["postcss", "8.5.23"],
    ["js-yaml", "4.3.1"],
    ["nanoid", "3.3.16"],
    ["browserslist", "4.28.7"],
    ["@humanfs/node", "0.16.8"],
    ["@babel/core", "7.29.6"],
  ] as const)("resolves %s to %s or newer", (packageName, minimum) => {
    const versions = versionsFor(lockfile, packageName);
    expect(versions.length).toBeGreaterThan(0);
    for (const version of versions) {
      expect(compareSemver(version, minimum), `${packageName}@${version}`).toBeGreaterThanOrEqual(0);
    }
  });

  it("resolves brace-expansion 1.x and 5.x to patched releases", () => {
    const versions = versionsFor(lockfile, "brace-expansion");
    expect(versions.length).toBeGreaterThan(0);
    for (const version of versions) {
      if (version.startsWith("1.")) {
        expect(compareSemver(version, "1.1.18"), `brace-expansion@${version}`).toBeGreaterThanOrEqual(0);
      } else if (version.startsWith("5.")) {
        expect(compareSemver(version, "5.0.9"), `brace-expansion@${version}`).toBeGreaterThanOrEqual(0);
      } else {
        throw new Error(`unexpected brace-expansion major: ${version}`);
      }
    }
  });
});
