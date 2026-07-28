import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AKU news — migration review",
  description:
    "Faceted browser over the 3606 migrated AKU news stories: filter by structural element, writer, date and taxonomy.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
