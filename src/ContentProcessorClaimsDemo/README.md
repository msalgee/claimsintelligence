# Content Processor — Claims Intelligence Demo

A polished, executive-facing 7-step walkthrough of the auto-insurance claims journey, powered by Microsoft Foundry.

The current experience uploads claim documents, reads workflow output, and uses `/claimsdemo` endpoints for the guided claims journey. Foundry-backed sections fail loudly in deployed `APP_ENV=prod` environments if the Foundry project/model configuration is missing; local `APP_ENV=dev|local|test` runs can still use fixture payloads, and the UI labels those sections as local fixture data.

## Local development

```powershell
cp .env.example .env
npm install
npm run dev
```

Run the API with `APP_ENV=dev` if you want the entity, recommendation, and email sections to use local fixture payloads when Foundry is not configured.

App runs at <http://localhost:5173>.

If `VITE_API_BASE_URL` is omitted, the Vite dev proxy targets `http://localhost:8000`. Set it explicitly when pointing the demo at a deployed API.

### Required Entra app registration tweak

Create (or reuse) your own SPA app registration as described in [`../../docs/ConfigureAppAuthentication.md`](../../docs/ConfigureAppAuthentication.md), put its client ID in `VITE_AAD_CLIENT_ID`, and add `http://localhost:5173` as an SPA redirect URI on that app registration before signing in locally.

The landing page and top bar both initiate MSAL redirect sign-in when no account is active. If a user clicks **Start sample claim** while signed out, the app remembers that intent in session storage and starts the walkthrough after the redirect completes.

## Runtime configuration

The container image is built once with placeholder `VITE_*` values. At startup, `env.sh` replaces these placeholders with the Container App's `APP_*` environment variables and fails fast if required values are missing or left unreplaced:

- `APP_TENANT_ID`
- `APP_WEB_CLIENT_ID`
- `APP_API_SCOPE`
- `APP_API_BASE_URL`
- `APP_REDIRECT_URI`

`APP_REDIRECT_URI` may be a relative path such as `/`; the frontend resolves it against the current origin before configuring MSAL.

## Current fixture boundary

These parts can still be fixture-backed in local API runs where Foundry is not configured:

- extracted fields drilldown
- entity timeline and map
- recommendation content
- email draft content

The supporting persona PDFs live in `../ContentProcessorAPI/samples/claim_demo_persona/` so the fixture story has source documents ready for the later real-upload milestone.

## Stack

- Vite 6 + React 19 + TypeScript
- Fluent UI v9 (custom navy/teal dark theme)
- MSAL.js + react-router v7
- Zustand state, Framer Motion animations
