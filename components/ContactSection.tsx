import Link from 'next/link';
import { EMAIL, LINKEDIN } from '@/lib/content';
import ContactForm from './ContactForm';

const asideLink = { display: 'block', marginTop: 6, fontSize: 22 } as const;

/** Enquiry form with the Email / Elsewhere / See it first column. */
export default function ContactSection({ extraTopics }: { extraTopics?: string[] }) {
  return (
    <section className="paper">
      <div className="wrap">
        <div
          className="rail"
          style={{ paddingTop: 'clamp(64px,8vw,112px)', display: 'flex', flexWrap: 'wrap', gap: '48px clamp(48px,7vw,112px)' }}
        >
          <div style={{ flex: '1.6 1 420px', minWidth: 0, maxWidth: 760 }}>
            <ContactForm extraTopics={extraTopics} />
          </div>
          <div style={{ flex: '1 1 260px', minWidth: 0, display: 'flex', flexDirection: 'column', gap: 24 }}>
            <div style={{ borderTop: '1px solid #0A0A0A', paddingTop: 18 }}>
              <div className="field-label">Email</div>
              <a href={'mailto:' + EMAIL} className="serif" style={asideLink}>
                {EMAIL}
              </a>
            </div>
            <div style={{ borderTop: '1px solid #E5E5E3', paddingTop: 18 }}>
              <div className="field-label">Elsewhere</div>
              <a href={LINKEDIN} className="serif" style={asideLink}>
                LinkedIn
              </a>
            </div>
            <div style={{ borderTop: '1px solid #E5E5E3', paddingTop: 18 }}>
              <div className="field-label">See it first</div>
              <Link href="/demo" className="serif" style={asideLink}>
                Request demo access →
              </Link>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
