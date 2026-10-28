import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Project Interview Lab",
  description: "基于项目证据的模拟面试与复盘",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
