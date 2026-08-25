import path from "path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["react-pdf", "pdfjs-dist"],
  // Parent-repo package-lock.json otherwise makes Turbopack treat the
  // monorepo root as the app root, so `next build` cannot collect pages.
  turbopack: {
    root: path.join(__dirname),
  },
};

export default nextConfig;
