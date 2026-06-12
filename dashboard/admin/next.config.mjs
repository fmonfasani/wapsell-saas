/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Standalone output emits a self-contained .next/standalone tree so the
  // production Docker image runs without node_modules at runtime. See
  // infra/docker/Dockerfile.dashboard.
  output: "standalone",
  // The API base is read at build/runtime from NEXT_PUBLIC_API_URL;
  // defaulting here keeps `npm run build` reproducible.
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  },
};
export default nextConfig;
