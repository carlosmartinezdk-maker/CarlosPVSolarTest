import type { Metadata } from 'next';
import Platform from '@/components/Platform';
import ServicesBlock from '@/components/ServicesBlock';

export const metadata: Metadata = { title: 'Services' };

export default function ServicesPage() {
  return (
    <>
      <ServicesBlock variant="services" />
      <Platform />
    </>
  );
}
