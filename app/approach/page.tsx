import type { Metadata } from 'next';
import HowWeWork from '@/components/HowWeWork';
import WhoWeWorkWith from '@/components/WhoWeWorkWith';

export const metadata: Metadata = { title: 'Our approach' };

export default function ApproachPage() {
  return (
    <>
      <WhoWeWorkWith />
      <HowWeWork />
    </>
  );
}
