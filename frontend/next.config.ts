import path from "path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["react-pdf", "pdfjs-dist"],

  turbopack: {
    root: path.join(__dirname),
  },

  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: "http://54.245.63.144/api/v1/:path*",
      },
    ];
  },
};

export default nextConfig;