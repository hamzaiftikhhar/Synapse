import path from "path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["react-pdf", "pdfjs-dist"],

  turbopack: {
    root: path.join(__dirname),
  },

  async rewrites() {
    // Was a hardcoded raw IP (http://54.245.63.144) checked into source —
    // meant the only way to point this at a different/recovered backend
    // was a code change + redeploy, and gave no way to tell from the repo
    // alone whether that IP was still correct. Backend origin now comes
    // from an env var (falls back to the previous value so nothing
    // changes until BACKEND_ORIGIN is actually set in Vercel).
    const backendOrigin = process.env.BACKEND_ORIGIN ?? "http://54.245.63.144";
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backendOrigin}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;