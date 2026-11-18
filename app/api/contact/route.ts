import { NextResponse } from 'next/server';
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

  // Sent through Microsoft 365 with Microsoft Graph: an app registered in
  // Entra ID sends as the sender mailbox, using the client-credentials flow.
  const { MS_TENANT_ID: tenant, MS_CLIENT_ID: clientId, MS_CLIENT_SECRET: secret, MAIL_SENDER: sender } = process.env;
  if (!tenant || !clientId || !secret || !sender) return NextResponse.json({ error: 'not_configured' }, { status: 503 });

  try {
    await sendMail({ tenant, clientId, secret, sender }, enquiry);
  } catch (err) {
    console.error('Contact form delivery failed', err);
    return NextResponse.json({ error: 'delivery_failed' }, { status: 502 });
  }
  return NextResponse.json({ ok: true });
}

type GraphConfig = { tenant: string; clientId: string; secret: string; sender: string };

// Short timeouts so a visitor gets the mailto fallback quickly if Microsoft is unreachable.
const TIMEOUT_MS = 8000;

async function sendMail(cfg: GraphConfig, enquiry: Enquiry) {
  const tokenRes = await fetch(`https://login.microsoftonline.com/${encodeURIComponent(cfg.tenant)}/oauth2/v2.0/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'client_credentials',
      client_id: cfg.clientId,
      client_secret: cfg.secret,
      scope: 'https://graph.microsoft.com/.default',
    }),
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (!tokenRes.ok) throw new Error(`Token request failed: ${tokenRes.status} ${await tokenRes.text()}`);
  const { access_token: token } = (await tokenRes.json()) as { access_token: string };

  const mailRes = await fetch(`https://graph.microsoft.com/v1.0/users/${encodeURIComponent(cfg.sender)}/sendMail`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message: {
        subject: subjectFor(enquiry),
        body: { contentType: 'Text', content: bodyFor(enquiry) },
        toRecipients: [{ emailAddress: { address: EMAIL } }],
        replyTo: [{ emailAddress: { address: enquiry.email.trim(), name: enquiry.name.trim() } }],
      },
      saveToSentItems: false,
    }),
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  // Graph answers 202 Accepted when the message is queued.
  if (!mailRes.ok) throw new Error(`sendMail failed: ${mailRes.status} ${await mailRes.text()}`);
}
