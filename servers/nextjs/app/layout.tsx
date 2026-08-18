import type { Metadata } from "next";
import localFont from "next/font/local";
// import { Manrope, Syne, Unbounded } from "next/font/google";
import "./globals.css";
import "katex/dist/katex.min.css";
import { Providers } from "./providers";
import MixpanelInitializer from "./MixpanelInitializer";
import { Toaster } from "@/components/ui/sonner";
import RouteTheme from "./RouteTheme";
const inter = localFont({
  src: [
    {
      path: "./fonts/Inter.ttf",
      weight: "400",
      style: "normal",
    },
  ],
  variable: "--font-inter",
});

// const syne = Syne({
//   subsets: ["latin"],
//   weight: ["400", "500", "600", "700", "800"],
//   variable: "--font-syne",
// });

// const manrope = Manrope({
//   subsets: ["latin"],
//   weight: ["400", "500", "600", "700", "800"],
//   variable: "--font-manrope",
// });

// const unbounded = Unbounded({
//   subsets: ["latin"],
//   weight: ["400", "500", "600", "700", "800"],
//   variable: "--font-unbounded",
// });

export const metadata: Metadata = {
  metadataBase: new URL("https://presenton.ai"),
  title: "Presentation Studio",
  description:
    "Open-source AI presentation generator with custom layouts, multi-model support (OpenAI, Gemini, Ollama), and PDF/PPTX export. A free Gamma alternative.",
  keywords: [
    "AI presentation generator",
    "data storytelling",
    "data visualization tool",
    "AI data presentation",
    "presentation generator",
    "data to presentation",
    "interactive presentations",
    "professional slides",
  ],
  icons: null, 
  openGraph: {
    title: "Presentation Studio",
    description:
      "Open-source AI presentation generator with custom layouts, multi-model support (OpenAI, Gemini, Ollama), and PDF/PPTX export. A free Gamma alternative.",
    url: "https://presenton.ai",
    siteName: "Presentation Studio",
    
    type: "website",
    locale: "en_US",
  },
  alternates: {
    canonical: "https://presenton.ai",
  },
  twitter: {
    card: "summary_large_image",
    title: "Presentation Studio",
    description:
      "Open-source AI presentation generator with custom layouts, multi-model support (OpenAI, Gemini, Ollama), and PDF/PPTX export. A free Gamma alternative.",
    images: ["/presentation-studio-logo.png"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {

  return (
    <html lang="en">
      <body
        className={`${inter.variable} antialiased`}
      >
        <RouteTheme />
        <Providers>
          <MixpanelInitializer>

            {children}

          </MixpanelInitializer>
        </Providers>
        <Toaster position="top-center" />
      </body>
    </html>
  );
}
