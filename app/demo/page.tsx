import type { Metadata } from 'next';
import ContactSection from '@/components/ContactSection';
import PageHero from '@/components/PageHero';
import { DEMO_TOPIC } from '@/lib/enquiry';

export const metadata: Metadata = { title: 'Request demo access' };

// Stand-in until the client-portal demo ships: the contact form, preset to a portal demo.
export default function DemoPage() {
  return (
    <>
      <PageHero tight label="Portal demo" title="Request demo access." lede="Request demo access and we'll send you a code." />
      <ContactSection extraTopics={[DEMO_TOPIC]} />
    </>
  );
}
