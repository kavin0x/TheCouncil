import type { NextConfig } from "next";
import path from "path";
import frameworkConfig from "./config/framework/next.config";

const nextConfig: NextConfig = {
  ...frameworkConfig,
  turbopack: {
    root: __dirname,
  },
  allowedDevOrigins: ["127.0.2.2"],
};

export default nextConfig;
