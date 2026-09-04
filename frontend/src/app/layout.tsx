import type { Metadata } from "next";
import { Geist, Geist_Mono, Instrument_Serif } from "next/font/google";
import { AppProviders } from "@/providers/app-providers";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const instrumentSerif = Instrument_Serif({
  variable: "--font-display",
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
});

export const metadata: Metadata = {
  title: {
    default: "Synapse — AI Healthcare Platform for Clinics",
    template: "%s · Synapse",
  },
  description:
    "Synapse is the multi-tenant AI healthcare platform that helps clinics manage operations and engage patients through an intelligent chatbot.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Paint handoff/boot bg before React hydrates so dark mode doesn't flash white. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var h=sessionStorage.getItem("synapse_handoff_active");var t=localStorage.getItem("synapse-dashboard-theme");if(h||t==="dark"){document.documentElement.style.background=t==="dark"?"#0c0e14":"#f4f5fa";document.documentElement.style.colorScheme=t==="dark"?"dark":"light";}}catch(e){}})();`,
          }}
        />
      </head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} ${instrumentSerif.variable} font-sans antialiased`}
      >
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
