# Task 6 report: authenticated web list

## Result

Implemented the React 19/Vite web client in `apps/web`, including cookie-authenticated API calls, the `/login?token=` callback, and the responsive semantic transaction table.

## RED evidence

After creating `TransactionList.test.tsx` but before implementation, ran:

```sh
./node_modules/.bin/vitest run
```

Result: failed as expected because `./TransactionList` could not be resolved from `TransactionList.test.tsx` (the production component did not exist).

## GREEN evidence

After implementation, ran:

```sh
./node_modules/.bin/vitest run
./node_modules/.bin/tsc --noEmit
./node_modules/.bin/vite build
```

Results:

- Vitest: 1 test file passed, 2 tests passed.
- TypeScript strict check: passed.
- Vite production build: passed; created `dist`.

## Commands and verification notes

`pnpm install` successfully generated and committed `apps/web/pnpm-lock.yaml`. Running `pnpm test --run` was blocked by the environment's package-manager supply-chain gate because it rejected esbuild's postinstall script (`ERR_PNPM_IGNORED_BUILDS`). The equivalent project-local Vitest, TypeScript, and Vite commands above all passed.

`git diff --cached --check` passed before commit.

## Commits

- `1ffabb2 feat: add authenticated transaction list`
- `ff02583 chore: omit TypeScript build metadata`
- `cc807aa chore: ignore TypeScript build metadata`

## Concerns

No functional concerns.

## Fix (review follow-up)

Fixed the workspace build-script policy by setting `allowBuilds.esbuild: true` in
`apps/web/pnpm-workspace.yaml`, so pnpm can execute esbuild's required postinstall.

Added regression coverage and fixed the browser behavior:

- `LoginCallback` keeps a module-scoped in-flight token-exchange promise. A
  StrictMode effect replay attaches to that same promise after the first effect
  removes the token from browser history, rather than issuing a second POST or
  showing a false invalid-link error. Its active-effect guard still allows the
  replayed effect to redirect on success or show the error on failure.
- `TransactionList` now disables retry specifically for `UNAUTHORIZED`, while
  retaining up to three retries for other errors. The production-default
  QueryClient test asserts that a 401 makes exactly one request.

### RED evidence

After adding the regressions and before the implementation changes, ran:

```sh
CI=true HOME=/tmp XDG_CACHE_HOME=/tmp/.cache pnpm test --run src/auth/LoginCallback.test.tsx src/transactions/TransactionList.test.tsx
```

Result: both tests failed as intended. The StrictMode callback test rendered
the invalid-link alert because the replay saw the already-stripped URL token;
the 401 test remained loading while React Query retried, rather than reaching
the login guidance after one fetch.

### Verification evidence

```sh
CI=true HOME=/tmp XDG_CACHE_HOME=/tmp/.cache pnpm install --frozen-lockfile
CI=true HOME=/tmp XDG_CACHE_HOME=/tmp/.cache pnpm test --run
CI=true HOME=/tmp XDG_CACHE_HOME=/tmp/.cache pnpm build
CI=true HOME=/tmp XDG_CACHE_HOME=/tmp/.cache pnpm lint
```

Results: frozen install passed and ran esbuild postinstall; Vitest passed (2
files, 3 tests); production build passed; and `tsc --noEmit` passed. `HOME` and
`XDG_CACHE_HOME` point pnpm at writable CI cache locations in this environment;
they do not alter project configuration.
