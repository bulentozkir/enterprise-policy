[CmdletBinding()]
param(
    [switch]$Apply,
    [switch]$AcknowledgeCoverageGaps
)

$ErrorActionPreference = 'Stop'
$tenant = 'd24284e3-1ea5-4285-9b96-4d53f671284b'
$subscription = 'a0fdc749-441a-43a5-8297-29192ed42f79'
$scope = '/providers/Microsoft.Management/managementGroups/contoso'

function Invoke-Native {
    param(
        [Parameter(Mandatory)][string]$Command,
        [Parameter(Mandatory)][string[]]$Arguments
    )
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE."
    }
}

$catalog = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'catalog.json') -Raw | ConvertFrom-Json
$missing = @(
    foreach ($set in 'Global', 'Hub', 'LandingZone') {
        foreach ($row in $catalog.sets.$set.missing_rows) { "$set/$row" }
    }
)
if ($missing.Count -gt 0) {
    throw "Source catalog is incomplete; no Azure changes will be made. Missing: $($missing -join ', ')."
}
$coverageGaps = @(
    foreach ($set in 'Global', 'Hub', 'LandingZone') { $catalog.sets.$set.coverage_gaps }
)
if ($coverageGaps.Count -gt 0 -and -not $AcknowledgeCoverageGaps) {
    throw 'Review the documented Key Vault ARM-only coverage and certificate-expiry omission; explicitly acknowledge these limitations.'
}

$accountJson = & az account show --subscription $subscription --output json
if ($LASTEXITCODE -ne 0) { throw 'Azure CLI authentication is required for the specified tenant.' }
$account = $accountJson | ConvertFrom-Json
if ($account.tenantId -ne $tenant) { throw 'The provider subscription belongs to a different tenant.' }

$authenticationJson = & az account get-access-token --subscription $subscription --resource 'https://management.azure.com/' --output json
if ($LASTEXITCODE -ne 0) { throw 'Unable to acquire the existing Azure CLI session for the target tenant.' }
$authentication = $authenticationJson | ConvertFrom-Json
$payload = $authentication.accessToken.Split('.')[1].Replace('-', '+').Replace('_', '/')
$payload = $payload.PadRight($payload.Length + ((4 - $payload.Length % 4) % 4), '=')
$claims = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)) | ConvertFrom-Json
if ($claims.tid -ne $tenant -or [string]::IsNullOrWhiteSpace($claims.oid)) {
    throw 'The acquired ARM session does not match the target tenant or has no principal identity.'
}
$principalObjectId = $claims.oid
try {
    $permissions = Invoke-RestMethod -Method Get `
        -Uri "https://management.azure.com$scope/providers/Microsoft.Authorization/permissions?api-version=2022-04-01" `
        -Headers @{ Authorization = "Bearer $($authentication.accessToken)" }
} finally {
    $authenticationJson = $null
    $authentication = $null
    $payload = $null
    $claims = $null
}
if ($permissions.nextLink) {
    throw 'Effective permissions are paged; verify the complete permission set before proceeding.'
}
foreach ($required in @(
    'Microsoft.Authorization/policyDefinitions/write',
    'Microsoft.Authorization/policySetDefinitions/write'
)) {
    $permitted = $false
    foreach ($entry in $permissions.value) {
        $allowed = @($entry.actions | Where-Object { $required -like $_ }).Count -gt 0
        $excluded = @($entry.notActions | Where-Object { $required -like $_ }).Count -gt 0
        if ($allowed -and -not $excluded) { $permitted = $true }
    }
    if (-not $permitted) { throw "Missing $required at $scope. No elevation or role changes will be attempted." }
}

# Keep Terraform state/provider files out of the OneDrive-synced source directory.
$runtime = Join-Path $env:LOCALAPPDATA "MicrosoftScout\Terraform\ALZ-$tenant"
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$oldData = $env:TF_DATA_DIR
$env:TF_DATA_DIR = Join-Path $runtime 'data'
$terraformDirectory = "-chdir=$PSScriptRoot"
$planPath = Join-Path $runtime 'definitions.tfplan'
try {
    Invoke-Native -Command terraform -Arguments @($terraformDirectory, 'init', '-input=false', "-backend-config=path=$(Join-Path $runtime 'terraform.tfstate')")
    Invoke-Native -Command terraform -Arguments @($terraformDirectory, 'validate')
    Invoke-Native -Command terraform -Arguments @(
        $terraformDirectory, 'plan', '-input=false', "-out=$planPath",
        "-var=acknowledge_coverage_gaps=$($AcknowledgeCoverageGaps.IsPresent.ToString().ToLowerInvariant())",
        "-var=expected_principal_object_id=$principalObjectId"
    )
    $planJson = & terraform $terraformDirectory show -json $planPath
    if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect the saved Terraform plan.' }
    $plan = $planJson | ConvertFrom-Json
    foreach ($change in $plan.resource_changes) {
        $actions = @($change.change.actions)
        if ('delete' -in $actions) { throw "Refusing a plan containing deletion: $($change.address)" }
        if ($change.mode -eq 'managed' -and @($actions | Where-Object { $_ -ne 'no-op' }).Count -gt 0) {
            if ($change.type -notin @('azurerm_policy_definition', 'azurerm_management_group_policy_set_definition', 'terraform_data')) {
                throw "Unexpected resource type in plan: $($change.type)"
            }
        }
    }
    if ($Apply) {
        Invoke-Native -Command terraform -Arguments @($terraformDirectory, 'apply', '-input=false', '-auto-approve', $planPath)
        Invoke-Native -Command terraform -Arguments @($terraformDirectory, 'output')
    } else {
        Write-Output "Plan saved to $planPath. Use -Apply to create only the reviewed definitions and initiatives."
    }
} finally {
    $env:TF_DATA_DIR = $oldData
}
