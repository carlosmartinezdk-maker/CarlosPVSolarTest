import type { Metadata } from 'next';
import { LegalBody, LegalDetails, PrivacyNotice } from '@/components/LegalDetails';
import PageHero from '@/components/PageHero';

export const metadata: Metadata = { title: 'Legal notice' };

export default function LegalPage() {
  return (
    <>
      <PageHero tight label="Legal" title="Legal notice" />
      <LegalBody>
        <LegalDetails />
        <h2
          id="privacy"
          className="h2"
          style={{ margin: 'clamp(64px,8vw,104px) 0 0', fontSize: 'clamp(32px,3.6vw,48px)', lineHeight: 1.1 }}
        >
          Privacy
        </h2>
        <PrivacyNotice />
      </LegalBody>
    </>
  );
}
