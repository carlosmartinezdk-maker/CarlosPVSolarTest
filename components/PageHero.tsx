import type { ReactNode } from 'react';
import SectionHead from './SectionHead';

/** Black hero used on the inner pages (Team, Contact, Legal, Demo). */
export default function PageHero({ label, title, lede, tight }: { label: string; title: ReactNode; lede?: ReactNode; tight?: boolean }) {
  return (
    <section className="dark">
      <div className="wrap">
        <div className="rail" style={tight ? { paddingBottom: 'clamp(64px,8vw,104px)' } : undefined}>
          <SectionHead as="h1" label={label} title={title} />
          {lede && (
            <p className="lede" style={tight ? { marginTop: 24, maxWidth: 560 } : undefined}>
              {lede}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
