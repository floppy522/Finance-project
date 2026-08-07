# MoneyFlow GitHub Portfolio Design

**Date:** 2026-08-07
**Status:** Approved design
**Audience:** Product and engineering recruiters, hiring managers, and interviewers
**Primary positioning:** Product Manager with strong technical depth

## Objective

Turn the public MoneyFlow repository into a credible portfolio case without changing or redeploying the running server. A recruiter should understand the product in under 30 seconds; a technical reviewer should be able to inspect architecture, quality controls, and implementation decisions in depth.

The presentation must distinguish implemented behavior from future roadmap items. It must not expose production access details or personal financial data.

## Positioning and authorship

MoneyFlow is presented as a privacy-first personal finance product designed and shipped from problem definition through production delivery by **Valeriy Malov**.

The repository will explicitly describe the role as:

- product ownership, requirements, scope, and prioritization;
- technical product decisions and delivery ownership;
- implementation completed with AI coding agents;
- verification through automated tests, CI, and release safeguards.

It will not claim unsupported user research, adoption, financial impact, or sole unaided authorship of all source code.

## Portfolio deliverables

### Root README

Create `README.md` in English with this information hierarchy:

1. Hero: product name, concise value proposition, CI/stack/license badges.
2. Problem: why personal expense capture fails at the moment of spending.
3. Current solution: Telegram for capture and the browser for review.
4. Product preview: synthetic Telegram and web visuals.
5. Implemented capabilities: only behavior present in the repository.
6. Product decisions and trade-offs.
7. Architecture and data flow.
8. Technology and engineering quality.
9. Local Docker Compose setup.
10. Current limitations and roadmap.
11. Author role and AI-assisted delivery disclosure.
12. MIT license reference.

The hero message is:

> Capture personal finances in Telegram. Understand them in the browser.

The README must make clear that the application is deployed privately but has no public demo because it processes personal financial data.

### Product case

Create `docs/product-case.md` in English. It will cover:

- personal problem and JTBD;
- product constraints: one owner, manual-first capture, privacy, Russian ruble base currency;
- MVP scope and prioritization;
- Telegram/web responsibility split;
- batch input for offline catch-up;
- category resolution and correction learning loop;
- technical and operational delivery decisions;
- evidence from automated verification;
- current limitations and roadmap.

The case must describe this as a personal product case, not a validated multi-user commercial business.

### Visual assets

Create repository-native, responsive SVG assets:

- `docs/assets/telegram-batch-input.svg`;
- `docs/assets/web-category-review.svg`;
- `docs/assets/architecture.svg`.

The Telegram visual will show a valid implemented batch-input example with date headers, expenses, income, and categorized confirmation. The web visual will reproduce the implemented transaction table, filters, category controls, and review badge. The architecture visual will show Telegram, FastAPI, batch parsing/resolution/ingestion, OpenAI fallback, PostgreSQL, React, and encrypted backup boundaries.

All visual data must be synthetic. Assets must not contain a production domain, IP address, Telegram identifier, access token, secret, real account balance, or real transaction history.

### License

Add a standard MIT `LICENSE` for copyright year 2026 and author `Valeriy Malov`.

## Current release versus roadmap

The implemented section may claim:

- manual Telegram capture;
- multi-line batch input with date handling;
- expense and income parsing;
- automatic category resolution with local rules, learned corrections, and guarded AI fallback;
- idempotent and atomic persistence;
- secure one-time web login;
- transaction review, category filtering, and manual category correction;
- single-owner enforcement;
- PostgreSQL migrations;
- Docker Compose deployment with HTTPS proxying;
- encrypted backup and restore verification workflow;
- API unit/integration tests, web tests, Playwright E2E, and release checks in CI.

The roadmap section must label these items as not yet implemented:

- spending analytics and pie charts;
- monthly and per-category budgets;
- manually valued net worth tracking;
- voice input.

## Product decisions to highlight

- **Manual-first over bank integration:** lower integration risk and full user control.
- **Telegram capture plus web review:** optimize each interface for one job.
- **Batch input:** support catch-up from offline notes and reduce entry friction.
- **Rules and learned corrections before AI:** reduce cost, latency, and nondeterminism.
- **AI as guarded fallback:** strict timeout, validation, and deterministic fallback behavior.
- **Single-owner by design:** reduce authorization surface for a personal application.
- **No public demo:** protect financial privacy while keeping the source reviewable.

## Visual direction

Use a product-case-study style:

- dark green/navy hero and architecture accents;
- neutral light surfaces for product screenshots;
- existing MoneyFlow web colors for the web asset;
- clear hierarchy and restrained badges;
- no decorative charts for unimplemented analytics.

## GitHub repository metadata

Repository description:

> Privacy-first personal finance tracker: batch Telegram capture, AI-assisted categories, and a React review dashboard.

Recommended topics:

- `personal-finance`
- `telegram-bot`
- `fastapi`
- `react`
- `postgresql`
- `openai`
- `docker`
- `product-management`

The repository About section must not include the production URL.

## Local setup content

The README setup must use existing repository interfaces and avoid inventing commands. It will explain:

1. prerequisites: Docker and Docker Compose;
2. copying `.env.example` to `.env`;
3. replacing example-only Telegram/OpenAI values when those integrations are needed;
4. starting the local stack through the existing Compose configuration;
5. checking the health endpoint;
6. keeping `.env` out of version control.

Production deployment instructions remain in `ops/deploy.md`; the portfolio work will not modify deployment or server state.

## Safety and accuracy rules

- Do not include secrets, credentials, private keys, database dumps, production URLs, or personal identifiers.
- Do not present roadmap items as implemented.
- Do not invent users, interviews, conversion metrics, business impact, or adoption.
- Do not expose a clickable live demo.
- Do not change application behavior, infrastructure, Compose, migrations, or CI workflow.
- Preserve existing source and operational documentation.

## Verification

Before delivery:

1. verify all Markdown links and repository paths;
2. parse all SVG files as valid XML and inspect their rendered output;
3. verify README claims against source and tests;
4. run the existing secret/artifact scan or its focused sentinel;
5. run `git diff --check`;
6. confirm only portfolio documentation, assets, and license files changed;
7. confirm no server or GitHub repository metadata was mutated automatically.

Existing application test suites do not need to be rerun when no application, test, CI, or deployment files change. The existing green PR CI remains the application baseline.

## Acceptance criteria

- A recruiter can identify the problem, solution, role, and current product scope from the first two README screens.
- A technical reviewer can find architecture, stack, quality evidence, setup, and operational safeguards without reading source first.
- All visuals contain synthetic data and correspond to implemented behavior.
- Current features and roadmap are visually and textually distinct.
- AI-assisted implementation is disclosed clearly and professionally.
- No production or personal data appears in the new files.
- README, product case, visuals, and license render correctly on GitHub.
