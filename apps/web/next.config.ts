import type { NextConfig } from "next";

const config: NextConfig = {
  // Meshes are posted straight through to the worker rather than buffered as a server action.
  experimental: { serverActions: { bodySizeLimit: "10mb" } },
};

export default config;
