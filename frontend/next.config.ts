import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  // 后端 (FastAPI) 用尾斜杠区分 collection 路由；关掉 Next 的尾斜杠重定向，
  // 让 /api/xxx/ 原样转发给后端，避免与后端重定向形成循环。
  skipTrailingSlashRedirect: true,
  experimental: {
    workerThreads: true,
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001"}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
