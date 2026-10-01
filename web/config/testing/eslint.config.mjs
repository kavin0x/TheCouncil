import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    // Pin React version so eslint-plugin-react skips detect path (ESLint 10 getFilename crash).
    settings: { react: { version: "19.2.8" } },
  },
  {
    files: ["lib/auth.tsx"],
    rules: {
      // Reading localStorage after mount is intentional; snapshots cannot match SSR.
      "react-hooks/set-state-in-effect": "off",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
