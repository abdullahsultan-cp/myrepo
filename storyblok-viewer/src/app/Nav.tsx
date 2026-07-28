"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/archive", label: "Archive" },
  { href: "/tree", label: "Structure" },
  { href: "/inspect", label: "Inspector" },
];

export default function Nav() {
  const path = usePathname();
  return (
    <header className="nav">
      <Link href="/" className="nav-brand">
        <span className="nav-mark">AKU</span>
        <span>News migration</span>
      </Link>
      <nav className="nav-links">
        {LINKS.map((l) => {
          const on =
            l.href === "/" ? path === "/" : path.startsWith(l.href);
          return (
            <Link key={l.href} href={l.href} className={on ? "on" : ""}>
              {l.label}
            </Link>
          );
        })}
      </nav>
      <span className="nav-note">review build · not the live site</span>
    </header>
  );
}
