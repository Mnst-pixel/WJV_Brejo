import "@fontsource/montserrat/400.css";
import "@fontsource/montserrat/500.css";
import "@fontsource/montserrat/600.css";
import "@fontsource/montserrat/700.css";
import "./globals.css";

import type { Metadata, Viewport } from "next";

export const metadata: Metadata = {
  title: {default: "Kairós", template: "%s · Kairós"},
  description: "Ambiente de estudos para a preparação da OAB.",
  icons: {icon: "/app/mini-icone.png"},
};

export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#1E312A",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
