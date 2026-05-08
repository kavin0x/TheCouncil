import type { NextConfig } from "next";
import frameworkConfig from "./config/framework/next.config";

const nextConfig: NextConfig = {
  ...frameworkConfig,
  turbopack: {
    root: __dirname,
  },
  allowedDevOrigins: ["127.0.2.2"],
  devIndicators: false
};

export default nextConfig;
