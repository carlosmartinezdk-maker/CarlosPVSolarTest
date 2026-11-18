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

`/api/contact` validates the enquiry, drops honeypot (`website`) submissions without telling the sender, and limits each IP to 5 enquiries per 10 minutes. It then sends the email to info@sarasinpicquart.com through Microsoft 365, using Microsoft Graph: an app registered in Microsoft Entra ID sends as a company mailbox. The visitor's address goes in Reply-To, so you can answer straight from Outlook.

It needs four environment variables (see `.env.example`):

- `MS_TENANT_ID`: the Directory (tenant) ID of the Microsoft 365 organisation.
- `MS_CLIENT_ID`: the Application (client) ID of the app registration.
- `MS_CLIENT_SECRET`: a client secret of the app registration.
- `MAIL_SENDER`: the mailbox the enquiries are sent from, for example `website@sarasinpicquart.com`.

Without them the endpoint returns 503. If Microsoft rejects the request or doesn't answer within 8 seconds, it returns 502. In both cases the form offers a pre-filled `mailto:` link instead.

### Setting up Microsoft 365

1. **Create the sending mailbox.** In the Microsoft 365 admin center (admin.microsoft.com), go to Teams & groups → Shared mailboxes → Add a shared mailbox, named for example "Website" with the address `website@sarasinpicquart.com`. Shared mailboxes need no licence. (You can also send from `info@` itself.)
2. **Register the app.** In the Microsoft Entra admin center (entra.microsoft.com), go to Identity → Applications → App registrations → New registration. Name it "Website contact form", keep "Accounts in this organizational directory only", leave the Redirect URI empty, and click Register. From the Overview page, copy the **Application (client) ID** and the **Directory (tenant) ID**.
3. **Give it permission to send mail.** In the app, go to API permissions → Add a permission → Microsoft Graph → **Application permissions**, tick **Mail.Send**, and click Add permissions. Then click **Grant admin consent for (your organisation)** and confirm. The status column should show a green tick.
4. **Create a client secret.** Go to Certificates & secrets → Client secrets → New client secret, describe it as "Vercel", and choose the longest expiry (24 months). Copy the **Value** column straight away; it is shown only once. Put a reminder in the calendar to create a new one before it expires.
5. **Limit the app to the one mailbox (strongly recommended).** Mail.Send on its own lets the app send as *any* mailbox in the organisation. Restrict it in Exchange Online PowerShell (`Install-Module ExchangeOnlineManagement`, then `Connect-ExchangeOnline`):
   - Create a mail-enabled security group containing only the sending mailbox, for example `website-senders@sarasinpicquart.com`.
   - Run `New-ApplicationAccessPolicy -AppId <Application (client) ID> -PolicyScopeGroupId website-senders@sarasinpicquart.com -AccessRight RestrictAccess -Description "Website contact form"`.
   - Check it with `Test-ApplicationAccessPolicy -Identity website@sarasinpicquart.com -AppId <Application (client) ID>` (should say Granted) and with another mailbox (should say Denied). The policy can take up to an hour to apply.

   Microsoft is moving this feature to "RBAC for Applications" in Exchange Online. If the command is no longer available, use that instead to scope the app to the one mailbox.
6. **Store the values** in the hosting provider's environment variables (see below), never in the code.

If Microsoft 365 was bought through GoDaddy, GoDaddy may limit access to the Entra admin center. If you can't open App registrations, ask GoDaddy support for the access, or for help moving to a direct Microsoft subscription.

## Deploying to your domain

These steps use Vercel, which is made by the company behind Next.js and runs this project, the API route included, with no changes. The free Hobby plan is for non-commercial use, so a company site should be on the Pro plan.

1. **Merge the code.** Merge the pull request into `main` on GitHub. Vercel deploys `main` as the live site.
2. **Create the Vercel project.** Sign up at vercel.com with GitHub, choose Add New → Project, and import this repository. Vercel detects Next.js; keep the default build settings.
3. **Add the environment variables.** Before the first deploy (or later, under Settings → Environment Variables), add `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET` and `MAIL_SENDER` for the Production environment. After changing a variable, redeploy (Deployments → … → Redeploy) for it to take effect.
4. **Deploy and check.** Vercel builds the site and gives it a temporary address such as `your-project.vercel.app`. Open it, click through the pages and send a test enquiry from the contact form.
5. **Add your domain.** In the project, go to Settings → Domains and add `sarasinpicquart.com` and `www.sarasinpicquart.com`. Vercel suggests redirecting one to the other; pick which one is the main address.
6. **Point the DNS at Vercel.** At the company that manages the domain's DNS (the registrar, or Cloudflare, or wherever the nameservers point), add the records Vercel shows on the Domains page. They are usually:
   - for `sarasinpicquart.com`: an **A** record with the IP address Vercel gives (often `76.76.21.21`);
   - for `www`: a **CNAME** record pointing to the name Vercel gives (often `cname.vercel-dns.com`).

   Delete any old A, AAAA or CNAME records for the same names that point at a previous website.

   **Do not touch the email records:** MX (pointing to `…mail.protection.outlook.com`), the `autodiscover` CNAME, TXT records with `v=spf1` or `MS=`, DKIM (`selector1._domainkey`, `selector2._domainkey`) and DMARC (`_dmarc`). Those deliver the company's Microsoft 365 email, and changing them stops email from working.
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
