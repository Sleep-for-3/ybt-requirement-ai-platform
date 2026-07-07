import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "一表通字段口径智能辅助平台",
  description: "银行一表通字段级口径智能辅助平台 MVP"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
