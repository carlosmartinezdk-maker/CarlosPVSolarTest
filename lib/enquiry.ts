// Shared by the contact form (client) and /api/contact (server).

export type Enquiry = {
  name: string;
  email: string;
  company: string;
  kind: string;
  topics: string[];
  message: string;
  consent: boolean;
  website?: string; // honeypot
};

export type FieldErrors = Partial<Record<'name' | 'email' | 'company' | 'consent', string>>;

export const MESSAGE_MAX = 1200;
export const KINDS = ['A fund', 'A portfolio company', 'Real assets', 'Something else'];
export const TOPICS = ['Finance-as-a-Service', 'Flex-up finance', 'Advisory'];
export const DEMO_TOPIC = 'A portal demo';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const FREE_EMAIL_RE = /@(gmail|yahoo|hotmail|outlook|icloud|proton)\./i;

export function validate(f: Pick<Enquiry, 'name' | 'email' | 'company'>, consent: boolean): FieldErrors {
  const e: FieldErrors = {};
  if (!f.name.trim()) e.name = 'Please add your name.';
  if (!EMAIL_RE.test(f.email.trim())) e.email = 'Please add a valid work email.';
  else if (FREE_EMAIL_RE.test(f.email)) e.email = 'Please use your work email.';
  if (!f.company.trim()) e.company = 'Please add your company.';
  if (!consent) e.consent = 'Please agree so we can reply.';
  return e;
}

export function subjectFor(f: Pick<Enquiry, 'name' | 'company'>): string {
  return 'Enquiry from ' + f.name.trim() + (f.company.trim() ? ', ' + f.company.trim() : '');
}

export function bodyFor(f: Enquiry): string {
  const lines = ['Name: ' + f.name.trim(), 'Work email: ' + f.email.trim(), 'Company: ' + f.company.trim()];
  if (f.kind) lines.push('Writing for: ' + f.kind);
  if (f.topics.length) lines.push('To discuss: ' + f.topics.join(', '));
  if (f.message.trim()) lines.push('', f.message.trim());
  return lines.join('\n');
}

export function mailtoFor(f: Enquiry, to: string): string {
  return 'mailto:' + to + '?subject=' + encodeURIComponent(subjectFor(f)) + '&body=' + encodeURIComponent(bodyFor(f));
}
