import type { Metadata } from "next";
import { AppShell } from "@/components/AppShell";
import { QueryProvider } from "@/components/QueryProvider";
import { ToastProvider } from "@/components/feedback/ToastProvider";
import "./globals.css";

export const metadata: Metadata = {
  title: "一表通字段口径智能辅助平台",
  description: "银行一表通字段级口径智能辅助平台 MVP"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body><QueryProvider><ToastProvider><AppShell>{children}</AppShell></ToastProvider></QueryProvider></body>
    </html>
  );
}
