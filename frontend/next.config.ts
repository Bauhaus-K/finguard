import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Docker 이미지 빌드 시에만 standalone 출력 (next start 와 호환되지 않음)
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  poweredByHeader: false,
};

export default nextConfig;
