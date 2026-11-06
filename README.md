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

`/api/contact` validates the enquiry, drops honeypot (`website`) submissions without telling the sender, and limits each IP to 5 enquiries per 10 minutes. It then sends the email to info@sarasinpicquart.com through Google Workspace: a mailbox on the domain signs in to Gmail's SMTP server (`smtp.gmail.com`) with an app password. The visitor's address goes in Reply-To, so you can answer straight from Gmail.

It needs two environment variables (see `.env.example`):

- `GMAIL_USER`: the Workspace mailbox that sends, for example `website@sarasinpicquart.com`.
- `GMAIL_APP_PASSWORD`: a 16-character app password for that mailbox.

Without them the endpoint returns 503. If Gmail rejects the login or can't be reached within 8 seconds, it returns 502. In both cases the form offers a pre-filled `mailto:` link instead.

### Setting up the Google Workspace mailbox

1. **Choose the sending mailbox.** In the Admin console (admin.google.com), go to Directory → Users and create a user such as `website@sarasinpicquart.com`. This takes a Workspace licence. To avoid that, you can use an existing user's mailbox (for example `info@`, if it is a real user and not a group or an alias).
2. **Allow 2-Step Verification.** Google only offers app passwords to accounts with 2-Step Verification on. In the Admin console, go to Security → Authentication → 2-Step Verification and tick "Allow users to turn on 2-Step Verification" for that user's organisational unit.
3. **Turn it on for the mailbox.** Sign in as that user, open myaccount.google.com → Security → 2-Step Verification, and turn it on.
4. **Create the app password.** Still signed in as that user, open myaccount.google.com/apppasswords, name it "Website" and copy the 16-character password (without spaces). Google shows it only once.
5. **Store it.** Put the two values in the hosting provider's environment variables (see below), never in the code.

If the app password page says the setting isn't available, the account has 2-Step Verification off, uses security keys only, or is in Advanced Protection.

Gmail allows about 2,000 messages a day per user, far more than a contact form needs.

## Deploying to your domain

These steps use Vercel, which is made by the company behind Next.js and runs this project, the API route included, with no changes. The free Hobby plan is for non-commercial use, so a company site should be on the Pro plan.

1. **Merge the code.** Merge the pull request into `main` on GitHub. Vercel deploys `main` as the live site.
2. **Create the Vercel project.** Sign up at vercel.com with GitHub, choose Add New → Project, and import this repository. Vercel detects Next.js; keep the default build settings.
3. **Add the environment variables.** Before the first deploy (or later, under Settings → Environment Variables), add `GMAIL_USER` and `GMAIL_APP_PASSWORD` for the Production environment. After changing a variable, redeploy (Deployments → … → Redeploy) for it to take effect.
4. **Deploy and check.** Vercel builds the site and gives it a temporary address such as `your-project.vercel.app`. Open it, click through the pages and send a test enquiry from the contact form.
5. **Add your domain.** In the project, go to Settings → Domains and add `sarasinpicquart.com` and `www.sarasinpicquart.com`. Vercel suggests redirecting one to the other; pick which one is the main address.
6. **Point the DNS at Vercel.** At the company that manages the domain's DNS (the registrar, or Cloudflare, or wherever the nameservers point), add the records Vercel shows on the Domains page. They are usually:
   - for `sarasinpicquart.com`: an **A** record with the IP address Vercel gives (often `76.76.21.21`);
   - for `www`: a **CNAME** record pointing to the name Vercel gives (often `cname.vercel-dns.com`).

   Delete any old A, AAAA or CNAME records for the same names that point at a previous website.

   **Do not touch the MX, SPF (TXT `v=spf1 …`), DKIM or DMARC records.** Those deliver the company's Google Workspace email, and changing them stops email from working.
7. **Wait for it to go live.** DNS changes usually take minutes, sometimes up to 48 hours. The Domains page shows "Valid Configuration" when it works, and Vercel then issues the HTTPS certificate automatically.
8. **Open the site to search engines.** Remove the `robots: { index: false, follow: false }` line in `app/layout.tsx` and merge. Every push to `main` from then on deploys automatically, and every pull request gets its own preview address.

Other hosts that run Next.js with API routes (Netlify, Render, Google Cloud Run, or your own Node server with `npm run build && npm start`) also work. Static-only hosting such as GitHub Pages does not, because the contact form needs the server.

## Before launch

- Remove `robots: { index: false }` in `app/layout.tsx`. It was carried over from the prototype.
- Send a real enquiry from the live site and check it arrives at info@sarasinpicquart.com.
- Fill in the placeholders: registered name, company number, registered office, privacy notice and the LinkedIn URL (`LINKEDIN` in `lib/content.ts`).
- Supply the four black-and-white photos for "Who we work with". They currently show placeholder text in `components/WhoWeWorkWith.tsx`.

## Where things live

- `lib/content.ts`: all approved copy and data (services, platform, audiences, flows, Europe tiles).
- `lib/enquiry.ts`: form validation and email formatting. Both the client and the server use it.
- `lib/tabs.ts`: WAI-ARIA tabs with roving `tabIndex`, arrow, Home and End keys, and the .25s cross-fade.
- `components/Reveal.tsx`: the scroll reveal for `[data-reveal]`. It is turned off under `prefers-reduced-motion`.
