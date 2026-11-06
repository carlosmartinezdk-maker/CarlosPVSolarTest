import { NextResponse } from 'next/server';
import nodemailer from 'nodemailer';
import { EMAIL } from '@/lib/content';
import { MESSAGE_MAX, bodyFor, subjectFor, validate, type Enquiry } from '@/lib/enquiry';

export const runtime = 'nodejs';

// Best-effort, per-instance rate limit: 5 enquiries per IP per 10 minutes.
const WINDOW_MS = 10 * 60 * 1000;
const LIMIT = 5;
const hits = new Map<string, number[]>();

function limited(ip: string): boolean {
  const now = Date.now();
  const recent = (hits.get(ip) ?? []).filter((t) => now - t < WINDOW_MS);
  if (recent.length >= LIMIT) {
    hits.set(ip, recent);
    return true;
  }
  recent.push(now);
  hits.set(ip, recent);
  if (hits.size > 5000) {
    for (const [k, v] of hits) if (v.every((t) => now - t >= WINDOW_MS)) hits.delete(k);
  }
  return false;
}

const str = (v: unknown, max: number) => (typeof v === 'string' ? v.slice(0, max) : '');

export async function POST(req: Request) {
  let raw: Record<string, unknown>;
  try {
    raw = await req.json();
  } catch {
    return NextResponse.json({ error: 'invalid_json' }, { status: 400 });
  }

  const enquiry: Enquiry = {
    name: str(raw.name, 200),
    email: str(raw.email, 200),
    company: str(raw.company, 200),
    kind: str(raw.kind, 100),
    topics: Array.isArray(raw.topics) ? raw.topics.slice(0, 10).map((t) => str(t, 100)).filter(Boolean) : [],
    message: str(raw.message, MESSAGE_MAX),
    consent: raw.consent === true,
    website: str(raw.website, 200),
  };

  // Honeypot filled: accept silently so bots learn nothing.
  if (enquiry.website) return NextResponse.json({ ok: true });

  const errors = validate(enquiry, enquiry.consent);
  if (Object.keys(errors).length) return NextResponse.json({ error: 'invalid', errors }, { status: 422 });

  const ip = (req.headers.get('x-forwarded-for') ?? '').split(',')[0].trim() || req.headers.get('x-real-ip') || 'unknown';
  if (limited(ip)) return NextResponse.json({ error: 'rate_limited' }, { status: 429 });

  // Sent through Google Workspace: a mailbox on the domain signs in to Gmail's
  // SMTP server with an app password.
  const user = process.env.GMAIL_USER;
  const pass = process.env.GMAIL_APP_PASSWORD;
  if (!user || !pass) return NextResponse.json({ error: 'not_configured' }, { status: 503 });

  try {
    // Short timeouts so a visitor gets the mailto fallback quickly if Gmail is unreachable.
    const transport = nodemailer.createTransport({
      host: 'smtp.gmail.com',
      port: 465,
      secure: true,
      auth: { user, pass },
      connectionTimeout: 8000,
      greetingTimeout: 8000,
      socketTimeout: 15000,
    });
    await transport.sendMail({
      from: { name: 'Sarasin Picquart website', address: user },
      to: EMAIL,
      replyTo: enquiry.email.trim(),
      subject: subjectFor(enquiry),
      text: bodyFor(enquiry),
    });
  } catch (err) {
    console.error('Contact form delivery failed', err);
    return NextResponse.json({ error: 'delivery_failed' }, { status: 502 });
  }
  return NextResponse.json({ ok: true });
}
