#!/bin/bash

# Stop script on any error
set -e

# -----------------------------------------------------------------------------
# Pre-flight: app registration env vars
# -----------------------------------------------------------------------------
missing_app_reg=()
for var in APP_WEB_CLIENT_ID APP_API_SCOPE; do
  val=$(azd env get-value "$var" 2>/dev/null || true)
  if [ -z "$val" ] || [[ "$val" == *"<"*">"* ]] || [[ "$val" == ERROR:* ]]; then
    missing_app_reg+=("$var")
  fi
done

if [ "${#missing_app_reg[@]}" -gt 0 ]; then
  echo ""
  echo "❌ Required app-registration values are not set in the azd environment:"
  for v in "${missing_app_reg[@]}"; do echo "    - $v"; done
  echo ""
  echo "Create the two Entra app registrations described in"
  echo "  docs/ConfigureAppAuthentication.md"
  echo "and then run, for example:"
  echo "  azd env set APP_WEB_CLIENT_ID <web-app-client-id>"
  echo "  azd env set APP_API_SCOPE     api://<api-app-client-id>/user_impersonation"
  echo ""
  echo "Aborting post-deployment: missing required app-registration values."
  exit 1
fi

# -----------------------------------------------------------------------------
# Build & deploy container images
# -----------------------------------------------------------------------------
# Bicep provisions all container apps with a public placeholder image so the
# initial revisions can boot even though the per-deploy ACR is empty. Here we
# build the real images directly into that ACR using `az acr build` (cloud-side
# build, no Docker required) and then flip each app to its built image. This
# keeps `azd up` self-contained: a clean environment with no pre-built shared
# registry will deploy successfully.
# -----------------------------------------------------------------------------

echo ""
echo "🛠  Resolving build context from azd environment..."

RESOURCE_GROUP=$(azd env get-value AZURE_RESOURCE_GROUP)
ACR_NAME=$(azd env get-value CONTAINER_REGISTRY_NAME)
ACR_LOGIN_SERVER=$(azd env get-value CONTAINER_REGISTRY_LOGIN_SERVER)
IMAGE_TAG=$(azd env get-value AZURE_ENV_IMAGETAG 2>/dev/null || true)
# azd env get-value writes "ERROR: key not found..." to stdout when missing — guard
# on empty / error prefix so we don't pass garbage as a Docker tag.
if [ -z "$IMAGE_TAG" ] || [ "$IMAGE_TAG" = "latest_v2" ] || [[ "$IMAGE_TAG" == ERROR:* ]]; then
  IMAGE_TAG="$(date +%Y%m%d%H%M%S)"
fi

APP_PROC=$(azd env get-value CONTAINER_APP_NAME)
APP_API=$(azd env get-value CONTAINER_API_APP_NAME)
APP_WORKFLOW=$(azd env get-value CONTAINER_WORKFLOW_APP_NAME)
APP_CLAIMS=$(azd env get-value CONTAINER_CLAIMS_APP_NAME)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "  ACR:          $ACR_NAME ($ACR_LOGIN_SERVER)"
echo "  Image tag:    $IMAGE_TAG"
echo "  Resource grp: $RESOURCE_GROUP"

stage_build_context() {
  local source_context="$1"
  local staged_context="$2"
  mkdir -p "$staged_context"
  tar \
    --exclude='./node_modules' \
    --exclude='*/node_modules' \
    --exclude='./dist' \
    --exclude='*/dist' \
    --exclude='./build' \
    --exclude='*/build' \
    --exclude='./.next' \
    --exclude='*/.next' \
    --exclude='./.parcel-cache' \
    --exclude='*/.parcel-cache' \
    --exclude='./.git' \
    --exclude='*/.git' \
    --exclude='./.venv' \
    --exclude='*/.venv' \
    --exclude='./__pycache__' \
    --exclude='*/__pycache__' \
    --exclude='./.pytest_cache' \
    --exclude='*/.pytest_cache' \
    --exclude='./.mypy_cache' \
    --exclude='*/.mypy_cache' \
    --exclude='./.ruff_cache' \
    --exclude='*/.ruff_cache' \
    -C "$source_context" -cf - . | tar -C "$staged_context" -xf -
}

wait_acr_build() {
  local run_id="$1"
  local image="$2"
  local status=""

  for attempt in $(seq 1 180); do
    status=$(az acr task show-run \
      --registry "$ACR_NAME" \
      --run-id "$run_id" \
      --query status \
      --output tsv \
      --only-show-errors 2>/dev/null || true)

    [ -z "$status" ] && status="Unknown"

    if [ "$status" = "Succeeded" ]; then
      echo "  ✅ ACR build $run_id for $image succeeded."
      return 0
    fi

    case "$status" in
      Failed|Canceled|Error|Timeout)
        local error_message
        error_message=$(az acr task show-run \
          --registry "$ACR_NAME" \
          --run-id "$run_id" \
          --query runErrorMessage \
          --output tsv \
          --only-show-errors 2>/dev/null || true)
        echo "  ❌ ACR build $run_id for $image ended with status '$status'. $error_message"
        return 1
        ;;
    esac

    echo "  ⏳ ACR build $run_id for $image status: $status ($attempt/180)"
    sleep 10
  done

  echo "  ❌ ACR build $run_id for $image did not finish after 1800 seconds."
  return 1
}

context_hash() {
  # Stable SHA256 over a sorted listing of "<relpath>|<sha256>".
  local path="$1"
  ( cd "$path" && find . -type f -print0 \
      | LC_ALL=C sort -z \
      | while IFS= read -r -d '' f; do
          h=$(sha256sum -- "$f" | awk '{print $1}')
          printf '%s|%s|' "${f#./}" "$h"
        done
  ) | sha256sum | awk '{print $1}'
}

acr_image_exists() {
  local acr="$1"
  local image="$2"
  local tag="$3"
  local tags
  tags=$(az acr repository show-tags --name "$acr" --repository "$image" --output tsv --only-show-errors 2>/dev/null || true)
  [ -z "$tags" ] && return 1
  printf '%s\n' "$tags" | tr -d '\r' | grep -Fxq "$tag"
}

env_key() {
  printf '%s' "$1" | tr '[:lower:]' '[:upper:]' | tr -c 'A-Z0-9' '_'
}

build_and_deploy() {
    local image="$1"
    local context="$2"
    local app="$3"
    local ref="${ACR_LOGIN_SERVER}/${image}:${IMAGE_TAG}"

    echo ""
    echo "🔨 Building $image -> $ref  (context: $context)"
  local staged_context
  staged_context="$(mktemp -d "${TMPDIR:-/tmp}/cps-acrbuild-${image}.XXXXXX")"
  echo "  staging clean build context: $staged_context"
  stage_build_context "$context" "$staged_context"
    # --no-wait avoids local CLI hangs after a server-side build completes;
    # wait_acr_build polls Azure for the authoritative run status.
    set +e
    local build_output
    build_output=$(
      cd "$staged_context"
        az acr build \
            --registry "$ACR_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --image "${image}:${IMAGE_TAG}" \
            --file Dockerfile \
            --no-logs \
            --no-wait \
            .
    2>&1)
    local build_status=$?
    set -e
    printf '%s\n' "$build_output" | sed 's/^/  /'
  rm -rf "$staged_context"
        if [ "$build_status" -ne 0 ]; then
          return "$build_status"
        fi
    local run_id
    run_id=$(printf '%s\n' "$build_output" | sed -nE 's/.*Queued a build with ID: ([[:alnum:]_-]+).*/\1/p' | tail -n 1)
    if [ -z "$run_id" ]; then
      echo "  ❌ Could not determine ACR build run id for $image."
      return 1
    fi
    wait_acr_build "$run_id" "$image"

    echo "🚀 Deploying $app <- $ref"
    update_containerapp_image "$app" "$ref"

    wait_containerapp_ready "$app" "$ref"
}

wait_containerapp_ready() {
  local app="$1"
  local expected_image="${2:-}"
  local state=""
  local current_image=""
  local details=""

  for attempt in $(seq 1 40); do
    details=$(az containerapp show \
      --name "$app" \
      --resource-group "$RESOURCE_GROUP" \
      --query "[properties.provisioningState, properties.template.containers[0].image]" \
      --output tsv \
      --only-show-errors 2>/dev/null || true)
    state=$(printf '%s\n' "$details" | sed -n '1p')
    current_image=$(printf '%s\n' "$details" | sed -n '2p')

    if [ "$state" = "Succeeded" ]; then
      if [ -z "$expected_image" ] || [ "$current_image" = "$expected_image" ]; then
        echo "  ✅ $app is ready."
        return 0
      fi
      echo "  ⏳ $app state: Succeeded, image not updated yet ($attempt/40)"
    else
      [ -z "$state" ] && state="Unknown"
      echo "  ⏳ $app state: $state ($attempt/40)"
    fi

    if [ "$state" = "Failed" ]; then
      echo "  ❌ Container App '$app' provisioning failed."
      return 1
    fi

    sleep 10
  done

  echo "  ❌ Container App '$app' did not become ready after 400 seconds."
  return 1
}

update_containerapp_image() {
  local app="$1"
  local image="$2"

  if command -v timeout >/dev/null 2>&1; then
    set +e
    timeout 120s az containerapp update \
      --name "$app" \
      --resource-group "$RESOURCE_GROUP" \
      --image "$image" \
      --no-wait \
      --only-show-errors >/dev/null
    local status=$?
    set -e

    if [ "$status" -eq 124 ] || [ "$status" -eq 137 ]; then
      echo "  ⚠️ az containerapp update timed out locally for $app; checking Azure provisioning state."
      return 0
    fi

    return "$status"
  fi

  az containerapp update \
    --name "$app" \
    --resource-group "$RESOURCE_GROUP" \
    --image "$image" \
    --no-wait \
    --only-show-errors >/dev/null
}

# --- Parallel build/deploy pipeline ---
# Phase 1: stage + decide skip per service.
PLAN_NAMES=(contentprocessor contentprocessorapi contentprocessorworkflow contentprocessorclaimsdemo)
declare -A PLAN_CONTEXT=(
  [contentprocessor]="$REPO_ROOT/src/ContentProcessor"
  [contentprocessorapi]="$REPO_ROOT/src/ContentProcessorAPI"
  [contentprocessorworkflow]="$REPO_ROOT/src/ContentProcessorWorkflow"
  [contentprocessorclaimsdemo]="$REPO_ROOT/src/ContentProcessorClaimsDemo"
)
declare -A PLAN_APP=(
  [contentprocessor]="$APP_PROC"
  [contentprocessorapi]="$APP_API"
  [contentprocessorworkflow]="$APP_WORKFLOW"
  [contentprocessorclaimsdemo]="$APP_CLAIMS"
)
declare -A PLAN_STAGE=()
declare -A PLAN_HASH=()
declare -A PLAN_RUNID=()
declare -A PLAN_REF=()
declare -A PLAN_SKIP=()
declare -A PLAN_HASHKEY=()
declare -A PLAN_TAGKEY=()

for image in "${PLAN_NAMES[@]}"; do
  context="${PLAN_CONTEXT[$image]}"
  staged="$(mktemp -d "${TMPDIR:-/tmp}/cps-acrbuild-${image}.XXXXXX")"
  stage_build_context "$context" "$staged"
  hash_val=$(context_hash "$staged")
  hash_key="LAST_BUILT_HASH_$(env_key "$image")"
  tag_key="LAST_BUILT_TAG_$(env_key "$image")"
  prev_hash=$(azd env get-value "$hash_key" 2>/dev/null || true)
  prev_tag=$(azd env get-value  "$tag_key"  2>/dev/null || true)
  [[ "$prev_hash" == ERROR:* ]] && prev_hash=""
  [[ "$prev_tag"  == ERROR:* ]] && prev_tag=""

  ref="${ACR_LOGIN_SERVER}/${image}:${IMAGE_TAG}"
  skip="false"
  if [ -n "$hash_val" ] && [ "$prev_hash" = "$hash_val" ] && [ -n "$prev_tag" ] && acr_image_exists "$ACR_NAME" "$image" "$prev_tag"; then
    echo "⏭  $image: context unchanged (hash ${hash_val:0:12}); reusing tag $prev_tag"
    ref="${ACR_LOGIN_SERVER}/${image}:${prev_tag}"
    skip="true"
    rm -rf "$staged"
    staged=""
  fi

  PLAN_STAGE[$image]="$staged"
  PLAN_HASH[$image]="$hash_val"
  PLAN_HASHKEY[$image]="$hash_key"
  PLAN_TAGKEY[$image]="$tag_key"
  PLAN_REF[$image]="$ref"
  PLAN_SKIP[$image]="$skip"
done

# Phase 2: queue all ACR builds in parallel.
for image in "${PLAN_NAMES[@]}"; do
  [ "${PLAN_SKIP[$image]}" = "true" ] && continue
  staged="${PLAN_STAGE[$image]}"
  echo ""
  echo "🔨 Queueing ACR build: ${image}:${IMAGE_TAG}"
  set +e
  build_output=$(cd "$staged" && az acr build \
    --registry "$ACR_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --image "${image}:${IMAGE_TAG}" \
    --file Dockerfile \
    --no-logs --no-wait . 2>&1)
  build_status=$?
  set -e
  if [ "$build_status" -ne 0 ]; then
    echo "$build_output" | sed 's/^/  /'
    echo "❌ az acr build failed for $image"
    exit "$build_status"
  fi
  run_id=$(printf '%s\n' "$build_output" | sed -nE 's/.*Queued a build with ID: ([[:alnum:]_-]+).*/\1/p' | tail -n 1)
  if [ -z "$run_id" ]; then
    echo "❌ Could not determine ACR build run id for $image. Output: $build_output"
    exit 1
  fi
  PLAN_RUNID[$image]="$run_id"
  echo "  Queued: $run_id"
done

# Phase 3: wait for each build, then kick off its container app update.
for image in "${PLAN_NAMES[@]}"; do
  if [ "${PLAN_SKIP[$image]}" != "true" ]; then
    wait_acr_build "${PLAN_RUNID[$image]}" "$image"
    azd env set "${PLAN_HASHKEY[$image]}" "${PLAN_HASH[$image]}" >/dev/null
    azd env set "${PLAN_TAGKEY[$image]}"  "$IMAGE_TAG"           >/dev/null
  fi
  app="${PLAN_APP[$image]}"
  ref="${PLAN_REF[$image]}"
  echo "🚀 Deploying $app <- $ref"
  update_containerapp_image "$app" "$ref"
done

# Phase 4: wait for all container apps to roll.
for image in "${PLAN_NAMES[@]}"; do
  wait_containerapp_ready "${PLAN_APP[$image]}" "${PLAN_REF[$image]}"
  staged="${PLAN_STAGE[$image]}"
  [ -n "$staged" ] && [ -d "$staged" ] && rm -rf "$staged"
done

echo ""
echo "✅ All container images built and deployed."
echo ""

echo "🔍 Fetching container app info from azd environment..."

get_azd_env_optional() {
  local key="$1"
  local value
  value=$(azd env get-value "$key" 2>/dev/null || true)
  case "$value" in
    ""|ERROR:*) echo "" ;;
    *) printf '%s' "$value" ;;
  esac
}

# Load values from azd env
CONTAINER_CLAIMS_APP_FQDN=$(azd env get-value CONTAINER_CLAIMS_APP_FQDN)
CONTAINER_WEB_APP_FQDN=$(get_azd_env_optional CONTAINER_WEB_APP_FQDN)

CONTAINER_API_APP_NAME=$(azd env get-value CONTAINER_API_APP_NAME)
CONTAINER_API_APP_FQDN=$(azd env get-value CONTAINER_API_APP_FQDN)

CONTAINER_WORKFLOW_APP_NAME=$(azd env get-value CONTAINER_WORKFLOW_APP_NAME)

# Get subscription and resource group (assuming same for both)
SUBSCRIPTION_ID=$(azd env get-value AZURE_SUBSCRIPTION_ID)
RESOURCE_GROUP=$(azd env get-value AZURE_RESOURCE_GROUP)

# Construct Azure Portal URLs
API_APP_PORTAL_URL="https://portal.azure.com/#resource/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.App/containerApps/$CONTAINER_API_APP_NAME"
WORKFLOW_APP_PORTAL_URL="https://portal.azure.com/#resource/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.App/containerApps/$CONTAINER_WORKFLOW_APP_NAME"

echo "✅ Fetched container app info."
echo "Values are as follows:"
echo "  🕒 Started at: $(date)"
echo "  🌍 Claims Demo FQDN: $CONTAINER_CLAIMS_APP_FQDN"
echo "  🌍 API App FQDN: $CONTAINER_API_APP_FQDN"
echo "  🔗 API App Portal URL: $API_APP_PORTAL_URL"

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Go from infra/scripts → root → src
DATA_SCRIPT_PATH="$SCRIPT_DIR/../../src/ContentProcessorAPI/samples/schemas"

# Normalize the path (optional, in case of ../..)
DATA_SCRIPT_PATH="$(realpath "$DATA_SCRIPT_PATH")"

# Output
echo ""
echo "🧭 Claims Demo App Endpoint: $CONTAINER_CLAIMS_APP_FQDN"

echo ""
echo "🧭 API App Details:"
echo "  ✅ Name: $CONTAINER_API_APP_NAME"
echo "  🌐 Endpoint: $CONTAINER_API_APP_FQDN"
echo "  🔗 Portal URL: $API_APP_PORTAL_URL"

echo ""
echo "🧭 Workflow App Details:"
echo "  ✅ Name: $CONTAINER_WORKFLOW_APP_NAME"
echo "  🔗 Portal URL: $WORKFLOW_APP_PORTAL_URL"

register_spa_redirect_uris() {
  local client_id="$1"
  shift

  if [ -z "$client_id" ] || [[ "$client_id" == *"<"* ]]; then
    echo ""
    echo "🔐 APP_WEB_CLIENT_ID is not set; skipping SPA redirect URI registration."
    return
  fi

  echo ""
  echo "🔐 Registering SPA redirect URI(s) for app registration $client_id..."
  for host_name in "$@"; do
    case "$host_name" in
      ""|ERROR:*|*" "*) ;;
      *) echo "  https://${host_name#https://}" ;;
    esac
  done

  local tmp_app tmp_body object_id app_show_error
  tmp_app=$(mktemp)
  tmp_body=$(mktemp)

  app_show_error=$(az ad app show --id "$client_id" -o json > "$tmp_app" 2>&1) || {
    rm -f "$tmp_app" "$tmp_body"
    echo "  ❌ Could not read app registration '$client_id'."
    [ -n "$app_show_error" ] && echo "     Details: $app_show_error"
    if [[ "$app_show_error" == *"TokenCreatedWithOutdatedPolicies"* || "$app_show_error" == *"InteractionRequired"* || "$app_show_error" == *"Continuous access evaluation"* ]]; then
      echo "     Refresh Microsoft Graph auth with: az login --use-device-code --scope https://graph.microsoft.com//.default"
    fi
    echo "     Ensure the signed-in deployment identity owns the app registration or has Application Administrator/Cloud Application Administrator permissions."
    exit 1
  }

  object_id=$(python3 - "$tmp_app" "$tmp_body" "$@" <<'PY'
import json
import sys

app_path, body_path, *host_names = sys.argv[1:]
with open(app_path, encoding="utf-8") as handle:
    app = json.load(handle)

existing = (app.get("spa") or {}).get("redirectUris") or []
redirect_uris = []
for host_name in host_names:
    host_name = (host_name or "").strip()
    if not host_name or host_name.startswith("ERROR:") or any(char.isspace() for char in host_name):
        continue
    origin = host_name if host_name.startswith(("http://", "https://")) else f"https://{host_name}"
    origin = origin.rstrip("/")
    redirect_uris.extend([origin, f"{origin}/"])

merged = sorted(set(existing + redirect_uris))
with open(body_path, "w", encoding="utf-8") as handle:
    json.dump({"spa": {"redirectUris": merged}}, handle, separators=(",", ":"))

print(app["id"])
PY
  )

  if ! az rest \
    --method PATCH \
    --url "https://graph.microsoft.com/v1.0/applications/$object_id" \
    --headers "Content-Type=application/json" \
    --body "@$tmp_body" \
    --only-show-errors >/dev/null; then
    rm -f "$tmp_app" "$tmp_body"
    echo "  ❌ Failed to update SPA app registration redirect URIs."
    echo "     Ensure the signed-in deployment identity owns the app registration or has Application Administrator/Cloud Application Administrator permissions."
    exit 1
  fi

  rm -f "$tmp_app" "$tmp_body"
  echo "  ✅ SPA redirect URIs are up to date."
}

APP_WEB_CLIENT_ID_VAL=$(azd env get-value APP_WEB_CLIENT_ID 2>/dev/null || true)
register_spa_redirect_uris "$APP_WEB_CLIENT_ID_VAL" "$CONTAINER_WEB_APP_FQDN" "$CONTAINER_CLAIMS_APP_FQDN"

echo ""
echo "📦 Registering schemas and creating schema set..."
echo "  ⏳ Waiting for API to be ready..."

# Postprov runs immediately after the API container app gets a new
# image, so the first /schemavault/ probe routinely hits a still-warming
# replica. We keep the per-attempt timeout short but extend the total
# budget to ~5 min so cold starts (image pull + EasyAuth init + Cosmos
# warm) don't silently skip schema registration. The fail-fast block
# below escalates the previous quiet "Skipping..." into a hard exit.
MAX_RETRIES=20
RETRY_INTERVAL=15
API_BASE_URL="https://$CONTAINER_API_APP_FQDN"

# Optional: acquire a bearer token for the API. If APP_API_SCOPE is set in
# the azd env (per docs/ConfigureAppAuthentication.md), the script tries to
# request a token via the signed-in az CLI principal. When EasyAuth is enabled
# on the API container app this is required; when EasyAuth is not yet
# configured the calls succeed without it.
AUTH_HEADER_ARGS=()
APP_API_SCOPE_VAL=$(azd env get-value APP_API_SCOPE 2>/dev/null || true)
if [ -n "$APP_API_SCOPE_VAL" ] && [[ "$APP_API_SCOPE_VAL" != *"<"* ]]; then
  TOKEN_RESOURCE="${APP_API_SCOPE_VAL%/user_impersonation}"
  echo "  🔐 Acquiring bearer token for $TOKEN_RESOURCE ..."
  if TOKEN_OUTPUT=$(az account get-access-token --resource "$TOKEN_RESOURCE" --query accessToken -o tsv 2>&1); then
    TOKEN_STATUS=0
  else
    TOKEN_STATUS=$?
  fi

  if [ "$TOKEN_STATUS" -ne 0 ] && [[ "$TOKEN_OUTPUT" == *"AADSTS65001"* && "$TOKEN_RESOURCE" == api://* ]]; then
    API_APP_ID_FOR_CONSENT="${TOKEN_RESOURCE#api://}"
    SCOPE_NAME_FOR_CONSENT="${APP_API_SCOPE_VAL##*/}"
    [ -z "$SCOPE_NAME_FOR_CONSENT" ] && SCOPE_NAME_FOR_CONSENT="user_impersonation"
    AZURE_CLI_APP_ID="04b07795-8ddb-461a-bbee-02f9e1bf7b46"

    echo "  🔐 Granting Microsoft Azure CLI consent to API scope '$SCOPE_NAME_FOR_CONSENT'..."
    az ad sp show --id "$AZURE_CLI_APP_ID" >/dev/null 2>&1 || \
      az ad sp create --id "$AZURE_CLI_APP_ID" --only-show-errors >/dev/null
    az ad app permission grant --id "$AZURE_CLI_APP_ID" --api "$API_APP_ID_FOR_CONSENT" --scope "$SCOPE_NAME_FOR_CONSENT" --only-show-errors >/dev/null

    if TOKEN_OUTPUT=$(az account get-access-token --resource "$TOKEN_RESOURCE" --query accessToken -o tsv 2>&1); then
      TOKEN_STATUS=0
    else
      TOKEN_STATUS=$?
    fi
  fi

  if [ "$TOKEN_STATUS" -eq 0 ] && [ -n "$TOKEN_OUTPUT" ]; then
    TOKEN="$TOKEN_OUTPUT"
    AUTH_HEADER_ARGS=(-H "Authorization: Bearer $TOKEN")
    echo "  🔐 Bearer token acquired."
  else
    echo "  🔐 Could not acquire token; calls will be unauthenticated."
  fi
fi

for i in $(seq 1 $MAX_RETRIES); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${AUTH_HEADER_ARGS[@]}" "$API_BASE_URL/schemavault/" 2>/dev/null || echo "000")
  if [ "$STATUS" = "200" ]; then
    echo "  ✅ API is ready."
    break
  fi
  echo "  Attempt $i/$MAX_RETRIES – API returned HTTP $STATUS, retrying in ${RETRY_INTERVAL}s..."
  sleep $RETRY_INTERVAL
done

if [ "$STATUS" != "200" ]; then
  # Hard-fail rather than continuing with a "Skipping..." warning.
  # Without the schemas + schema set the demo's first claim is broken
  # (the workflow has no analyzers to invoke), and the previous quiet-
  # skip behaviour meant the breakage only showed up minutes later in
  # the UI. Surface it now so `azd up` exits non-zero and the operator
  # immediately sees what happened.
  TOTAL_WAIT=$(( MAX_RETRIES * RETRY_INTERVAL ))
  echo "  â API at $API_BASE_URL did not become ready after $MAX_RETRIES attempts (${TOTAL_WAIT}s total)." >&2
  echo "     Schema registration cannot proceed. Re-run 'azd hooks run postprovision' once the API container app is ready," >&2
  echo "     or inspect the container app logs for the failing replica." >&2
  exit 1
else
  # ---------- Schema registration (no Python dependency) ----------
  SCHEMA_INFO_FILE="$DATA_SCRIPT_PATH/schema_info.json"
  SCHEMAVAULT_URL="$API_BASE_URL/schemavault/"
  SCHEMASETVAULT_URL="$API_BASE_URL/schemasetvault/"

  # --- Step 1: Register schemas ---
  echo ""
  echo "============================================================"
  echo "Step 1: Register schemas"
  echo "============================================================"

  # Fetch existing schemas
  EXISTING_SCHEMAS=$(curl -s "${AUTH_HEADER_ARGS[@]}" "$SCHEMAVAULT_URL" 2>/dev/null || echo "[]")
  EXISTING_COUNT=$(echo "$EXISTING_SCHEMAS" | grep -o '"Id"' | wc -l)
  echo "Fetched $EXISTING_COUNT existing schema(s)."

  # Read schema entries from manifest
  SCHEMA_COUNT=$(cat "$SCHEMA_INFO_FILE" | grep -o '"File"' | wc -l)
  REGISTERED_IDS=()
  REGISTERED_NAMES=()

  for idx in $(seq 0 $((SCHEMA_COUNT - 1))); do
    # Parse entry fields using grep/sed (no python needed)
    ENTRY=$(cat "$SCHEMA_INFO_FILE")
    FILE_NAME=$(echo "$ENTRY" | grep -o '"File"[[:space:]]*:[[:space:]]*"[^"]*"' | sed -n "$((idx + 1))p" | sed 's/.*"File"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
    CLASS_NAME=$(echo "$ENTRY" | grep -o '"ClassName"[[:space:]]*:[[:space:]]*"[^"]*"' | sed -n "$((idx + 1))p" | sed 's/.*"ClassName"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
    DESCRIPTION=$(echo "$ENTRY" | grep -o '"Description"[[:space:]]*:[[:space:]]*"[^"]*"' | sed -n "$((idx + 1))p" | sed 's/.*"Description"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')

    SCHEMA_FILE="$DATA_SCRIPT_PATH/$FILE_NAME"

    echo ""
    echo "Processing schema: $CLASS_NAME"

    if [ ! -f "$SCHEMA_FILE" ]; then
      echo "Error: Schema file '$SCHEMA_FILE' does not exist. Skipping..."
      continue
    fi

    # Check if already registered
    EXISTING_ID=""
    # Use a simple approach: look for the ClassName in the existing schemas response
    if echo "$EXISTING_SCHEMAS" | grep -q "\"ClassName\"[[:space:]]*:[[:space:]]*\"$CLASS_NAME\""; then
      # Extract the Id for this ClassName – find the object containing it
      EXISTING_ID=$(echo "$EXISTING_SCHEMAS" | sed 's/},/}\n/g' | grep "\"ClassName\"[[:space:]]*:[[:space:]]*\"$CLASS_NAME\"" | grep -o '"Id"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
    fi

    if [ -n "$EXISTING_ID" ]; then
      echo "  Schema '$CLASS_NAME' already exists with ID: $EXISTING_ID"
      REGISTERED_IDS+=("$EXISTING_ID")
      REGISTERED_NAMES+=("$CLASS_NAME")
      continue
    fi

    echo "  Registering new schema '$CLASS_NAME' (JSON-native)..."

    if ! command -v jq >/dev/null 2>&1; then
      echo "  Error: 'jq' is required for JSON-native schema registration. Install jq and re-run 'azd hooks run postprovision'." >&2
      exit 1
    fi

    REQUEST_BODY=$(jq -n \
      --arg cn   "$CLASS_NAME" \
      --arg desc "$DESCRIPTION" \
      --slurpfile env "$SCHEMA_FILE" \
      '{ClassName: $cn,
        Description: $desc,
        FieldSchema: $env[0].fieldSchema,
        BaseAnalyzerId: ($env[0].baseAnalyzerId // "prebuilt-document"),
        CompletionModel: (($env[0].models // {}).completion // "gpt-4.1-mini")}')

    RESPONSE=$(curl -s -w "\n%{http_code}" \
      -X POST "${SCHEMAVAULT_URL}json" \
      "${AUTH_HEADER_ARGS[@]}" \
      -H "Content-Type: application/json" \
      -d "$REQUEST_BODY" \
      --connect-timeout 60)

    HTTP_CODE=$(echo "$RESPONSE" | tail -1)
    BODY=$(echo "$RESPONSE" | sed '$d')

    if [ "$HTTP_CODE" = "200" ]; then
      SCHEMA_ID=$(echo "$BODY" | sed 's/.*"Id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
      echo "  Successfully registered: $DESCRIPTION's Schema Id - $SCHEMA_ID"
      REGISTERED_IDS+=("$SCHEMA_ID")
      REGISTERED_NAMES+=("$CLASS_NAME")
    else
      echo "  Failed to register '$CLASS_NAME'. HTTP Status: $HTTP_CODE"
      echo "  Error Response: $BODY"
    fi
  done

  # --- Step 2: Create schema set ---
  echo ""
  echo "============================================================"
  echo "Step 2: Create schema set"
  echo "============================================================"

  # Parse schemaset config from manifest
  SET_NAME=$(cat "$SCHEMA_INFO_FILE" | grep -A2 '"schemaset"' | grep '"Name"' | sed 's/.*"Name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
  SET_DESC=$(cat "$SCHEMA_INFO_FILE" | grep -A3 '"schemaset"' | grep '"Description"' | sed 's/.*"Description"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')

  # Fetch existing schema sets
  EXISTING_SETS=$(curl -s "${AUTH_HEADER_ARGS[@]}" "$SCHEMASETVAULT_URL" 2>/dev/null || echo "[]")

  SCHEMASET_ID=""
  if echo "$EXISTING_SETS" | grep -q "\"Name\"[[:space:]]*:[[:space:]]*\"$SET_NAME\""; then
    SCHEMASET_ID=$(echo "$EXISTING_SETS" | sed 's/},/}\n/g' | grep "\"Name\"[[:space:]]*:[[:space:]]*\"$SET_NAME\"" | grep -o '"Id"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
    echo "  Schema set '$SET_NAME' already exists with ID: $SCHEMASET_ID"
  else
    echo "  Creating schema set '$SET_NAME'..."
    RESPONSE=$(curl -s -w "\n%{http_code}" \
      -X POST "$SCHEMASETVAULT_URL" \
      "${AUTH_HEADER_ARGS[@]}" \
      -H "Content-Type: application/json" \
      -d "{\"Name\": \"$SET_NAME\", \"Description\": \"$SET_DESC\"}" \
      --connect-timeout 30)

    HTTP_CODE=$(echo "$RESPONSE" | tail -1)
    BODY=$(echo "$RESPONSE" | sed '$d')

    if [ "$HTTP_CODE" = "200" ]; then
      SCHEMASET_ID=$(echo "$BODY" | sed 's/.*"Id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
      echo "  Created schema set '$SET_NAME' with ID: $SCHEMASET_ID"
    else
      echo "  Failed to create schema set. HTTP Status: $HTTP_CODE"
      echo "  Error Response: $BODY"
    fi
  fi

  if [ -z "$SCHEMASET_ID" ]; then
    echo "Error: Could not create or find schema set. Aborting step 3."
  else
    # --- Step 3: Add schemas to schema set ---
    echo ""
    echo "============================================================"
    echo "Step 3: Add schemas to schema set"
    echo "============================================================"

    ALREADY_IN_SET=$(curl -s "${AUTH_HEADER_ARGS[@]}" "${SCHEMASETVAULT_URL}${SCHEMASET_ID}/schemas" 2>/dev/null || echo "[]")

    # Iterate over registered schemas
    for i in "${!REGISTERED_IDS[@]}"; do
      SCHEMA_ID="${REGISTERED_IDS[$i]}"
      CLASS_NAME="${REGISTERED_NAMES[$i]}"

      if echo "$ALREADY_IN_SET" | grep -q "\"Id\"[[:space:]]*:[[:space:]]*\"$SCHEMA_ID\""; then
        echo "  Schema '$CLASS_NAME' ($SCHEMA_ID) already in schema set - skipped"
        continue
      fi

      RESPONSE=$(curl -s -w "\n%{http_code}" \
        -X POST "${SCHEMASETVAULT_URL}${SCHEMASET_ID}/schemas" \
        "${AUTH_HEADER_ARGS[@]}" \
        -H "Content-Type: application/json" \
        -d "{\"SchemaId\": \"$SCHEMA_ID\"}" \
        --connect-timeout 30)

      HTTP_CODE=$(echo "$RESPONSE" | tail -1)

      if [ "$HTTP_CODE" = "200" ]; then
        echo "  Added '$CLASS_NAME' ($SCHEMA_ID) to schema set"
      else
        BODY=$(echo "$RESPONSE" | sed '$d')
        echo "  Failed to add '$CLASS_NAME' to schema set. HTTP $HTTP_CODE"
        echo "    Error Response: $BODY"
      fi
    done
  fi

  echo ""
  echo "============================================================"
  echo "Schema registration process completed."
  echo "  Schemas registered: ${#REGISTERED_IDS[@]}"
  echo "============================================================"
fi

# --- Refresh Content Understanding Cognitive Services account ---
echo ""
echo "============================================================"
echo "Refreshing Content Understanding Cognitive Services account..."
echo "============================================================"

CU_ACCOUNT_NAME=$(azd env get-value CONTENT_UNDERSTANDING_ACCOUNT_NAME 2>/dev/null || echo "")

if [ -z "$CU_ACCOUNT_NAME" ]; then
  echo "  ⚠️ CONTENT_UNDERSTANDING_ACCOUNT_NAME not found in azd env. Skipping refresh."
else
  echo "  Refreshing account: $CU_ACCOUNT_NAME in resource group: $RESOURCE_GROUP"
  if az cognitiveservices account update \
    -g "$RESOURCE_GROUP" \
    -n "$CU_ACCOUNT_NAME" \
    --tags refresh=true \
    --output none; then
    echo "  ✅ Successfully refreshed Cognitive Services account '$CU_ACCOUNT_NAME'."
  else
    echo "  ❌ Failed to refresh Cognitive Services account '$CU_ACCOUNT_NAME'."
  fi
fi

# --- AI Search policy index seed (Phase D) ---
# Sends sample policy markdown to the API, which uses its managed identity to
# create the Search index and upload documents. This keeps one-command deploys
# working when Storage is private-networked and avoids Search admin keys.
AI_SEARCH_NAME=$(azd env get-value AI_SEARCH_NAME 2>/dev/null || echo "")

if [ -n "$AI_SEARCH_NAME" ]; then
  echo ""
  echo "============================================================"
  echo "AI Search: seeding policy index"
  echo "============================================================"

  INDEX_NAME=$(azd env get-value AI_SEARCH_INDEX_NAME)
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  # Claims-handling guidance corpus (advisory). Member policies are seeded
  # separately into a different index by the member-policies seed step.
  POLICIES_DIR="${SCRIPT_DIR}/../sample-policies/handling-guidance"

  TMPDIR_LOCAL=$(mktemp -d)
  trap "rm -rf $TMPDIR_LOCAL" EXIT
  PAYLOAD_FILE="$TMPDIR_LOCAL/search-seed.json"
  python3 - "$INDEX_NAME" "$POLICIES_DIR" > "$PAYLOAD_FILE" <<'PY'
import json
import pathlib
import sys

index_name = sys.argv[1]
policies_dir = pathlib.Path(sys.argv[2])
documents = []
for path in sorted(policies_dir.glob("*.md")):
    documents.append({
        "source_filename": path.name,
        "section": path.stem,
        "content": path.read_text(encoding="utf-8"),
    })
print(json.dumps({"index_name": index_name, "documents": documents}))
PY

  SEED_URL="$API_BASE_URL/claimsdemo/policy-index/seed"
  MAX_SEED_RETRIES=10
  for attempt in $(seq 1 $MAX_SEED_RETRIES); do
    echo "  Seeding '$INDEX_NAME' through API managed identity (attempt $attempt/$MAX_SEED_RETRIES)..."
    STATUS=$(curl -sS -o "$TMPDIR_LOCAL/search-seed-response.json" -w "%{http_code}" \
      "${AUTH_HEADER_ARGS[@]}" \
      -H "Content-Type: application/json" \
      --data-binary "@$PAYLOAD_FILE" \
      "$SEED_URL" || echo "000")
    if [ "$STATUS" = "200" ]; then
      DOC_COUNT=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("documents_uploaded", ""))' "$TMPDIR_LOCAL/search-seed-response.json")
      echo "  [OK] AI Search policy index seeded with ${DOC_COUNT} document(s)."
      break
    fi
    if [ "$attempt" = "$MAX_SEED_RETRIES" ]; then
      echo "  [Error] AI Search seeding failed with HTTP $STATUS:"
      cat "$TMPDIR_LOCAL/search-seed-response.json"
      exit 1
    fi
    echo "  [Wait] AI Search seeding not ready yet (HTTP $STATUS)."
    sleep 20
  done

  # --- Member auto-policy contracts (authoritative source) --- #
  # Reads infra/sample-policies/member-policies/_index.json (filterable
  # metadata) joined to the per-policy markdown body, then POSTs to the
  # member-policies seed endpoint. The recommendation agent retrieves
  # from this index by exact policy_number filter.
  MEMBER_INDEX_NAME=$(azd env get-value MEMBER_POLICIES_INDEX_NAME 2>/dev/null || echo "")
  if [ -n "$MEMBER_INDEX_NAME" ]; then
    echo ""
    echo "AI Search: seeding member-policies index"

    MEMBER_DIR="${SCRIPT_DIR}/../sample-policies/member-policies"
    MEMBER_INDEX_FILE="${MEMBER_DIR}/_index.json"
    if [ ! -f "$MEMBER_INDEX_FILE" ]; then
      echo "  [Skip] No _index.json found at $MEMBER_INDEX_FILE."
    else
      MEMBER_PAYLOAD_FILE="$TMPDIR_LOCAL/member-policies-seed.json"
      python3 - "$MEMBER_INDEX_NAME" "$MEMBER_DIR" "$MEMBER_INDEX_FILE" > "$MEMBER_PAYLOAD_FILE" <<'PY'
import json
import pathlib
import sys

index_name = sys.argv[1]
member_dir = pathlib.Path(sys.argv[2])
meta = json.loads(pathlib.Path(sys.argv[3]).read_text(encoding="utf-8"))

documents = []
for entry in meta.get("policies", []):
    md_path = member_dir / entry["source_filename"]
    if not md_path.exists():
        continue
    vins = [v.get("vin", "") for v in entry.get("covered_vehicles", []) if v.get("vin")]
    documents.append({
        "policy_number": entry["policy_number"],
        "source_filename": entry["source_filename"],
        "content": md_path.read_text(encoding="utf-8"),
        "form_version": entry.get("form_version", ""),
        "carrier": entry.get("carrier", ""),
        "state": entry.get("state", ""),
        "effective_date": entry.get("effective_date", ""),
        "expiration_date": entry.get("expiration_date", ""),
        "status": entry.get("status", ""),
        "named_insureds": entry.get("named_insureds", []),
        "excluded_drivers": entry.get("excluded_drivers", []),
        "vins": vins,
        "endorsements": entry.get("endorsements", []),
    })
print(json.dumps({"index_name": index_name, "documents": documents}))
PY

      MEMBER_SEED_URL="$API_BASE_URL/claimsdemo/member-policies-index/seed"
      for attempt in $(seq 1 $MAX_SEED_RETRIES); do
        echo "  Seeding '$MEMBER_INDEX_NAME' through API managed identity (attempt $attempt/$MAX_SEED_RETRIES)..."
        STATUS=$(curl -sS -o "$TMPDIR_LOCAL/member-seed-response.json" -w "%{http_code}" \
          "${AUTH_HEADER_ARGS[@]}" \
          -H "Content-Type: application/json" \
          --data-binary "@$MEMBER_PAYLOAD_FILE" \
          "$MEMBER_SEED_URL" || echo "000")
        if [ "$STATUS" = "200" ]; then
          DOC_COUNT=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("documents_uploaded", ""))' "$TMPDIR_LOCAL/member-seed-response.json")
          echo "  [OK] Member-policies index seeded with ${DOC_COUNT} document(s)."
          break
        fi
        if [ "$attempt" = "$MAX_SEED_RETRIES" ]; then
          echo "  [Error] Member-policies seeding failed with HTTP $STATUS:"
          cat "$TMPDIR_LOCAL/member-seed-response.json"
          exit 1
        fi
        echo "  [Wait] Member-policies seeding not ready yet (HTTP $STATUS)."
        sleep 20
      done
    fi
  fi
fi

# Note: Content Understanding analyzers (linked router + per-schema field
# extractors) are now self-healing — the API creates them on-demand on first
# claim via auto_router.py with hash-derived ids, so no pre-warm step is
# required here.

# ---------- Recommendation grounding warm-up (MED #8) ----------
# After both AI Search indexes are populated, the API MI can read them but
# the Foundry project's MI (used by AzureAISearchTool inside the agent)
# usually needs another 5-10 min for Search RBAC to propagate. Without
# this warm-up the FIRST recommendation in the demo 502s during that
# window — visible and embarrassing in front of customers. Hit the warm-up
# endpoint with retries to drive the Foundry MI -> Search path until it
# completes successfully.
if [ -n "${AI_SEARCH_NAME:-}" ] && [ -n "${CONTAINER_API_APP_FQDN:-}" ]; then
  echo ""
  echo "============================================================"
  echo "AI Search: warming recommendation grounding (Foundry MI -> AI Search RBAC)"
  echo "============================================================"

  WARMUP_URL="$API_BASE_URL/claimsdemo/warmup-grounding"
  MAX_WARMUP_RETRIES=20
  WARMUP_INTERVAL=30
  WARMED_UP=0

  for attempt in $(seq 1 $MAX_WARMUP_RETRIES); do
    echo "  Warm-up attempt $attempt/$MAX_WARMUP_RETRIES (timeout per attempt: 120s)..."
    WARMUP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
      "${AUTH_HEADER_ARGS[@]}" \
      -H "Content-Type: application/json" \
      -d '{}' \
      --max-time 120 \
      "$WARMUP_URL" || echo "000")

    if [ "$WARMUP_STATUS" = "200" ]; then
      echo "  ✅ Recommendation grounding warmed."
      WARMED_UP=1
      break
    fi

    echo "  ⏳ Grounding still propagating (HTTP $WARMUP_STATUS); retrying in ${WARMUP_INTERVAL}s..."
    if [ "$attempt" -lt "$MAX_WARMUP_RETRIES" ]; then
      sleep $WARMUP_INTERVAL
    fi
  done

  if [ "$WARMED_UP" -ne 1 ]; then
    # Don't fail postprov here — Search RBAC sometimes needs >10 min and
    # the demo recovers naturally once it propagates. But surface the
    # state loudly so the operator knows the first recommendation may
    # 502 until Foundry MI -> AI Search propagation completes.
    TOTAL_WARMUP_WAIT=$(( MAX_WARMUP_RETRIES * WARMUP_INTERVAL ))
    echo "  ⚠️  Recommendation grounding warm-up did not succeed within ${TOTAL_WARMUP_WAIT}s." >&2
    echo "     The demo will still work, but the first recommendation may 502 until" >&2
    echo "     the Foundry project managed identity finishes propagating to AI Search." >&2
    echo "     Re-run 'azd hooks run postprovision' or wait a few more minutes before demoing." >&2
  fi
fi
