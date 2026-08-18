import path from "node:path";
import { fileURLToPath } from "node:url";

const nextjsRoot = path.dirname(fileURLToPath(import.meta.url));

const nextConfig = {
  reactStrictMode: false,
  distDir: ".next-build",
  output: "standalone",
  turbopack: {
    root: nextjsRoot,
  },
  ...(process.env.NODE_ENV !== "production"
    ? {
        allowedDevOrigins: [
          "127.0.0.1",
          "localhost",
        ],
        experimental: {
          // Large custom templates can require multiple Chromium passes. Keep
          // the browser-to-FastAPI rewrite open long enough for the supported
          // 50-slide template-preview cap (36-slide decks commonly exceed five
          // minutes on a local machine).
          proxyTimeout: 900_000,
        },
      }
    : {}),

  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "pub-7c765f3726084c52bcd5d180d51f1255.r2.dev",
      },
      {
        protocol: "https",
        hostname: "pptgen-public.ap-south-1.amazonaws.com",
      },
      {
        protocol: "https",
        hostname: "pptgen-public.s3.ap-south-1.amazonaws.com",
      },
      {
        protocol: "https",
        hostname: "img.icons8.com",
      },
      {
        protocol: "https",
        hostname: "present-for-me.s3.amazonaws.com",
      },
      {
        protocol: "https",
        hostname: "yefhrkuqbjcblofdcpnr.supabase.co",
      },
      {
        protocol: "https",
        hostname: "images.unsplash.com",
      },
      {
        protocol: "https",
        hostname: "picsum.photos",
      },
      {
        protocol: "https",
        hostname: "unsplash.com",
      },
    ],
  },
  
};

export default nextConfig;
