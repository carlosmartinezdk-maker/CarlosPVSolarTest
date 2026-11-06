import type { Metadata } from 'next';
import ContactSection from '@/components/ContactSection';
import PageHero from '@/components/PageHero';

export const metadata: Metadata = { title: 'Talk to us' };

export default function ContactPage() {
  return (
    <>
      <PageHero tight label="Contact" title="Talk to us." lede="We work with a small number of clients at a time, by introduction or enquiry." />
      <ContactSection />
    </>
  );
}
