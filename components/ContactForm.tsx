'use client';

import Link from 'next/link';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { EMAIL } from '@/lib/content';
import { KINDS, MESSAGE_MAX, TOPICS, mailtoFor, validate, type Enquiry, type FieldErrors } from '@/lib/enquiry';

type FieldName = 'name' | 'email' | 'company';
const FIELDS: { label: string; name: FieldName; type: string; ac: string }[] = [
  { label: 'Name', name: 'name', type: 'text', ac: 'name' },
  { label: 'Work email', name: 'email', type: 'email', ac: 'email' },
  { label: 'Company', name: 'company', type: 'text', ac: 'organization' },
];

const EMPTY = { name: '', email: '', company: '' };

/** "Talk to us" enquiry form. `extraTopics` are offered, pre-selected, ahead of the standard topics. */
export default function ContactForm({ extraTopics = [] }: { extraTopics?: string[] }) {
  const [f, setF] = useState(EMPTY);
  const [kind, setKind] = useState('');
  const [topics, setTopics] = useState<string[]>(extraTopics);
  const [msg, setMsg] = useState('');
  const [consent, setConsent] = useState(false);
  const [hp, setHp] = useState('');
  const [errs, setErrs] = useState<FieldErrors>({});
  const [touched, setTouched] = useState<Partial<Record<FieldName, boolean>>>({});
  const [tried, setTried] = useState(false);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState<{ name: string; email: string } | null>(null);
  const [failed, setFailed] = useState(false);

  const errRef = useRef<HTMLDivElement>(null);
  const failRef = useRef<HTMLDivElement>(null);
  const doneRef = useRef<HTMLDivElement>(null);
  const [focusTarget, setFocusTarget] = useState<'err' | 'fail' | 'done' | null>(null);

  useEffect(() => {
    if (!focusTarget) return;
    ({ err: errRef, fail: failRef, done: doneRef })[focusTarget].current?.focus();
    setFocusTarget(null);
  }, [focusTarget]);

  const enquiry = (): Enquiry => ({ ...f, kind, topics, message: msg, consent, website: hp });
  const mailHref = mailtoFor(enquiry(), EMAIL);

  const setField = (k: FieldName, v: string) => {
    const nf = { ...f, [k]: v };
    setF(nf);
    // Re-validate while typing once the field has shown an error.
    if (errs[k]) {
      const chk = validate(nf, consent);
      setErrs((e) => {
        const ne = { ...e };
        if (chk[k]) ne[k] = chk[k];
        else delete ne[k];
        return ne;
      });
    }
  };

  const blur = (k: FieldName) => {
    if (!touched[k] && !f[k]) return;
    const chk = validate(f, true);
    setErrs((e) => {
      const ne = { ...e };
      if (chk[k]) ne[k] = chk[k];
      else delete ne[k];
      return ne;
    });
    setTouched((t) => ({ ...t, [k]: true }));
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (hp || sending) return;
    const er = validate(f, consent);
    if (Object.keys(er).length) {
      setErrs(er);
      setTried(true);
      setFocusTarget('err');
      return;
    }
    setErrs({});
    setFailed(false);
    setSending(true);
    try {
      const res = await fetch('/api/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(enquiry()),
      });
      if (!res.ok) throw new Error(String(res.status));
      setSent({ name: f.name.trim(), email: f.email.trim() });
      setFocusTarget('done');
    } catch {
      setFailed(true);
      setFocusTarget('fail');
    } finally {
      setSending(false);
    }
  };

  const reset = () => {
    setF(EMPTY);
    setKind('');
    setTopics(extraTopics);
    setMsg('');
    setConsent(false);
    setErrs({});
    setTouched({});
    setTried(false);
    setFailed(false);
    setSent(null);
  };

  if (sent) {
    return (
      <div ref={doneRef} role="status" tabIndex={-1} style={{ borderTop: '1px solid #0A0A0A', paddingTop: 28, outline: 'none' }}>
        <div className="serif" style={{ fontSize: 'clamp(26px,2.6vw,34px)', lineHeight: 1.2, letterSpacing: '-0.02em' }}>
          Thank you, {sent.name.split(' ')[0]}.
        </div>
        <p style={{ margin: '12px 0 0', fontSize: 17, color: '#333333', textWrap: 'pretty' }}>
          Your enquiry has reached {EMAIL}. A partner will reply to {sent.email} within one working day.
        </p>
        <p style={{ margin: '10px 0 0', fontSize: 15, color: '#4F4F4F' }}>
          Anything to add? Write to{' '}
          <a href={'mailto:' + EMAIL} className="underline" style={{ color: '#0A0A0A' }}>
            {EMAIL}
          </a>
          .
        </p>
        <button type="button" className="btn-outline" onClick={reset} style={{ marginTop: 28 }}>
          Send another enquiry
        </button>
      </div>
    );
  }

  const errList: { msg: string; go: () => void }[] = (['name', 'email', 'company'] as const)
    .filter((k) => errs[k])
    .map((k) => ({ msg: errs[k]!, go: () => document.getElementById('ct-' + k)?.focus() }));
  if (errs.consent) errList.push({ msg: errs.consent, go: () => document.getElementById('ct-consent')?.focus() });

  return (
    <form onSubmit={submit} noValidate style={{ borderTop: '1px solid #0A0A0A', paddingTop: 8 }}>
      {tried && errList.length > 0 && (
        <div ref={errRef} role="alert" tabIndex={-1} style={{ margin: '18px 0 4px', padding: '14px 18px', border: '1px solid #0A0A0A', fontSize: 15, outline: 'none' }}>
          <div style={{ fontWeight: 700 }}>{errList.length === 1 ? 'One thing to check' : errList.length + ' things to check'}</div>
          {errList.map((e) => (
            <button key={e.msg} type="button" className="err-link" onClick={e.go}>
              {e.msg}
            </button>
          ))}
        </div>
      )}

      <fieldset style={{ border: 'none', margin: 0, padding: '22px 0 6px' }}>
        <legend className="field-label">I am writing for</legend>
        <div role="radiogroup" aria-label="I am writing for" style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
          {KINDS.map((k) => (
            <button key={k} type="button" role="radio" aria-checked={kind === k} className="choice" onClick={() => setKind(kind === k ? '' : k)}>
              {k}
            </button>
          ))}
        </div>
      </fieldset>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(min(100%,260px),1fr))', columnGap: 32 }}>
        {FIELDS.map((fd) => {
          const err = errs[fd.name];
          const errId = 'ct-' + fd.name + '-err';
          return (
            <label key={fd.name} htmlFor={'ct-' + fd.name} style={{ display: 'block', padding: '20px 0 6px' }}>
              <span className="field-label">{fd.label}</span>
              <input
                id={'ct-' + fd.name}
                name={fd.name}
                type={fd.type}
                autoComplete={fd.ac}
                maxLength={200}
                value={f[fd.name]}
                onChange={(e) => setField(fd.name, e.target.value)}
                onBlur={() => blur(fd.name)}
                aria-invalid={!!err}
                aria-required="true"
                aria-describedby={err ? errId : undefined}
                className="field-input"
              />
              {err && (
                <span id={errId} className="field-error">
                  ■ {err}
                </span>
              )}
            </label>
          );
        })}
      </div>

      <fieldset style={{ border: 'none', margin: 0, padding: '22px 0 6px' }}>
        <legend className="field-label">To discuss (optional)</legend>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
          {[...extraTopics, ...TOPICS].map((t) => {
            const on = topics.includes(t);
            return (
              <button
                key={t}
                type="button"
                aria-pressed={on}
                className="choice"
                onClick={() => setTopics(on ? topics.filter((x) => x !== t) : [...topics, t])}
              >
                {t}
              </button>
            );
          })}
        </div>
      </fieldset>

      <label htmlFor="ct-message" style={{ display: 'block', padding: '22px 0 6px' }}>
        <span className="field-label">Message (optional)</span>
        <textarea
          id="ct-message"
          name="message"
          rows={4}
          maxLength={MESSAGE_MAX}
          value={msg}
          onChange={(e) => setMsg(e.target.value)}
          aria-describedby="ct-msg-count"
          className="field-input"
          style={{ resize: 'vertical' }}
        />
        <span id="ct-msg-count" style={{ display: 'block', textAlign: 'right', fontSize: 12, color: '#4F4F4F', marginTop: 4 }}>
          {msg.length} / {MESSAGE_MAX}
        </span>
      </label>

      <label style={{ display: 'flex', gap: 12, alignItems: 'flex-start', padding: '18px 0 0', fontSize: 15, cursor: 'pointer' }}>
        <input
          id="ct-consent"
          type="checkbox"
          checked={consent}
          onChange={() => {
            setConsent(!consent);
            setErrs((e) => {
              const ne = { ...e };
              delete ne.consent;
              return ne;
            });
          }}
          aria-invalid={!!errs.consent}
          aria-describedby={errs.consent ? 'ct-consent-err' : undefined}
          style={{ width: 18, height: 18, margin: '2px 0 0', accentColor: '#0A0A0A', flex: 'none' }}
        />
        <span>
          I agree that Sarasin Picquart may use these details to reply.{' '}
          <Link href="/legal/privacy" className="underline" style={{ color: '#0A0A0A' }}>
            Privacy notice
          </Link>
        </span>
      </label>
      {errs.consent && (
        <span id="ct-consent-err" className="field-error" style={{ margin: '6px 0 0 30px' }}>
          ■ {errs.consent}
        </span>
      )}

      <input
        name="website"
        tabIndex={-1}
        autoComplete="off"
        aria-hidden="true"
        value={hp}
        onChange={(e) => setHp(e.target.value)}
        className="honeypot"
      />

      {failed && (
        <div ref={failRef} role="alert" tabIndex={-1} style={{ margin: '28px 0 0', padding: '14px 18px', border: '1px solid #0A0A0A', fontSize: 15, outline: 'none' }}>
          <div style={{ fontWeight: 700 }}>Your enquiry could not be sent.</div>
          <div style={{ paddingTop: 4 }}>
            <a href={mailHref} className="underline" style={{ color: '#0A0A0A' }}>
              Open it in your email app
            </a>{' '}
            or write to{' '}
            <a href={'mailto:' + EMAIL} className="underline" style={{ color: '#0A0A0A' }}>
              {EMAIL}
            </a>
            .
          </div>
        </div>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '16px 24px', marginTop: 32 }}>
        <button type="submit" className="btn-submit" disabled={sending}>
          {sending ? 'Sending…' : 'Send enquiry'}
        </button>
        <span style={{ fontSize: 14, color: '#4F4F4F' }}>Every enquiry is answered personally.</span>
      </div>
    </form>
  );
}
