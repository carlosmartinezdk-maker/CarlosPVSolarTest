import type { Metadata } from 'next';
import Europe from '@/components/Europe';
import PageHero from '@/components/PageHero';

export const metadata: Metadata = { title: 'Team' };

export default function TeamPage() {
  return (
    <>
      <PageHero
        label="Team"
        title={
          <>
            <span>Same team.</span>
            <span className="dim">New vision.</span>
          </>
        }
        lede="For seven years we have run the finance behind renewable energy, now more than 300 entities, closed to a calendar every month across six jurisdictions. Now we bring that discipline to real assets and the companies funds back, in every industry."
      />
      <Europe />
    </>
  );
}
