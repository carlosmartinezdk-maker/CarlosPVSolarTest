// All approved copy and data from the design handoff (SP Site.dc.html logic class).

export type ServiceA = { kind: 'A'; t: string; ren: string; any: string };
export type ServiceB = { kind: 'B'; t: string; kicker: string; intro: string; points: string[]; best: string };
export type Service = ServiceA | ServiceB;

// [title, in renewables, in any industry]
const SA: [string, string, string][] = [
  ['Revenue and cash management', 'PPAs, merchant sales and guarantees of origin, invoiced automatically.', 'Customer contracts, subscriptions and billing.'],
  ['Operating budget tracking', 'O&M budgets across a portfolio of sites, with variance reporting.', 'Entity and departmental budgets against actuals.'],
  ['Compliance and regulatory reporting', 'Statutory filings, tax and lender covenants.', 'Statutory, tax, lender and investor reporting.'],
  ['Cash flow and treasury', 'Distributions, debt service and maintenance reserves.', '13-week cash, facilities and covenant headroom.'],
  ['Contractual audit and QC', 'O&M billing, warranties and land agreements.', 'Supplier billing, purchase orders and leases.'],
];

const SB: Omit<ServiceB, 'kind'>[] = [
  {
    t: 'Flex-up Finance',
    kicker: 'You keep your systems',
    intro: 'Keep your existing ledger and tech stack. We run end-to-end back-office finance and accounting, including the month-end close.',
    points: [
      'End-to-end finance and accounting, including the month-end close',
      'Skilled people on tap, alongside your in-house team',
      'Surge capacity where you need it in receivables, payables, FP&A and strategy',
      'AI-enabled efficiency, without ripping out your tech',
    ],
    best: 'an existing finance team with a broken process.',
  },
  {
    t: 'Advisory Services',
    kicker: 'On-demand expertise',
    intro: 'Experienced financial leadership for the moments that matter for PE-backed companies.',
    points: [
      'FP&A and board-pack reporting',
      'Technical accounting and clean-up',
      'Fractional and interim CFO',
      'M&A integration and carve-out support',
      'CFO recruitment and placement',
    ],
    best: 'ad-hoc, event-driven needs.',
  },
];

export const SERVICES: Service[] = [
  ...SA.map(([t, ren, any]): ServiceA => ({ kind: 'A', t, ren, any })),
  ...SB.map((s): ServiceB => ({ kind: 'B', ...s })),
];

export const PLATFORM = [
  {
    t: 'Platform',
    s: 'Data and reporting layer',
    p: ['Unified chart of accounts across portfolio companies', 'Pre-built integrations with the ledgers you already run', 'Standardised KPI library', 'Board packs that build themselves'],
  },
  {
    t: 'AI workflows',
    s: 'Orchestrated, with a human in the loop',
    p: ['OCR, classifiers and language models wrapped in our platform', 'Month-end close, payables, bank reconciliation and anomaly detection', 'A reviewer signs off every material line', 'One page across every tool'],
  },
  {
    t: 'Pod delivery',
    s: 'The senior human layer',
    p: ['A dedicated controller per client', 'A cross-portfolio lead per sponsor', 'Audit liaison and technical accounting', 'Tax and compliance by country'],
  },
];

export const AUDIENCES = [
  { label: 'Funds and management companies', line: 'One playbook across the portfolio, proven at one company first.', photo: 'Photo: partners at work, natural light · black and white' },
  { label: 'PE- and VC-backed companies', line: 'Board-ready numbers without building a finance team.', photo: 'Photo: quiet working interior · black and white' },
  { label: 'Renewable energy and infrastructure', line: 'Where we started: every SPV closed to the calendar, in every jurisdiction.', photo: 'Photo: wind farm or solar array at dusk · black and white' },
  { label: 'Real estate and other real assets', line: 'The same calendar, controls and lender reporting, for any asset with a balance sheet.', photo: 'Photo: European stone architecture · black and white' },
];

// Step: [title, text, lane (0 client / 1 SP), isReview]
export type FlowStep = [string, string, 0 | 1, boolean?];
export const FLOWS: { label: string; freq: string; note: string; steps: FlowStep[] }[] = [
  {
    label: 'Taking on an entity',
    freq: 'One-off',
    note: 'Mapped before first use, so the monthly feed never breaks.',
    steps: [
      ['Collect', 'You send your ledger exports, trial balances and budget, once.', 0],
      ['Rebuild', 'We rebuild your chart of accounts from what was actually posted.', 1],
      ['Map', "Every account is mapped to your group reporting before it's used.", 1],
      ['Load', 'Opening balances first, then each month of history, reconciled to the trial balance.', 1],
      ['Review', 'A reviewer signs off. You receive an onboarding review and a short list of coding fixes.', 1, true],
    ],
  },
  {
    label: 'Closing a month',
    freq: 'Monthly',
    note: 'Every step reviewed. Every exception named.',
    steps: [
      ['Close', 'Your period closes in your ledger.', 0],
      ['Load', 'We load the month. The file must net to zero and tie to your trial balance.', 1, true],
      ['Check', 'We check the coding against the agreed accounts.', 1, true],
      ['Reclassify', 'If anything drifted, you reclassify and we reload.', 0],
      ['Live', 'The month is live in group reporting by business day 10.', 1],
    ],
  },
  {
    label: 'Building the budget',
    freq: 'Annual',
    note: 'Budget, actuals and forecast on one structure, so every variance means something.',
    steps: [
      ['Template', 'We build the template on the same account codes as your actuals.', 1],
      ['Prepare', 'You prepare entity budgets: code, narrative, monthly P&L and cash.', 0],
      ['Validate', 'We validate every line.', 1, true],
      ['Approve and load', 'You approve; we load it and agree the totals.', 0, true],
    ],
  },
];

// [code, column, row, status (1 today / 2 core / 0 partners)]
export const TILES: [string, number, number, 0 | 1 | 2][] = [
  ['IS', 1, 1, 0], ['NO', 5, 1, 0], ['SE', 6, 1, 0], ['FI', 7, 1, 0],
  ['IE', 2, 2, 1], ['GB', 3, 2, 1], ['DK', 5, 2, 0], ['EE', 7, 2, 0],
  ['NL', 4, 3, 2], ['DE', 5, 3, 2], ['PL', 6, 3, 0], ['LV', 7, 3, 0],
  ['FR', 3, 4, 2], ['BE', 4, 4, 2], ['CZ', 5, 4, 0], ['SK', 6, 4, 0],
  ['LT', 8, 3, 0], ['PT', 1, 5, 1], ['ES', 2, 5, 1], ['CH', 4, 5, 0],
  ['AT', 5, 5, 0], ['HU', 6, 5, 0], ['RO', 7, 5, 0], ['LU', 3, 5, 0],
  ['IT', 4, 6, 1], ['SI', 5, 6, 0], ['HR', 6, 6, 0], ['RS', 7, 6, 0],
  ['BG', 8, 6, 0], ['MT', 4, 7, 0], ['AL', 7, 7, 0], ['GR', 8, 7, 1],
];

export const EMAIL = 'info@sarasinpicquart.com';
// LinkedIn URL is still to be confirmed.
export const LINKEDIN = '#';
