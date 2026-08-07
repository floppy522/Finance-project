# MoneyFlow: from personal friction to a production product

## Executive summary

MoneyFlow is a privacy-first personal finance tracker for a single owner. It turns a familiar messaging surface into a fast capture point and reserves the browser for reviewing and correcting a financial history. The MVP concentrates on the most failure-prone moment in personal finance: recording a transaction when it happens, or recovering a set of notes later without turning that recovery into a data-entry project.

The product is intentionally narrow. It supports manual Telegram capture, multi-line batches, expense and income categorization, and a browser-based review workflow. It is privately deployed because the data is financial and personal; the repository is the review surface rather than a public live demo.

## The problem

Personal finance records become unreliable when capture is slow or inconvenient. A form-heavy mobile flow asks for several fields at the moment a purchase happens, while notes written during the day can become a second backlog that still needs to be entered. In both cases, the cost of keeping the history current is high enough to make the history incomplete.

The product problem was therefore not to provide every finance feature at once. It was to make a trustworthy transaction history practical to maintain: capture quickly in a tool already used throughout the day, accept several entries when catching up, and provide a calmer place to review uncertain classifications.

## Job to be done

> When I spend money or catch up from offline notes, I want to record one or many transactions with minimal effort, so that I can maintain a trustworthy financial history and review it later.

This job defines the interface split and the MVP boundary. Telegram handles quick, text-first capture. The browser handles a transaction list, category filtering, a review filter, and manual category correction. The system keeps the captured transaction even when a category needs review, rather than making the user resolve every ambiguity before saving.

## Constraints

- **Single user.** MoneyFlow is for one owner, not a shared household or a multi-tenant product. A singleton owner setting and owner-scoped data access keep the authorization surface deliberately small.
- **Manual input.** The product begins with typed transaction descriptions, amounts, and dates. Manual input includes multi-line catch-up batches from offline notes; it does not mean bank synchronization.
- **RUB base currency.** The owner setting uses RUB as the base currency and the current capture and review experiences format amounts in rubles and kopecks. Multi-currency accounting is outside the MVP.
- **Private financial data.** Transaction history is personal data. The application is privately deployed, has no public demo, and is designed so that source review does not require exposing a real account or transaction history.

## MVP scope and prioritization

The MVP ships the smallest end-to-end loop that answers the job: a secret-authenticated, owner-gated Telegram webhook accepts an expense or income line, supports date headings and multiple lines, stores valid rows, and replies with a readable result. The React dashboard then lists recent transactions, filters by category or review state, and lets the owner correct a category.

The prioritization is intentional. Capture, reliable persistence, and correction learning come before reporting features because reporting cannot repair a missing or untrusted history. The implemented category path is learned corrections, local rules, and then an optional AI provider; an unresolved or invalid result becomes a deterministic fallback category marked for review.

## Product experience

Telegram is the capture surface: it accepts ordinary text, recognizes batches, and returns a saved, already-saved, or rejected-line summary. Date headings make it practical to enter a short backlog from notes without repeating a date on every line.

![Synthetic Telegram batch-input example](assets/telegram-batch-input.svg)

The browser is the review surface, not a second chat workflow. The transaction table exposes category and review filters and offers a category control on each transaction, so the owner can correct an uncertain item with more context and less conversational back-and-forth.

![Synthetic web category-review example](assets/web-category-review.svg)

Both visuals use synthetic demo data and depict implemented product behavior.

## Key product decisions

- **Telegram capture over a form-heavy mobile flow.** A text message minimizes interruption and uses an interface already present at the point of spending. The trade-off is a constrained grammar and less immediate structure than a dedicated form.
- **Browser review over editing inside Telegram.** A table, filters, and category controls make comparison and correction easier than a long message thread. The trade-off is a handoff from capture to review.
- **Batch input for offline catch-up.** Multi-line parsing, date handling, and per-line results reduce the cost of converting notes into history. The trade-off is parser complexity and the need to explain rejected lines clearly.
- **Rules and learned corrections before AI.** Deterministic local rules and the owner's past corrections cover repeatable cases first, reducing latency, cost, and non-determinism. The trade-off is that the initial rule set has limited coverage.
- **AI as a guarded fallback.** The optional provider receives only unresolved category inputs and is bounded by a strict five-second timeout, a strict schema, allowed category codes, confidence thresholds, and deterministic fallback behavior. The trade-off is that some entries remain marked for review instead of being force-classified.
- **Single-owner enforcement over multi-user account complexity.** Telegram preflight checks, a singleton owner model, and owner-scoped repositories fit a personal product and reduce authorization risk. The trade-off is no collaboration, household sharing, or account management.
- **Private deployment over a public demo.** A public instance would conflict with the privacy model for personal financial data. The trade-off is that reviewers inspect source, tests, synthetic visuals, and operational documentation rather than a live account.

## Delivery and architecture

The delivery path is deliberately vertical: Telegram sends a private webhook update to FastAPI; the batch parser produces transaction candidates; category resolution applies learned corrections and local rules before an optional guarded provider; atomic ingestion persists the result in PostgreSQL; the React dashboard reads and corrects the history through authenticated REST endpoints.

![MoneyFlow architecture and safeguards](assets/architecture.svg)

The persistence layer exposes owner-scoped reads and corrections. Batch transaction events are idempotent through a unique source-event identity and conflict-safe insert behavior, so replaying a Telegram update does not duplicate its transactions. A batch is committed only after its rows have been processed and is rolled back on persistence failure.

The web login begins with a Telegram-issued token, exchanges it once for a session, and stores token hashes rather than raw credentials. Database migrations describe the schema evolution for the owner setting, transactions, categories, corrections, login tokens, and web sessions.

## Quality and operational readiness

The repository contains evidence for each delivery safeguard rather than treating them as future intentions:

- API unit and integration tests cover parsing, owner checks, category resolution, atomic batch ingestion, authentication, migrations, and repositories.
- GitHub Actions separates API, web, end-to-end, and release-static jobs. The end-to-end job runs a Playwright vertical slice through batch ingestion, browser review, manual correction, learned correction reuse, and one-time login behavior.
- Alembic migrations and a bootstrap path make database setup explicit for test and deployment environments.
- The production backup script writes encrypted `age` backup artifacts. The restore check decrypts the newest backup into a separately named, network-isolated PostgreSQL container and validates the expected schema revision before cleanup.

These controls support safe iteration on a private personal product; they do not imply a public SaaS operating model or external adoption.

## Current outcome

The repository demonstrates an end-to-end, privately deployed personal finance workflow and a green CI vertical slice. It provides a reviewable implementation of Telegram capture, batch handling, guarded categorization, authenticated browser review, and operational recovery checks without claiming adoption, revenue, or business impact.

## Limitations and roadmap

The following items are **not implemented**:

- Spending analytics and pie charts
- Monthly and per-category budgets
- Manually valued net worth tracking
- Voice input

The current product also remains intentionally single-owner, manual-first, RUB-only, and privately deployed. These boundaries keep the MVP focused while leaving clear directions for a later product phase.

## My role and AI-assisted delivery

I owned the product problem, requirements, prioritization, technical product decisions, acceptance criteria, and release process. Implementation was completed with AI coding agents through specification-driven, test-driven, and review-gated workflows. I remained accountable for scope, trade-offs, verification, and production readiness.
