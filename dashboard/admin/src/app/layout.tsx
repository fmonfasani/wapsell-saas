import type { Metadata } from "next";
import Link from "next/link";
import { UserMenu } from "@/components/UserMenu";
import "./globals.css";

export const metadata: Metadata = {
  title: "Wapsell Admin",
  description: "Administración de tenants Wapsell (WhatsApp Sales SaaS).",
};

const NAV = [
  { href: "/tenants", label: "Tenants" },
  { href: "/skills", label: "Skills" },
  { href: "/health", label: "Health" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body>
        <div className="min-h-screen flex flex-col">
          <header className="border-b border-slate-200 bg-white">
            <div className="max-w-5xl mx-auto px-4 h-14 flex items-center justify-between">
              <Link href="/" className="font-semibold text-brand-700 text-lg">
                Wapsell <span className="text-slate-400 font-normal">admin</span>
              </Link>
              <div className="flex items-center gap-6">
                <nav className="flex gap-4">
                  {NAV.map((item) => (
                    <Link
                      key={item.href}
                      href={item.href}
                      className="text-slate-600 hover:text-brand-600 text-sm font-medium"
                    >
                      {item.label}
                    </Link>
                  ))}
                </nav>
                <UserMenu />
              </div>
            </div>
          </header>
          <main className="flex-1 max-w-5xl w-full mx-auto px-4 py-8">
            {children}
          </main>
          <footer className="border-t border-slate-200 text-xs text-slate-400 text-center py-3">
            Wapsell admin · WhatsApp Sales SaaS
          </footer>
        </div>
      </body>
    </html>
  );
}
