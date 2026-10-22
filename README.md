# Sarasin Picquart website

The marketing site for Sarasin Picquart, built from the high-fidelity design handoff (`SP Site.dc.html`).
It uses Next.js (App Router), TypeScript and plain CSS.

## Routes

| Path | Content |
| --- | --- |
| `/` | Hero, Services (with "In renewables"), Our approach, Proof (count-up), Europe |
| `/services` | Services, The platform (`#portal`) |
| `/approach` | Who we work with (`#who`), How we work (`#how`) |
| `/team` | Team hero, Europe |
| `/contact` | Talk to us: the enquiry form |
| `/demo` | Request demo access: the same form, with "A portal demo" preselected (a stand-in until the portal demo ships) |
| `/legal`, `/legal/privacy` | Legal placeholders |
| `POST /api/contact` | Emails enquiries to info@sarasinpicquart.com |

## Develop

```bash
npm install
npm run dev        # http://localhost:3000
npm run typecheck
npm run build && npm start
```

## Contact form delivery

`/api/contact` validates the enquiry, drops honeypot (`website`) submissions without telling the sender, limits each IP to 5 enquiries per 10 minutes, and sends the email through [Resend](https://resend.com).

Copy `.env.example` to `.env.local` and set:

- `RESEND_API_KEY`: your Resend API key.
- `CONTACT_FROM`: a sender address on a domain verified in Resend.

Without a key the endpoint returns 503. The form then offers a pre-filled `mailto:` link as a fallback.

Because of this endpoint the site runs on a Node server (for example Vercel), not as a static export. All the pages themselves are still prerendered as static HTML.

The rate limit lives in memory, so it applies per server instance. Behind several instances or serverless functions, back it with a shared store if you need a hard limit.

## Before launch

- Remove `robots: { index: false }` in `app/layout.tsx`. It was carried over from the prototype.
- Fill in the placeholders: registered name, company number, registered office, privacy notice and the LinkedIn URL (`LINKEDIN` in `lib/content.ts`).
- Supply the four black-and-white photos for "Who we work with". They currently show placeholder text in `components/WhoWeWorkWith.tsx`.

## Where things live

- `lib/content.ts`: all approved copy and data (services, platform, audiences, flows, Europe tiles).
- `lib/enquiry.ts`: form validation and email formatting. Both the client and the server use it.
- `lib/tabs.ts`: WAI-ARIA tabs with roving `tabIndex`, arrow, Home and End keys, and the .25s cross-fade.
- `components/Reveal.tsx`: the scroll reveal for `[data-reveal]`. It is turned off under `prefers-reduced-motion`.
