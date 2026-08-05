import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Toaster } from "@/components/ui/toaster";
import { ThemeProvider } from "next-themes";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Observatorio ENSO Perú — Monitoreo costero y de cuenca",
  description:
    "Plataforma de monitoreo de indicadores ENSO costeros (El Niño Costero, ICEN, Niño 1+2) y de cuenca (Niño 3.4, RONI, SOI, D20, viento zonal 850 hPa) con fuentes oficiales NOAA y ENFEN.",
  keywords: [
    "ENSO",
    "El Niño Costero",
    "ICEN",
    "ENFEN",
    "Niño 1+2",
    "Niño 3.4",
    "RONI",
    "SOI",
    "D20",
    "termoclina",
    "Perú",
    "NOAA",
    "observatorio",
  ],
  authors: [{ name: "Observatorio ENSO Perú" }],
  lang: "es",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-background text-foreground`}
      >
        <ThemeProvider attribute="class" defaultTheme="light" enableSystem disableTransitionOnChange>
          {children}
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
