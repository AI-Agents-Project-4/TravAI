@AGENTS.md

# Frontend (Next.js) — owner: Fernando

Project-wide rules and the product rules are in [../CLAUDE.md](../CLAUDE.md). The API shapes are in [../docs/api-contract.md](../docs/api-contract.md).

## Stack

- Next.js 16 (App Router, Turbopack; `cacheComponents` is on in `next.config.ts`), React 19, TypeScript (strict)
- Tailwind CSS v4 (CSS-first config in `src/app/globals.css`; there is no `tailwind.config.js`)
- Vitest + React Testing Library (jsdom)
- pnpm

Next 16 differs from older versions. Read the relevant guide in `node_modules/next/dist/docs/` before using an API you're unsure of (see AGENTS.md above).

## Layout

```
src/
  app/            routes (App Router). page.tsx, layout.tsx, *.test.tsx next to what they test
  components/     shared UI components (create as needed)
  lib/
    config.ts     API_BASE_URL. All backend URLs go through this
    api/          typed fetch helpers for each endpoint in docs/api-contract.md (create as needed)
    types.ts      TS types copied from docs/api-contract.md (create as needed)
```

## Conventions

- Components are Server Components by default. Add `"use client"` only where you need state, effects or event handlers (trip form, plan editor, progress screen).
- All backend calls go through `src/lib/api/`. Don't call `fetch` with hard-coded URLs in components.
- Types for API data mirror `docs/api-contract.md`. If the shapes need to change, update the contract in the same PR.
- The plan editor keeps a **running total** client-side. Compute it from the option prices so it stays in sync with the budget display.
- Show `source_url` and how old the price is (`fetched_at`) wherever a price appears, and label estimates as estimates.
- Show money with its currency (`Intl.NumberFormat`). Never round down.
- Keep progress updates (polling vs. SSE is still undecided) behind a single hook, so swapping the transport touches one file.
- Write accessible markup: real `<button>`/`<label>` elements, and test with `getByRole`.
- Only public values go in env vars: `NEXT_PUBLIC_*` is shipped to the browser. Copy `.env.example` → `.env.local`.

## Checks

```bash
pnpm lint && pnpm typecheck && pnpm test && pnpm build
```

`typecheck` runs `next typegen` first, because the route types (`PageProps`, `LayoutProps`) are generated.

Vitest can't render `async` Server Components. Test those with E2E tests, or keep their logic in plain functions you can unit test.
