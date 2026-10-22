import ApproachColumns from '@/components/ApproachColumns';
import Europe from '@/components/Europe';
import HomeHero from '@/components/HomeHero';
import Proof from '@/components/Proof';
import ServicesBlock from '@/components/ServicesBlock';

export default function Home() {
  return (
    <>
      <HomeHero />
      <ServicesBlock variant="home" />
      <ApproachColumns />
      <Proof />
      <Europe ruled />
    </>
  );
}
