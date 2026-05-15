# Cost Profiles — Demo vs Production

This solution ships configured for a **demo / evaluation profile** that
minimises Azure spend. The profile is controlled by parameters in
`infra/main.parameters.json` and `infra/main.bicep`. Flip the values listed
below to move from demo into a production-grade footprint.

> **No cost figures are quoted in this document.** Azure pricing changes
> frequently, varies by region, and depends entirely on your usage profile,
> SKU choices, and any EA / MCA discounts you have in place. Always price
> a deployment with the
> [Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/)
> against your own region and consumption assumptions before committing
> to a budget. You are responsible for all Azure charges incurred by
> deploying this solution.

## What "demo" gives you today

The default `azd up` deploys with:

| Setting | Value | File |
| --- | --- | --- |
| `enablePrivateNetworking` | `false` | `infra/main.parameters.json` |
| `enableMonitoring` | `true` | `infra/main.parameters.json` |
| `deployJumpbox` | `false` | `infra/main.parameters.json` |
| `enableScalability` | `false` (bicep default) | `infra/main.bicep` |
| `enableRedundancy` | `false` (bicep default) | `infra/main.bicep` |
| `enablePurgeProtection` | `false` (bicep default) | `infra/main.bicep` |
| `gptDeploymentCapacity` | `100` (100K TPM) | `infra/main.bicep` |
| App Insights retention | 90 days | `infra/main.bicep` |

Resulting footprint:

- Public endpoints, AAD-only data plane (no shared keys, no public blob).
- ACR **Standard** (not Premium); no private endpoints, no VNet, no DNS zones.
- Container Apps on Consumption profile, `min 1 / max 2` replicas per app.
- Cosmos DB single-region, no zone redundancy.
- AI Search basic, 1 replica / 1 partition, semantic free.
- App Configuration Standard (single region).
- Log Analytics + Application Insights with 90-day retention.
- No Bastion, no jumpbox VM.

This is the lowest-cost shape the solution supports while still being
functionally complete. Azure OpenAI token spend is additive and depends
entirely on usage.

## Promoting a deployment to production

To harden a deployment for production (private networking, redundancy,
multi-replica scale-out, longer log retention), change the values below.
You can either edit the files in-place, or override via `azd env set`
before running `azd provision` / `azd up`.

### 1. `infra/main.parameters.json` (edit the file)

The boolean toggles below are stored as JSON literals in
`infra/main.parameters.json`. Edit the file in-place and re-run
`azd provision` / `azd up` to apply.

| Param | Demo | Production | Effect |
| --- | --- | --- | --- |
| `enablePrivateNetworking` | `false` | `true` | Adds VNet, ~8 private endpoints, private DNS zones. Forces ACR to **Premium** and disables public network access on Cosmos / Storage / Search / AI / AppConfig / Foundry. |
| `enableMonitoring` | `true` | `true` | Already on; leave as-is. |
| `deployJumpbox` | `false` | `true` (only meaningful when `enablePrivateNetworking=true`) | Deploys Azure Bastion (Standard) + a `Standard_D2s_v5` Windows jumpbox so admins can reach private endpoints. |
| `enableScalability` | `false` | `true` | Container Apps `min 2 / max 3` replicas instead of `min 1 / max 2`. Removes cold-start latency at the cost of always-on capacity. |
| `enableRedundancy` | `false` | `true` | Adds App Configuration replica region and turns on zone-redundant SKUs where supported. Requires picking a `replicaLocation`. |
| `enablePurgeProtection` | `false` | `true` | Hardens Key Vault / similar resources against accidental deletion. |
| `gptDeploymentCapacity` (env var `AZURE_ENV_GPT_MODEL_CAPACITY`) | `100` | `200`–`300` | Raises the gpt-5.1 GlobalStandard quota ceiling (in thousands of TPM). GlobalStandard is pay-per-token, so this is a quota cap, not a reservation. Raise only if you expect sustained high RPS. |

### 2. `infra/main.bicep` defaults (require file edit)

| Param | Demo | Production | Effect |
| --- | --- | --- | --- |
| Application Insights `retentionInDays` (line ~589) | `90` | `365` | Longer log retention for forensics / compliance. Cost scales with ingest volume × retained days. |

### 3. Optional production overrides (env-var driven)

| Param | Env var | Default | When to change |
| --- | --- | --- | --- |
| `acrAllowedIpRules` | `ACR_ALLOWED_IPS` | empty | Set to a comma-separated list of build-agent / developer IPs when `ENABLE_PRIVATE_NETWORKING=true` and you still need to push images from outside the VNet. Promotes ACR to Premium with a deny-default firewall. |
| `aiSearchLocation` | `AI_SEARCH_LOCATION` | empty (= primary `location`) | Override when the primary region is out of AI Search capacity. |
| `vmSize` | (n/a) | empty (defaults to `Standard_D2s_v5`) | Pick a smaller jumpbox size (e.g. `Standard_B2s`) if the jumpbox is rarely used. Edit `main.bicep` to change. |

## What the production profile adds

With `enablePrivateNetworking: true`, `deployJumpbox: true`,
`enableScalability: true`, `enableRedundancy: true` you take on the
following additional cost drivers (price each one in the Azure Pricing
Calculator for your region and usage):

- ACR **Premium** instead of Standard.
- ~8 Private Endpoints + associated private DNS zones.
- Azure Bastion **Standard** for admin access into the VNet.
- A jumpbox VM (`Standard_D2s_v5` by default) — deallocate when idle to
  drop to storage-only cost.
- Container Apps `min 2` always-on replicas across all apps in the
  solution, instead of `min 1`.
- Application Insights 365-day retention instead of 90-day (ingest cost
  scales with retention × volume).
- Other resources (Cosmos, Search, Storage, AppConfig, LAW, AOAI base
  pricing) are unchanged from demo.

## Quick switch via `azd env`

The string-typed knobs below (`AZURE_ENV_GPT_MODEL_CAPACITY`,
`ACR_ALLOWED_IPS`, `AI_SEARCH_LOCATION`) are env-var driven and can be
flipped per `azd` environment without editing files. The boolean cost
knobs (`enablePrivateNetworking`, `deployJumpbox`,
`enableScalability`, `enableRedundancy`, `enablePurgeProtection`)
are hardcoded JSON literals in `infra/main.parameters.json` because
azd's parameters-file substitution does not support unquoted boolean
placeholders — edit the file when promoting to production.

```bash
# Per-env knobs that don't require editing the parameters file
azd env set AZURE_ENV_GPT_MODEL_CAPACITY 200
azd env set ACR_ALLOWED_IPS "203.0.113.4,198.51.100.0/24"
azd env set AI_SEARCH_LOCATION eastus2
azd provision
```

| Env var | Default | Bicep param |
| --- | --- | --- |
| `AZURE_ENV_GPT_MODEL_CAPACITY` | `100` | `gptDeploymentCapacity` |
| `ACR_ALLOWED_IPS` | empty | `acrAllowedIpRules` |
| `AI_SEARCH_LOCATION` | empty | `aiSearchLocation` |

App Insights `retentionInDays` (90 → 365) is still a `main.bicep`
default and requires a file edit to change.

## Cost-control tips that apply in both profiles

- **Azure OpenAI is pay-per-token** in GlobalStandard. The capacity number
  is a quota ceiling, not a reservation; it does not generate idle cost.
  The big lever for AOAI spend is request volume / prompt size, not the
  capacity number.
- **Container Apps Consumption profile** bills per active vCPU-second.
  Lowering `minReplicas` from 1 to 0 drops idle cost to zero on apps that
  tolerate cold starts (~2–10 s on first request).
- **Cosmos DB** can be switched to **serverless** for demo / low-traffic
  scenarios by adding `EnableServerless` to `capabilitiesToAdd` in the
  Cosmos AVM module call. Serverless has a 50 GB / container ceiling and
  no dedicated-throughput SLA; do not enable in production without
  validating the workload fits.
- **AI Search basic** and **App Configuration Standard** are flat-rate;
  the only way to save money on them between demos is to delete and
  redeploy the resource group.
