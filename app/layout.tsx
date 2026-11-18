import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';
import { Closing, Footer } from '@/components/Footer';
import Header from '@/components/Header';
import Reveal from '@/components/Reveal';
import './globals.css';

export const metadata: Metadata = {
  title: { default: 'Sarasin Picquart', template: '%s · Sarasin Picquart' },
  description:
    'We deliver an institutional-grade finance function through expert people, standardised processes, and AI-enabled technology.',
  // Remove before launch to allow indexing.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { themeColor: '#0A0A0A' };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en-GB">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,300;6..72,400&family=Hanken+Grotesk:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap"
        />
      </head>
      <body>
        <div className="site">
          <Header />
          <main>{children}</main>
          <Closing />
          <Footer />
        </div>
        <Reveal />
      </body>
    </html>
  );
}
