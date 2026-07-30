/** @type {import('next').NextConfig} */
const nextConfig = {
  // Allows CI/local verification to build beside an active `next dev` process.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  output: "standalone"
};

export default nextConfig;
