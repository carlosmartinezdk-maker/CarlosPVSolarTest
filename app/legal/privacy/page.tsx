import type { Metadata } from 'next';
import { LegalBody, PrivacyNotice } from '@/components/LegalDetails';
import PageHero from '@/components/PageHero';

export const metadata: Metadata = { title: 'Privacy' };

export default function PrivacyPage() {
  return (
    <>
      <PageHero tight label="Legal" title="Privacy" />
      <LegalBody>
        <div style={{ borderTop: '1px solid #0A0A0A', maxWidth: 760 }}>
          <PrivacyNotice />
        </div>
      </LegalBody>
    </>
  );
}
