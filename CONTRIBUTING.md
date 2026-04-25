# Contributing

This guide is for **frontend contributors**. You don't need the backend, Postgres, Docker, or Prefect running locally — see [Mock data](#mock-data) below.

## Workflow

1. Branch from `main`:
   ```bash
   git checkout main && git pull
   git checkout -b your-name/short-description
   ```
2. Make changes and push:
   ```bash
   git push -u origin your-name/short-description
   ```
3. Open a PR against `main`. Direct pushes to `main` are blocked by branch protection.
4. The repo owner reviews and merges. Resolve all conversation threads before merge — required by branch protection.

## Setup

```bash
cd web
cp .env.example .env.local
# Open .env.local and set NEXT_PUBLIC_USE_MOCK=1
npm install
npm run dev
```

Open http://localhost:3000.

## Mock data

`web/lib/mocks.ts` contains six rivers covering all five condition states (Excellent / Good / Fair / Poor / Blown Out) plus edge cases:

- a river with `condition: null` (no prediction yet)
- a river with `current: null` (no recent gauge reading)
- a river with an empty forecast array

Edit this file freely to test additional states — extreme flow values, missing weather data, error fallbacks, etc. Forecast dates are generated relative to today, so they stay current.

To talk to a real backend instead, set `NEXT_PUBLIC_USE_MOCK=0` and `NEXT_PUBLIC_API_URL=<url>` in `.env.local`.

## Before you push

```bash
cd web
npm run lint
npx tsc --noEmit
```

Both must pass.

## Commit messages

Use Conventional Commits — `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`. See `git log --oneline` for examples.
