import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PixelSave",
  description: "MVP para descargar medios publicos con jobs en segundo plano."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}

