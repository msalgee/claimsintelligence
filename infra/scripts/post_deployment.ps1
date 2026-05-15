# Stop script on any error
$ErrorActionPreference = "Stop"

# -----------------------------------------------------------------------------
# Build & deploy container images
# -----------------------------------------------------------------------------
# Bicep provisions all container apps with a public placeholder image so the
# initial revisions can boot even though the per-deploy ACR is empty. Here we
# build the real images directly into that ACR using `az acr build` (cloud-side
# build, no Docker required) and then flip each app to its built image. This
# keeps `azd up` self-contained: a clean environment with no pre-built shared
# registry will deploy successfully.
#
# Optimisations:
#   * All four ACR builds are queued in parallel (server-side); we then wait
#     for each, swap the corresponding container app image, and wait for ACA
#     to roll. Wall time is bounded by the slowest single build instead of
#     the sum of all four.
#   * For each service we hash the staged build context. If the hash matches
#     the value stored under `LAST_BUILT_HASH_<svc>` in the azd environment
#     and the previously-built image still exists in ACR, we skip the build
#     and re-tag/redeploy the existing image. This makes follow-up deploys
#     where only one service changed near-instant.
#   * App-registration env vars are validated up front so we fail fast with
#     a clear message instead of producing a broken deploy.
# -----------------------------------------------------------------------------

# ----- Pre-flight: app registration env vars ---------------------------------
function Test-AzdValuePlaceholder {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $true }
    if ($Value -match '<.*>')                 { return $true }
    if ($Value -match '^ERROR:')              { return $true }
    return $false
}

$RequiredAppRegVars = @('APP_WEB_CLIENT_ID','APP_API_SCOPE')
$MissingAppRegVars = @()
foreach ($name in $RequiredAppRegVars) {
    $val = (azd env get-value $name 2>$null)
    if (Test-AzdValuePlaceholder -Value $val) { $MissingAppRegVars += $name }
}
if ($MissingAppRegVars.Count -gt 0) {
    Write-Host ""
    Write-Host "[ERROR] Required app-registration values are not set in the azd environment:" -ForegroundColor Red
    foreach ($name in $MissingAppRegVars) { Write-Host "    - $name" -ForegroundColor Red }
    Write-Host ""
    Write-Host "Create the two Entra app registrations described in" -ForegroundColor Yellow
    Write-Host "  docs/ConfigureAppAuthentication.md" -ForegroundColor Yellow
    Write-Host "and then run, for example:" -ForegroundColor Yellow
    Write-Host "  azd env set APP_WEB_CLIENT_ID <web-app-client-id>" -ForegroundColor Yellow
    Write-Host "  azd env set APP_API_SCOPE     api://<api-app-client-id>/user_impersonation" -ForegroundColor Yellow
    Write-Host ""
    throw "Aborting post-deployment: missing required app-registration values."
}

Write-Host ""
Write-Host "[Build] Resolving build context from azd environment..."

$ResourceGroup    = azd env get-value AZURE_RESOURCE_GROUP
$AcrName          = azd env get-value CONTAINER_REGISTRY_NAME
$AcrLoginServer   = azd env get-value CONTAINER_REGISTRY_LOGIN_SERVER
$ImageTag         = (azd env get-value AZURE_ENV_IMAGETAG 2>$null)
# azd env get-value writes "ERROR: key not found..." to stdout when missing — guard
# on both exit code and the error prefix so we don't pass garbage as a Docker tag.
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($ImageTag) -or $ImageTag -like 'ERROR:*' -or $ImageTag -eq 'latest_v2') {
    $ImageTag = Get-Date -Format 'yyyyMMddHHmmss'
}
$global:LASTEXITCODE = 0

$AppContentProcessor = azd env get-value CONTAINER_APP_NAME
$AppApi              = azd env get-value CONTAINER_API_APP_NAME
$AppWorkflow         = azd env get-value CONTAINER_WORKFLOW_APP_NAME
$AppClaims           = azd env get-value CONTAINER_CLAIMS_APP_NAME

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

$BuildPlan = @(
    [pscustomobject]@{ Image = 'contentprocessor';          Context = (Join-Path $RepoRoot 'src/ContentProcessor');           App = $AppContentProcessor },
    [pscustomobject]@{ Image = 'contentprocessorapi';       Context = (Join-Path $RepoRoot 'src/ContentProcessorAPI');        App = $AppApi              },
    [pscustomobject]@{ Image = 'contentprocessorworkflow';  Context = (Join-Path $RepoRoot 'src/ContentProcessorWorkflow');   App = $AppWorkflow         },
    [pscustomobject]@{ Image = 'contentprocessorclaimsdemo';Context = (Join-Path $RepoRoot 'src/ContentProcessorClaimsDemo'); App = $AppClaims           }
)
foreach ($svc in $BuildPlan) {
    foreach ($prop in @('ImageRef','TempContext','ContextHash','HashEnvName','TagEnvName','SkipBuild','RunId')) {
        if (-not $svc.PSObject.Properties.Match($prop).Count) {
            $svc | Add-Member -NotePropertyName $prop -NotePropertyValue $null
        }
    }
}

Write-Host "  ACR:          $AcrName ($AcrLoginServer)"
Write-Host "  Image tag:    $ImageTag"
Write-Host "  Resource grp: $ResourceGroup"

$ContextExcludeDirs = @('node_modules','dist','build','.next','.parcel-cache','.git','.venv','__pycache__','.pytest_cache','.mypy_cache','.ruff_cache')
$ContextExcludeFiles = @('.env','npm-debug.log','yarn-error.log','pnpm-debug.log','*.pyc')

function Get-ContextHash {
    param([Parameter(Mandatory = $true)][string]$Path)

    $files = Get-ChildItem -Path $Path -Recurse -File -ErrorAction SilentlyContinue |
        Sort-Object FullName
    if (-not $files) { return $null }

    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $sb = New-Object System.Text.StringBuilder
        foreach ($f in $files) {
            $relative = $f.FullName.Substring($Path.Length).TrimStart('\','/').Replace('\','/')
            $hashHex = (Get-FileHash -Algorithm SHA256 -LiteralPath $f.FullName).Hash
            [void]$sb.Append("$relative|$hashHex|")
        }
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($sb.ToString())
        return ([BitConverter]::ToString($sha.ComputeHash($bytes)) -replace '-','').ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Test-AcrImageExists {
    param(
        [Parameter(Mandatory = $true)][string]$AcrName,
        [Parameter(Mandatory = $true)][string]$Image,
        [Parameter(Mandatory = $true)][string]$Tag
    )
    $tags = az acr repository show-tags --name $AcrName --repository $Image --output tsv --only-show-errors 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $tags) { return $false }
    return ($tags -split "`n" | ForEach-Object { $_.Trim() }) -contains $Tag
}

function Wait-ContainerAppReady {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ResourceGroupName,
        [string]$ExpectedImage = '',
        [int]$MaxAttempts = 40,
        [int]$DelaySeconds = 10
    )

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        $detailsJson = az containerapp show `
            --name $Name `
            --resource-group $ResourceGroupName `
            --query "{state:properties.provisioningState,image:properties.template.containers[0].image}" `
            --output json `
            --only-show-errors 2>$null

        $state = 'Unknown'
        $currentImage = ''
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($detailsJson)) {
            $details = $detailsJson | ConvertFrom-Json
            $state = $details.state
            $currentImage = $details.image
        }

        if ($state -eq 'Succeeded') {
            if ([string]::IsNullOrWhiteSpace($ExpectedImage) -or $currentImage -eq $ExpectedImage) {
                Write-Host "  [OK] $Name is ready."
                return
            }
            Write-Host "  [Wait] $Name state: Succeeded, image not updated yet ($attempt/$MaxAttempts)"
        } else {
            if ([string]::IsNullOrWhiteSpace($state)) { $state = 'Unknown' }
            Write-Host "  [Wait] $Name state: $state ($attempt/$MaxAttempts)"
        }

        if ($state -eq 'Failed') { throw "Container App '$Name' provisioning failed." }
        Start-Sleep -Seconds $DelaySeconds
    }

    throw "Container App '$Name' did not become ready after $($MaxAttempts * $DelaySeconds) seconds."
}

function Invoke-ContainerAppImageUpdate {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ResourceGroupName,
        [Parameter(Mandatory = $true)][string]$Image
    )

    az containerapp update `
        --name $Name `
        --resource-group $ResourceGroupName `
        --image $Image `
        --no-wait `
        --only-show-errors | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "az containerapp update failed for $Name" }
}

function Wait-AcrBuild {
    param(
        [Parameter(Mandatory = $true)][string]$AcrName,
        [Parameter(Mandatory = $true)][string]$RunId,
        [Parameter(Mandatory = $true)][string]$ImageName,
        [int]$MaxAttempts = 180,
        [int]$DelaySeconds = 10
    )

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        $status = az acr task show-run `
            --registry $AcrName `
            --run-id $RunId `
            --query "status" `
            --output tsv `
            --only-show-errors 2>$null

        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($status)) { $status = 'Unknown' }

        if ($status -eq 'Succeeded') {
            Write-Host "  [OK] ACR build $RunId for $ImageName succeeded."
            return
        }

        if (@('Failed', 'Canceled', 'Error', 'Timeout') -contains $status) {
            $errorMessage = az acr task show-run `
                --registry $AcrName `
                --run-id $RunId `
                --query "runErrorMessage" `
                --output tsv `
                --only-show-errors 2>$null
            throw "ACR build $RunId for $ImageName ended with status '$status'. $errorMessage"
        }

        Write-Host "  [Wait] ACR build $RunId for $ImageName status: $status ($attempt/$MaxAttempts)"
        Start-Sleep -Seconds $DelaySeconds
    }

    throw "ACR build $RunId for $ImageName did not finish after $($MaxAttempts * $DelaySeconds) seconds."
}

foreach ($svc in $BuildPlan) {
    $imgRef = "${AcrLoginServer}/$($svc.Image):$ImageTag"
    Write-Host ""
    Write-Host "[Stage] $($svc.Image)"
    $tempContext = Join-Path ([System.IO.Path]::GetTempPath()) "cps-acrbuild-$($svc.Image)-$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Path $tempContext -Force | Out-Null

    $robocopyArgs = @(
        $svc.Context,
        $tempContext,
        '/E','/NFL','/NDL','/NJH','/NJS','/NP',
        '/XD'
    ) + $ContextExcludeDirs + @('/XF') + $ContextExcludeFiles
    & robocopy @robocopyArgs | Out-Null
    $robocopyExitCode = $LASTEXITCODE
    if ($robocopyExitCode -ge 8) { throw "robocopy failed for $($svc.Image) with exit code $robocopyExitCode" }

    # Hash the staged context for reuse-detection.
    $contextHash = Get-ContextHash -Path $tempContext
    $hashEnvName = "LAST_BUILT_HASH_$(($svc.Image -replace '[^A-Za-z0-9]','_').ToUpperInvariant())"
    $tagEnvName  = "LAST_BUILT_TAG_$(($svc.Image -replace '[^A-Za-z0-9]','_').ToUpperInvariant())"
    $previousHash = (azd env get-value $hashEnvName 2>$null)
    $previousTag  = (azd env get-value $tagEnvName  2>$null)
    if ($previousHash -match '^ERROR:') { $previousHash = '' }
    if ($previousTag  -match '^ERROR:') { $previousTag  = '' }

    $skipBuild = $false
    if ($contextHash -and $previousHash -eq $contextHash -and $previousTag -and (Test-AcrImageExists -AcrName $AcrName -Image $svc.Image -Tag $previousTag)) {
        Write-Host "  [Skip] context unchanged (hash $($contextHash.Substring(0,12))); reusing $($svc.Image):$previousTag"
        $imgRef = "${AcrLoginServer}/$($svc.Image):$previousTag"
        $skipBuild = $true
    }

    $svc.ImageRef    = $imgRef
    $svc.TempContext = $tempContext
    $svc.ContextHash = $contextHash
    $svc.HashEnvName = $hashEnvName
    $svc.TagEnvName  = $tagEnvName
    $svc.SkipBuild   = $skipBuild
    $svc.RunId       = $null
}

# Phase 2: queue all ACR builds in parallel.
foreach ($svc in $BuildPlan) {
    if ($svc.SkipBuild) { continue }
    Write-Host ""
    Write-Host "[Build] Queueing ACR build: $($svc.Image):$ImageTag"
    Push-Location $svc.TempContext
    try {
        $buildOutput = az acr build `
            --registry $AcrName `
            --resource-group $ResourceGroup `
            --image "$($svc.Image):$ImageTag" `
            --file Dockerfile `
            --no-logs `
            --no-wait `
            . 2>&1
        if ($LASTEXITCODE -ne 0) { throw "az acr build failed for $($svc.Image): $buildOutput" }
        $buildText = $buildOutput | Out-String
        if ($buildText -notmatch 'Queued a build with ID:\s*([A-Za-z0-9_-]+)') {
            throw "Could not determine ACR build run id for $($svc.Image). Output: $buildText"
        }
        $svc.RunId = $Matches[1]
        Write-Host "  Queued: $($svc.RunId)"
    } finally {
        Pop-Location
    }
}

# Phase 3: wait for each build to finish, then deploy it. Builds run in
# parallel server-side; this loop just collects results in order. As soon
# as a build finishes we kick off the (non-blocking) container app update,
# then wait for the rollout below.
foreach ($svc in $BuildPlan) {
    if (-not $svc.SkipBuild) {
        Wait-AcrBuild -AcrName $AcrName -RunId $svc.RunId -ImageName $svc.Image
        # Persist hash + tag so the next deploy can short-circuit.
        if ($svc.ContextHash) {
            azd env set $svc.HashEnvName $svc.ContextHash | Out-Null
            azd env set $svc.TagEnvName  $ImageTag        | Out-Null
        }
    }
    Write-Host "[Deploy] $($svc.App) <- $($svc.ImageRef)"
    Invoke-ContainerAppImageUpdate -Name $svc.App -ResourceGroupName $ResourceGroup -Image $svc.ImageRef
}

# Phase 4: wait for all container apps to roll to the new image.
foreach ($svc in $BuildPlan) {
    Wait-ContainerAppReady -Name $svc.App -ResourceGroupName $ResourceGroup -ExpectedImage $svc.ImageRef
    if ($svc.TempContext -and (Test-Path $svc.TempContext)) {
        Remove-Item -Recurse -Force $svc.TempContext -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "[Build] All container images built and deployed."
Write-Host ""

Write-Host "[Search] Fetching container app info from azd environment..."

function Get-AzdEnvValueOptional {
    param([Parameter(Mandatory = $true)][string]$Name)

    $value = azd env get-value $Name 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($value) -or $value -match '^ERROR:') { return '' }
    return $value.Trim()
}

# Load values from azd env
$CONTAINER_CLAIMS_APP_FQDN = azd env get-value CONTAINER_CLAIMS_APP_FQDN
$CONTAINER_WEB_APP_FQDN = Get-AzdEnvValueOptional -Name CONTAINER_WEB_APP_FQDN

$CONTAINER_API_APP_NAME = azd env get-value CONTAINER_API_APP_NAME
$CONTAINER_API_APP_FQDN = azd env get-value CONTAINER_API_APP_FQDN

$CONTAINER_WORKFLOW_APP_NAME = azd env get-value CONTAINER_WORKFLOW_APP_NAME

# Get subscription and resource group (assuming same for both)
$SUBSCRIPTION_ID = azd env get-value AZURE_SUBSCRIPTION_ID
$RESOURCE_GROUP = azd env get-value AZURE_RESOURCE_GROUP

# Construct Azure Portal URLs
$API_APP_PORTAL_URL = "https://portal.azure.com/#resource/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.App/containerApps/$CONTAINER_API_APP_NAME"
$WORKFLOW_APP_PORTAL_URL = "https://portal.azure.com/#resource/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.App/containerApps/$CONTAINER_WORKFLOW_APP_NAME"

# Get the current script's directory
$ScriptDir = $PSScriptRoot

# Navigate from infra/scripts -> root -> src/api/data/data.sh
$DataScriptPath = Join-Path $ScriptDir "..\..\src\ContentProcessorAPI\samples\schemas"

# Resolve to an absolute path
$FullPath = Resolve-Path $DataScriptPath

# Output
Write-Host ""
Write-Host "[Info] Claims Demo App Endpoint: $CONTAINER_CLAIMS_APP_FQDN"

Write-Host ""
Write-Host "[Info] API App Details:"
Write-Host "  [OK] Name: $CONTAINER_API_APP_NAME"
Write-Host "  [URL] Endpoint: $CONTAINER_API_APP_FQDN"
Write-Host "  [Link] Portal URL: $API_APP_PORTAL_URL"

Write-Host ""
Write-Host "[Info] Workflow App Details:"
Write-Host "  [OK] Name: $CONTAINER_WORKFLOW_APP_NAME"
Write-Host "  [Link] Portal URL: $WORKFLOW_APP_PORTAL_URL"

function Add-SpaRedirectUris {
    param(
        [Parameter(Mandatory = $true)][string]$ClientId,
        [string[]]$HostNames = @()
    )

    if ([string]::IsNullOrWhiteSpace($ClientId) -or $ClientId -match '<.*>') {
        Write-Host ""
        Write-Host "[Auth] APP_WEB_CLIENT_ID is not set; skipping SPA redirect URI registration."
        return
    }

    $RedirectUris = @()
    foreach ($hostName in $HostNames) {
        if ([string]::IsNullOrWhiteSpace($hostName)) { continue }
        $origin = $hostName.Trim()
        if ($origin -match '^ERROR:' -or $origin -match '\s') { continue }
        if ($origin -notmatch '^https?://') { $origin = "https://$origin" }
        $origin = $origin.TrimEnd('/')
        $RedirectUris += $origin
        $RedirectUris += "$origin/"
    }

    $RedirectUris = @($RedirectUris | Sort-Object -Unique)
    if ($RedirectUris.Count -eq 0) { return }

    Write-Host ""
    Write-Host "[Auth] Registering SPA redirect URI(s) for app registration $ClientId..."
    foreach ($uri in $RedirectUris) { Write-Host "  $uri" }

    $tempFile = Join-Path ([System.IO.Path]::GetTempPath()) "cps-spa-redirects-$([guid]::NewGuid().ToString('N')).json"
    try {
        $appJson = az ad app show --id $ClientId -o json 2>&1
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($appJson)) {
            throw "Could not read app registration '$ClientId'. $appJson"
        }

        $app = $appJson | ConvertFrom-Json
        $existingUris = @()
        if ($app.spa -and $app.spa.redirectUris) { $existingUris = @($app.spa.redirectUris) }
        $mergedUris = @($existingUris + $RedirectUris | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Sort-Object -Unique)

        @{ spa = @{ redirectUris = $mergedUris } } | ConvertTo-Json -Depth 8 -Compress | Set-Content -LiteralPath $tempFile -Encoding utf8
        az rest `
            --method PATCH `
            --url "https://graph.microsoft.com/v1.0/applications/$($app.id)" `
            --headers "Content-Type=application/json" `
            --body "@$tempFile" `
            --only-show-errors | Out-Null

        if ($LASTEXITCODE -ne 0) { throw "Microsoft Graph patch failed." }
        Write-Host "  [OK] SPA redirect URIs are up to date."
    } catch {
        $details = "$_"
        if ($details -match 'TokenCreatedWithOutdatedPolicies|InteractionRequired|Continuous access evaluation') {
            $details = "$details Refresh Microsoft Graph auth with: az login --use-device-code --scope https://graph.microsoft.com//.default"
        }
        throw "Failed to update SPA app registration redirect URIs. Ensure the signed-in deployment identity owns the app registration or has Application Administrator/Cloud Application Administrator permissions. Details: $details"
    } finally {
        if (Test-Path $tempFile) { Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue }
    }
}

$AppWebClientId = ''
try { $AppWebClientId = Get-AzdEnvValueOptional -Name APP_WEB_CLIENT_ID } catch {}
$SpaRedirectHostNames = @($CONTAINER_WEB_APP_FQDN, $CONTAINER_CLAIMS_APP_FQDN) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
Add-SpaRedirectUris -ClientId $AppWebClientId -HostNames $SpaRedirectHostNames

Write-Host ""
Write-Host "[Package] Registering schemas and creating schema set..."
Write-Host "  [Wait] Waiting for API to be ready..."

# Postprov runs immediately after the API container app gets a new image,
# so the first /schemavault/ probe routinely hits a still-warming replica.
# We keep the per-attempt timeout short but extend the total budget to
# ~5 min so cold starts (image pull + EasyAuth init + Cosmos warm) don't
# silently skip schema registration. Also see the FailFast block below
# that escalates the previous quiet "Skipping..." into a hard exit.
$MaxRetries = 20
$RetryInterval = 15
$ApiBaseUrl = "https://$CONTAINER_API_APP_FQDN"
$ApiReady = $false

# Optional: acquire a bearer token for the API. If APP_API_SCOPE is set in
# the azd env (per docs/ConfigureAppAuthentication.md), the script tries to
# request a token via the signed-in az CLI principal. When EasyAuth is enabled
# on the API container app this is required; when EasyAuth is not yet
# configured the calls succeed without it.
$AuthHeaders = @{}
$AppApiScope = ''
try { $AppApiScope = azd env get-value APP_API_SCOPE 2>$null } catch {}
if ($AppApiScope -and $AppApiScope -notmatch '<.*>') {
    $TokenResource = $AppApiScope -replace '/user_impersonation$', ''
    Write-Host "  [Auth] Acquiring bearer token for $TokenResource ..."
    try {
        $TokenJson = az account get-access-token --resource $TokenResource -o json 2>&1
        $TokenExitCode = $LASTEXITCODE

        if ($TokenExitCode -ne 0 -and "$TokenJson" -match 'AADSTS65001' -and $TokenResource -match '^api://([^/]+)$') {
            $ApiAppIdForConsent = $Matches[1]
            $ScopeNameForConsent = 'user_impersonation'
            if ($AppApiScope -match '/([^/]+)$') { $ScopeNameForConsent = $Matches[1] }
            $AzureCliAppId = '04b07795-8ddb-461a-bbee-02f9e1bf7b46'

            Write-Host "  [Auth] Granting Microsoft Azure CLI consent to API scope '$ScopeNameForConsent'..."
            $AzureCliSp = az ad sp show --id $AzureCliAppId -o json 2>$null
            if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($AzureCliSp)) {
                az ad sp create --id $AzureCliAppId --only-show-errors | Out-Null
                if ($LASTEXITCODE -ne 0) { throw "Could not create Microsoft Azure CLI service principal for API consent." }
            }

            az ad app permission grant --id $AzureCliAppId --api $ApiAppIdForConsent --scope $ScopeNameForConsent --only-show-errors | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Could not grant Microsoft Azure CLI consent to API scope '$ScopeNameForConsent'." }

            $TokenJson = az account get-access-token --resource $TokenResource -o json 2>&1
            $TokenExitCode = $LASTEXITCODE
        }

        if ($TokenExitCode -eq 0 -and $TokenJson) {
            $Token = ($TokenJson | ConvertFrom-Json).accessToken
            if ($Token) {
                $AuthHeaders = @{ Authorization = "Bearer $Token" }
                Write-Host "  [Auth] Bearer token acquired."
            }
        } else {
            Write-Host "  [Auth] Could not acquire token (az returned non-zero); calls will be unauthenticated."
        }
    } catch {
        Write-Host "  [Auth] Token acquisition failed: $_"
    }
}

for ($i = 1; $i -le $MaxRetries; $i++) {
    try {
        $response = Invoke-WebRequest -Uri "$ApiBaseUrl/schemavault/" -Method GET -Headers $AuthHeaders -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            Write-Host "  [OK] API is ready."
            $ApiReady = $true
            break
        }
    } catch {
        # Ignore - API not ready yet
    }
    Write-Host "  Attempt $i/$MaxRetries - API not ready, retrying in ${RetryInterval}s..."
    Start-Sleep -Seconds $RetryInterval
}

if (-not $ApiReady) {
    # Hard-fail rather than continuing with a "Skipping..." warning.
    # Without the schemas + schema set the demo's first claim is broken
    # (the workflow has no analyzers to invoke), and the previous quiet-
    # skip behaviour meant the breakage only showed up minutes later in
    # the UI. Surface it now so `azd up` exits non-zero and the operator
    # immediately sees what happened.
    Write-Error ("API at {0} did not become ready after {1} attempts ({2}s total). " -f $ApiBaseUrl, $MaxRetries, ($MaxRetries * $RetryInterval) +
        "Schema registration cannot proceed. Re-run 'azd hooks run postprovision' once the API container app is ready, " +
        "or inspect the container app logs for the failing replica.")
    exit 1
} else {
    # ---------- Schema registration (no Python dependency) ----------
    $SchemaInfoFile = Join-Path $FullPath "schema_info.json"
    $Manifest = Get-Content $SchemaInfoFile -Raw | ConvertFrom-Json

    $SchemaVaultUrl   = "$ApiBaseUrl/schemavault/"
    $SchemaSetVaultUrl = "$ApiBaseUrl/schemasetvault/"

    # --- Step 1: Register schemas ---
    Write-Host ""
    Write-Host ("=" * 60)
    Write-Host "Step 1: Register schemas"
    Write-Host ("=" * 60)

    # Fetch existing schemas
    $ExistingSchemas = @()
    try {
        $ExistingSchemas = Invoke-RestMethod -Uri $SchemaVaultUrl -Method GET -Headers $AuthHeaders -TimeoutSec 30 -ErrorAction Stop
        Write-Host "Fetched $($ExistingSchemas.Count) existing schema(s)."
    } catch {
        Write-Host "Warning: Could not fetch existing schemas. Proceeding..."
    }

    $Registered = @{}  # ClassName -> schema Id

    foreach ($entry in $Manifest.schemas) {
        $ClassName   = $entry.ClassName
        $Description = $entry.Description
        $SchemaFile  = Join-Path $FullPath $entry.File

        Write-Host ""
        Write-Host "Processing schema: $ClassName"

        if (-not (Test-Path $SchemaFile)) {
            Write-Host "Error: Schema file '$SchemaFile' does not exist. Skipping..."
            continue
        }

        # Check if already registered
        $existing = $ExistingSchemas | Where-Object { $_.ClassName -eq $ClassName } | Select-Object -First 1
        if ($existing) {
            $schemaId = $existing.Id
            Write-Host "  Schema '$ClassName' already exists with ID: $schemaId"
            $Registered[$ClassName] = $schemaId
            continue
        }

        Write-Host "  Registering new schema '$ClassName' (JSON-native)..."

        try {
            $Envelope     = Get-Content $SchemaFile -Raw | ConvertFrom-Json
            $FieldSchema  = $Envelope.fieldSchema
            $BaseAnalyzer = if ($Envelope.baseAnalyzerId) { $Envelope.baseAnalyzerId } else { "prebuilt-document" }
            $Completion   = if ($Envelope.models -and $Envelope.models.completion) { $Envelope.models.completion } else { "gpt-4.1-mini" }
        } catch {
            Write-Host "  Failed to parse envelope '$SchemaFile'. Error: $_"
            continue
        }

        if (-not $FieldSchema -or -not $FieldSchema.fields) {
            Write-Host "  Envelope '$SchemaFile' is missing fieldSchema.fields - skipping."
            continue
        }

        $RequestBody = @{
            ClassName       = $ClassName
            Description     = $Description
            FieldSchema     = $FieldSchema
            BaseAnalyzerId  = $BaseAnalyzer
            CompletionModel = $Completion
        } | ConvertTo-Json -Depth 100 -Compress

        try {
            $resp = Invoke-RestMethod -Uri "$SchemaVaultUrl`json" -Method POST `
                -Headers $AuthHeaders `
                -ContentType "application/json" `
                -Body $RequestBody -TimeoutSec 60 -ErrorAction Stop
            $schemaId = $resp.Id
            Write-Host "  Successfully registered: $Description's Schema Id - $schemaId"
            $Registered[$ClassName] = $schemaId
        } catch {
            Write-Host "  Failed to register '$ClassName'. Error: $_"
        }
    }

    # --- Step 2: Create schema set ---
    Write-Host ""
    Write-Host ("=" * 60)
    Write-Host "Step 2: Create schema set"
    Write-Host ("=" * 60)

    $SetName = $Manifest.schemaset.Name
    $SetDesc = $Manifest.schemaset.Description

    $ExistingSets = @()
    try {
        $ExistingSets = Invoke-RestMethod -Uri $SchemaSetVaultUrl -Method GET -Headers $AuthHeaders -TimeoutSec 30 -ErrorAction Stop
        Write-Host "Fetched $($ExistingSets.Count) existing schema set(s)."
    } catch {
        Write-Host "Warning: Could not fetch existing schema sets. Proceeding..."
    }

    $SchemaSetId = $null
    $existingSet = $ExistingSets | Where-Object { $_.Name -eq $SetName } | Select-Object -First 1
    if ($existingSet) {
        $SchemaSetId = $existingSet.Id
        Write-Host "  Schema set '$SetName' already exists with ID: $SchemaSetId"
    } else {
        Write-Host "  Creating schema set '$SetName'..."
        try {
            $setResp = Invoke-RestMethod -Uri $SchemaSetVaultUrl -Method POST `
                -Headers $AuthHeaders `
                -ContentType "application/json" `
                -Body (@{ Name = $SetName; Description = $SetDesc } | ConvertTo-Json) `
                -TimeoutSec 30 -ErrorAction Stop
            $SchemaSetId = $setResp.Id
            Write-Host "  Created schema set '$SetName' with ID: $SchemaSetId"
        } catch {
            Write-Host "  Failed to create schema set. Error: $_"
        }
    }

    if (-not $SchemaSetId) {
        Write-Host "Error: Could not create or find schema set. Aborting step 3."
    } else {
        # --- Step 3: Add schemas to schema set ---
        Write-Host ""
        Write-Host ("=" * 60)
        Write-Host "Step 3: Add schemas to schema set"
        Write-Host ("=" * 60)

        $AlreadyInSet = @()
        try {
            $AlreadyInSet = Invoke-RestMethod -Uri "$SchemaSetVaultUrl$SchemaSetId/schemas" -Method GET -Headers $AuthHeaders -TimeoutSec 30 -ErrorAction Stop
        } catch { }
        $AlreadyInSetIds = $AlreadyInSet | ForEach-Object { $_.Id }

        foreach ($className in $Registered.Keys) {
            $schemaId = $Registered[$className]
            if ($AlreadyInSetIds -contains $schemaId) {
                Write-Host "  Schema '$className' ($schemaId) already in schema set - skipped"
                continue
            }

            try {
                Invoke-RestMethod -Uri "$SchemaSetVaultUrl$SchemaSetId/schemas" -Method POST `
                    -Headers $AuthHeaders `
                    -ContentType "application/json" `
                    -Body (@{ SchemaId = $schemaId } | ConvertTo-Json) `
                    -TimeoutSec 30 -ErrorAction Stop | Out-Null
                Write-Host "  Added '$className' ($schemaId) to schema set"
            } catch {
                Write-Host "  Failed to add '$className' to schema set. Error: $_"
            }
        }
    }

    Write-Host ""
    Write-Host ("=" * 60)
    Write-Host "Schema registration process completed."
    Write-Host "  Schemas registered: $($Registered.Count)"
    Write-Host ("=" * 60)
}

# ---------- AI Search policy index seed (Phase D) ----------
# Sends sample policy markdown to the API, which uses its managed identity to
# create the Search index and upload documents. This keeps one-command deploys
# working when Storage is private-networked and avoids Search admin keys.
$AiSearchName = $null
try { $AiSearchName = azd env get-value AI_SEARCH_NAME } catch {}

if ($AiSearchName) {
    Write-Host ""
    Write-Host ("=" * 60)
    Write-Host "AI Search: seeding policy index"
    Write-Host ("=" * 60)

    $IndexName = azd env get-value AI_SEARCH_INDEX_NAME
    # Claims-handling guidance corpus (advisory). Member policies are seeded
    # separately into a different index by the member-policies seed step.
    $PoliciesDir = Resolve-Path (Join-Path $ScriptDir "..\sample-policies\handling-guidance")

    $Documents = @(Get-ChildItem -Path $PoliciesDir -Filter *.md | ForEach-Object {
        @{
            source_filename = $_.Name
            section = [System.IO.Path]::GetFileNameWithoutExtension($_.Name)
            content = Get-Content $_.FullName -Raw
        }
    })
    $Payload = @{ index_name = $IndexName; documents = $Documents } | ConvertTo-Json -Depth 8
    $SeedUrl = "$ApiBaseUrl/claimsdemo/policy-index/seed"

    $MaxSeedRetries = 10
    for ($attempt = 1; $attempt -le $MaxSeedRetries; $attempt++) {
        try {
            Write-Host "  Seeding '$IndexName' through API managed identity (attempt $attempt/$MaxSeedRetries)..."
            $result = Invoke-RestMethod -Uri $SeedUrl -Method POST -Headers $AuthHeaders `
                -ContentType 'application/json' -Body $Payload -TimeoutSec 120 -ErrorAction Stop
            Write-Host "  [OK] AI Search policy index seeded with $($result.documents_uploaded) document(s)."
            break
        } catch {
            if ($attempt -eq $MaxSeedRetries) { throw }
            Write-Host "  [Wait] AI Search seeding not ready yet: $_"
            Start-Sleep -Seconds 20
        }
    }

    # ---------- Member auto-policy contracts (authoritative source) ---------- #
    # Reads infra/sample-policies/member-policies/_index.json (filterable
    # metadata) joined to the per-policy markdown body, then POSTs to the
    # member-policies seed endpoint. The recommendation agent retrieves
    # from this index by exact policy_number filter.
    $MemberIndexName = $null
    try { $MemberIndexName = azd env get-value MEMBER_POLICIES_INDEX_NAME } catch {}
    if ($MemberIndexName) {
        Write-Host ""
        Write-Host "AI Search: seeding member-policies index"

        $MemberDir = Resolve-Path (Join-Path $ScriptDir "..\sample-policies\member-policies")
        $MemberIndexFile = Join-Path $MemberDir "_index.json"
        if (-not (Test-Path $MemberIndexFile)) {
            Write-Host "  [Skip] No _index.json found at $MemberIndexFile."
        } else {
            $MemberMeta = Get-Content $MemberIndexFile -Raw | ConvertFrom-Json
            $MemberDocs = @()
            foreach ($entry in $MemberMeta.policies) {
                $mdPath = Join-Path $MemberDir $entry.source_filename
                if (-not (Test-Path $mdPath)) {
                    Write-Host "  [Warn] Missing markdown for $($entry.policy_number) at $mdPath; skipping."
                    continue
                }
                $vins = @()
                if ($entry.covered_vehicles) {
                    foreach ($v in $entry.covered_vehicles) { $vins += $v.vin }
                }
                $MemberDocs += @{
                    policy_number    = $entry.policy_number
                    source_filename  = $entry.source_filename
                    content          = Get-Content $mdPath -Raw
                    form_version     = [string]$entry.form_version
                    carrier          = [string]$entry.carrier
                    state            = [string]$entry.state
                    effective_date   = [string]$entry.effective_date
                    expiration_date  = [string]$entry.expiration_date
                    status           = [string]$entry.status
                    named_insureds   = @($entry.named_insureds)
                    excluded_drivers = @($entry.excluded_drivers)
                    vins             = $vins
                    endorsements     = @($entry.endorsements)
                }
            }

            if ($MemberDocs.Count -eq 0) {
                Write-Host "  [Skip] No member-policy documents to upload."
            } else {
                $MemberPayload = @{
                    index_name = $MemberIndexName
                    documents  = $MemberDocs
                } | ConvertTo-Json -Depth 10
                $MemberSeedUrl = "$ApiBaseUrl/claimsdemo/member-policies-index/seed"

                for ($attempt = 1; $attempt -le $MaxSeedRetries; $attempt++) {
                    try {
                        Write-Host "  Seeding '$MemberIndexName' through API managed identity (attempt $attempt/$MaxSeedRetries)..."
                        $result = Invoke-RestMethod -Uri $MemberSeedUrl -Method POST -Headers $AuthHeaders `
                            -ContentType 'application/json' -Body $MemberPayload -TimeoutSec 120 -ErrorAction Stop
                        Write-Host "  [OK] Member-policies index seeded with $($result.documents_uploaded) document(s)."
                        break
                    } catch {
                        if ($attempt -eq $MaxSeedRetries) { throw }
                        Write-Host "  [Wait] Member-policies seeding not ready yet: $_"
                        Start-Sleep -Seconds 20
                    }
                }
            }
        }
    }
}

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
if ($AiSearchName -and -not [string]::IsNullOrWhiteSpace($CONTAINER_API_APP_FQDN)) {
    Write-Host ""
    Write-Host ("=" * 60)
    Write-Host "AI Search: warming recommendation grounding (Foundry MI -> AI Search RBAC)"
    Write-Host ("=" * 60)

    $WarmupUrl = "$ApiBaseUrl/claimsdemo/warmup-grounding"
    $MaxWarmupRetries = 20
    $WarmupInterval = 30
    $WarmedUp = $false

    for ($attempt = 1; $attempt -le $MaxWarmupRetries; $attempt++) {
        try {
            Write-Host "  Warm-up attempt $attempt/$MaxWarmupRetries (timeout per attempt: 120s)..."
            $null = Invoke-RestMethod -Uri $WarmupUrl -Method POST -Headers $AuthHeaders `
                -ContentType 'application/json' -Body '{}' -TimeoutSec 120 -ErrorAction Stop
            Write-Host "  [OK] Recommendation grounding warmed."
            $WarmedUp = $true
            break
        } catch {
            if ($attempt -eq $MaxWarmupRetries) {
                Write-Host "  [Warn] Warm-up did not complete after $MaxWarmupRetries attempts: $_"
            } else {
                Write-Host "  [Wait] Grounding still propagating: $_"
                Start-Sleep -Seconds $WarmupInterval
            }
        }
    }

    if (-not $WarmedUp) {
        # Don't fail postprov here — Search RBAC sometimes needs >10 min and
        # the demo recovers naturally once it propagates. But surface the
        # state loudly so the operator knows the first recommendation may
        # 502 until Foundry MI -> AI Search propagation completes.
        Write-Warning ("Recommendation grounding warm-up did not succeed within {0}s. " -f ($MaxWarmupRetries * $WarmupInterval) +
            "The demo will still work, but the first recommendation may 502 until " +
            "the Foundry project managed identity finishes propagating to AI Search. " +
            "Re-run 'azd hooks run postprovision' or wait a few more minutes before demoing.")
    }
}
