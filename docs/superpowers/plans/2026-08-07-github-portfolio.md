# MoneyFlow GitHub Portfolio Implementation Plan

> **For agentic workers:** Implement tasks in order and verify each commit before continuing.

**Goal:** Present MoneyFlow as an English, recruiter-first Product Manager portfolio case without changing application behavior, deployment state, or GitHub settings.

**Architecture:** The portfolio layer contains only repository documentation, three repository-native SVG assets, and an MIT license. `README.md` is the fast-scanning entry point, `docs/product-case.md` is the deeper narrative, and the SVGs are synthetic previews of implemented behavior.

**Tested base:** `718a5f404d1837a4a1b8c58a78378b174ecd565b` (`origin/main`)

**Tech stack:** GitHub-flavored Markdown, SVG/XML, ImageMagick or Librsvg rendering, Git format-patch, PowerShell handoff.

## Global constraints

- Write portfolio-facing copy in English.
- Identify Valeriy Malov as Product Manager with accountability for problem framing, requirements, prioritization, technical product decisions, acceptance criteria, release, and verification.
- Preserve this exact disclosure in the product case and README: “I owned the product problem, requirements, prioritization, technical product decisions, acceptance criteria, and release process. Implementation was completed with AI coding agents through specification-driven, test-driven, and review-gated workflows. I remained accountable for scope, trade-offs, verification, and production readiness.”
- Present only implemented release behavior as current; label analytics, budgets, net worth tracking, and voice input as roadmap.
- Use synthetic financial data only and do not link a live demo.
- Do not claim users, interviews, adoption, conversion, revenue, or fabricated impact.
- Do not include a production hostname, IP address, Telegram identifier, token, secret, private key, dump, balance, or transaction history.
- Use reserved examples such as `portfolio.example.com` and `192.0.2.10` only when a placeholder is necessary.
- Do not modify application source, tests, CI, Compose, migrations, deployment files, server state, or GitHub repository settings.

## File map

- `README.md`: recruiter-first landing page, role, product scope, evidence, setup, disclosure, and roadmap.
- `docs/product-case.md`: product reasoning, delivery narrative, scope boundaries, and trade-offs.
- `docs/assets/telegram-batch-input.svg`: synthetic Telegram batch capture.
- `docs/assets/web-category-review.svg`: synthetic browser category review.
- `docs/assets/architecture.svg`: system boundaries, REST path, atomic batch semantics, and backup flow.
- `LICENSE`: MIT license for Valeriy Malov, 2026.
- `docs/superpowers/specs/2026-08-07-github-portfolio-design.md`: approved design.
- `docs/superpowers/plans/2026-08-07-github-portfolio.md`: this implementation and handoff plan.

## Task 1: Design and plan

1. Add the approved design with no trailing whitespace.
2. Add this implementation plan with generic, configurable secret and production-identifier checks.
3. Confirm the plan contains no real deployment identifier, even inside example scan commands.
4. Commit the two files as `docs: plan MoneyFlow GitHub portfolio`.

## Task 2: Synthetic visual assets

1. Add the Telegram, web-review, and architecture SVGs with accessible `<title>` and `<desc>` elements.
2. Keep `15 июля` inside the sent Telegram message bubble as a batch date heading.
3. Use readable small-text colors against their backgrounds.
4. Draw an explicit FastAPI-to-REST-boundary connection in the architecture.
5. Describe atomic ingestion as `all accepted rows or none`.
6. Parse all SVGs as XML, render all three to PNG, and inspect each at original detail.
7. Commit the assets as `docs: add MoneyFlow portfolio visuals`.

## Task 3: Product case and license

1. Add `docs/product-case.md` and the standard MIT `LICENSE`.
2. Describe the webhook as secret-authenticated and owner-gated, not merely private.
3. Keep the current release and roadmap boundaries explicit.
4. Preserve the exact AI-assisted disclosure from the global constraints.
5. Commit as `docs: add MoneyFlow product case`.

## Task 4: Recruiter-first README

1. Put the Product Manager role and accountability immediately after the hero and private-deployment note.
2. Keep all product previews explicitly synthetic.
3. Link claims to source, tests, CI, and operations evidence.
4. In local setup, tell the reader to replace copied Telegram placeholder values before exercising Telegram.
5. Show `curl http://localhost:8000/health` in its own terminal after the API starts.
6. Preserve the exact AI-assisted disclosure and separate current release from roadmap.
7. Commit as `docs: present MoneyFlow as a product case`.

## Task 5: Complete validation

Run all checks from the repository root. `$Base` must remain the tested main commit.

```powershell
$ErrorActionPreference = "Stop"
$Base = "718a5f404d1837a4a1b8c58a78378b174ecd565b"

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs)
    & git @GitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "git $($GitArgs -join ' ') failed with exit code $LASTEXITCODE"
    }
}

Invoke-Git diff --check "$Base..HEAD"
$Changed = @(Invoke-Git diff --name-only "$Base..HEAD")
$Expected = @(
    "LICENSE"
    "README.md"
    "docs/assets/architecture.svg"
    "docs/assets/telegram-batch-input.svg"
    "docs/assets/web-category-review.svg"
    "docs/product-case.md"
    "docs/superpowers/plans/2026-08-07-github-portfolio.md"
    "docs/superpowers/specs/2026-08-07-github-portfolio-design.md"
)
if (@(Compare-Object $Expected $Changed).Count -ne 0) {
    throw "The docs-only path set differs from the expected eight paths."
}
```

Validate Markdown links, source claims, headings, XML parsing, and image renders. Then scan every added file and every generated patch with a configurable scanner. The scanner must reject likely secrets, non-reserved IPv4 addresses, unknown hostnames, and deployment-like assignments while allowing only documented public dependencies and IANA-reserved examples.

```text
Allowed public hosts:
github.com
img.shields.io
docs.astral.sh
www.w3.org

Allowed example host suffix:
.example.com

Allowed example IPv4 ranges:
192.0.2.0/24
198.51.100.0/24
203.0.113.0/24
```

The scan input set is the eight added files plus every `*.patch` file in the handoff directory. It must search full file content, not only selected deliverables or current-worktree grep output.

After generating the patch series, apply it in a disposable worktree at `$Base` and require:

- every `git am` succeeds;
- the applied tree hash equals the final branch tree hash;
- `git diff --check $Base..HEAD` exits zero;
- the changed path set is exactly the eight paths above;
- the scanner passes the applied files and the patch text;
- the ZIP contains only patches, `APPLY-POWERSHELL.md`, `SHA256SUMS`, and `SERIES`;
- the ZIP checksum and every internal checksum verify.

## Task 6: Beginner-safe PowerShell handoff

Use the following fail-fast pattern in `APPLY-POWERSHELL.md`. Run it from a clone of the repository after extracting the patch ZIP.

```powershell
$ErrorActionPreference = "Stop"
$TestedMain = "718a5f404d1837a4a1b8c58a78378b174ecd565b"
$Branch = "docs/github-portfolio"

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs)
    & git @GitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "git $($GitArgs -join ' ') failed with exit code $LASTEXITCODE"
    }
}

Invoke-Git fetch origin main
$RemoteMain = (Invoke-Git rev-parse origin/main | Select-Object -Last 1).Trim()
if ($RemoteMain -ne $TestedMain) {
    throw "origin/main is $RemoteMain, but these patches were tested on $TestedMain. Stop and request a refreshed series."
}

Invoke-Git switch main
Invoke-Git reset --keep origin/main
Invoke-Git switch -c $Branch

$Patches = @(Get-ChildItem -File -Filter "*.patch" | Sort-Object Name)
if ($Patches.Count -eq 0) {
    throw "No patch files were found in the current directory."
}

try {
    Invoke-Git am --3way @($Patches.FullName)
} catch {
    & git am --abort
    if ($LASTEXITCODE -ne 0) {
        throw "Patch application failed, and git am --abort also failed. Inspect the repository before continuing."
    }
    throw "Patch application failed and was aborted. No push was attempted."
}

Invoke-Git diff --check $TestedMain..HEAD
Invoke-Git status --short
Invoke-Git push --set-upstream origin $Branch

& gh pr create --base main --head $Branch --title "docs: present MoneyFlow as a product case" --body "Adds the reviewed MoneyFlow portfolio documentation and synthetic visuals."
if ($LASTEXITCODE -ne 0) {
    throw "gh pr create failed with exit code $LASTEXITCODE. The branch was pushed, but no pull request was confirmed."
}
```

Do not run these push or GitHub commands during portfolio preparation. They are a manual handoff only.

## Acceptance criteria

- The first two README screens identify the product, private-demo boundary, Valeriy Malov’s Product Manager role, and accountability.
- The repository contains exactly eight added portfolio paths and no app/runtime change.
- Visuals are synthetic, accurate, valid XML, rendered, and visually inspected.
- The product case and README preserve the exact AI-assisted disclosure.
- No commit, diff, patch, report, or artifact contains a real production hostname, IP, token, or secret.
- A fresh application of the generated patches on the exact tested base produces the identical final tree.
- The handoff archive and all internal artifacts pass checksum verification.
