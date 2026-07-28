import type { Metadata } from "next";
import Nav from "./Nav";
import "./globals.css";
import "./pages.css";

export const metadata: Metadata = {
  title: "AKU News — migration review",
  description:
    "Reader, archive, folder structure and inspector for the 3606 migrated AKU news stories.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <Nav />
        <main className="page">{children}</main>
      </body>
    </html>
  );
}
