$ErrorActionPreference = 'Stop'
$deployScript = Join-Path (Split-Path $PSScriptRoot -Parent) 'terraform\deploy.ps1'
$tenant = '11111111-1111-1111-1111-111111111111'
$subscription = '22222222-2222-2222-2222-222222222222'
$previousSubscription = '33333333-3333-3333-3333-333333333333'
$scope = "/providers/Microsoft.Management/managementGroups/$tenant"
$testDirectory = Join-Path ([IO.Path]::GetTempPath()) "policy-deploy-tests-$([guid]::NewGuid())"
New-Item -ItemType Directory -Path $testDirectory | Out-Null
$originalLocalAppData = $env:LOCALAPPDATA
$originalData = $env:TF_DATA_DIR
$global:deploymentFixture = @{
    tenant = $tenant
    subscription = $subscription
    previousSubscription = $previousSubscription
    scope = $scope
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function az {
    $global:LASTEXITCODE = 0
    $fixture = $global:deploymentFixture
    switch ("$($args[0])/$($args[1])") {
        'account/show' {
            $id = if ('--subscription' -in $args) { $fixture.subscription } else { $fixture.activeSubscription }
            $accountTenant = if ($fixture.scenario -eq 'wrong-tenant') { $fixture.previousSubscription } else { $fixture.tenant }
            $user = if ($fixture.scenario -eq 'wrong-user') { 'other@example.invalid' } else { 'admin@example.invalid' }
            @{ id = $id; tenantId = $accountTenant; state = 'Enabled'; user = @{ type = 'user'; name = $user } } |
                ConvertTo-Json -Depth 5 -Compress
        }
        'account/management-group' {
            $id = if ($fixture.scenario -eq 'wrong-group') { "$($fixture.scope)-other" } else { $fixture.scope }
            @{ id = $id } | ConvertTo-Json -Compress
        }
        'account/get-access-token' {
            $claims = @{ tid = $fixture.tenant; oid = '44444444-4444-4444-4444-444444444444' } | ConvertTo-Json -Compress
            $payload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($claims)).TrimEnd('=').Replace('+', '-').Replace('/', '_')
            @{ accessToken = "fixture.$payload.fixture" } | ConvertTo-Json -Compress
        }
        'account/set' {
            $fixture.activeSubscription = $args[3]
        }
        'rest/--method' {
            Assert-True (($args -join ' ').Contains("$($fixture.scope)/providers/Microsoft.Authorization/permissions?")) 'Permissions checked at the wrong scope.'
            $actions = if ($fixture.scenario -eq 'denied') { @('*/read') } else { @('*') }
            $result = @{ value = @(@{ actions = $actions; notActions = @() }) }
            if ($fixture.scenario -eq 'paged') { $result.nextLink = 'https://management.azure.com/next' }
            $result | ConvertTo-Json -Depth 5 -Compress
        }
        default { throw "Unexpected az command in deployment test: $($args -join ' ')" }
    }
}

function terraform {
    $global:LASTEXITCODE = 0
    $fixture = $global:deploymentFixture
    switch ($args[1]) {
        'init' {
            $fixture.backendArgument = @($args | Where-Object { $_ -like '-backend-config=*' })[0]
            Assert-True ($env:TF_DATA_DIR.Contains("ALZ-$($fixture.tenant)-$($fixture.tenant)")) 'Provider data is not isolated by target scope.'
        }
        'validate' {}
        'plan' {
            Assert-True ("-var=management_group_name=$($fixture.tenant)" -in $args) 'Plan has the wrong management-group target.'
        }
        'show' {
            $actions = switch ($fixture.scenario) {
                'delete' { @('delete') }
                'replace' { @('delete', 'create') }
                default { @('create') }
            }
            $type = if ($fixture.scenario -eq 'wrong-managed-type') { 'azurerm_resource_group' } else { 'azapi_resource' }
            $armType = if ($fixture.scenario -eq 'wrong-arm-type') { 'Microsoft.Authorization/policyAssignments@2026-07-01' } else { 'Microsoft.Authorization/policyDefinitions@2026-07-01' }
            $parent = if ($fixture.scenario -eq 'wrong-scope') { "$($fixture.scope)-other" } else { $fixture.scope }
            @{ resource_changes = @(@{
                address = 'azapi_resource.custom["fixture"]'
                mode = 'managed'
                type = $type
                change = @{ actions = $actions; after = @{ type = $armType; parent_id = $parent } }
            }) } | ConvertTo-Json -Depth 8 -Compress
        }
        'apply' { $fixture.applyCount++ }
        'output' {}
        default { throw "Unexpected terraform command in deployment test: $($args -join ' ')" }
    }
}

try {
    $env:LOCALAPPDATA = $testDirectory
    foreach ($case in @(
        @{ name = 'safe-root-plan'; error = $null },
        @{ name = 'wrong-user'; error = 'requested user' },
        @{ name = 'wrong-tenant'; error = 'different tenant' },
        @{ name = 'wrong-group'; error = 'different management-group scope' },
        @{ name = 'denied'; error = 'Missing Microsoft.Authorization/policyDefinitions/write' },
        @{ name = 'paged'; error = 'permissions are paged' },
        @{ name = 'wrong-managed-type'; error = 'Unexpected resource type' },
        @{ name = 'wrong-arm-type'; error = 'Unexpected Azure resource or scope' },
        @{ name = 'wrong-scope'; error = 'Unexpected Azure resource or scope' },
        @{ name = 'delete'; error = 'plan containing deletion' },
        @{ name = 'replace'; error = 'plan containing deletion' }
    )) {
        $global:deploymentFixture.scenario = $case.name
        $global:deploymentFixture.activeSubscription = $previousSubscription
        $global:deploymentFixture.applyCount = 0
        $global:deploymentFixture.backendArgument = $null
        $caught = $null
        $caughtRecord = $null
        try {
            & $deployScript -TenantId $tenant -SubscriptionId $subscription -ManagementGroupName $tenant `
                -ExpectedUserPrincipalName 'admin@example.invalid' -AcknowledgeCoverageGaps -Apply | Out-Null
        } catch {
            $caught = $_.Exception.Message
            $caughtRecord = $_
        }
        if ($null -eq $case.error) {
            Assert-True ($null -eq $caught) "Safe deployment failed: $caught`n$($caughtRecord.ScriptStackTrace)"
            Assert-True ($global:deploymentFixture.applyCount -eq 1) 'Safe plan was not applied exactly once.'
            Assert-True ($global:deploymentFixture.backendArgument.Contains("ALZ-$tenant-$tenant")) 'Backend state is not isolated by management group.'
        } else {
            Assert-True ($null -ne $caught -and $caught.Contains($case.error)) "Expected '$($case.error)', received '$caught'."
            Assert-True ($global:deploymentFixture.applyCount -eq 0) 'Unsafe plan reached apply.'
        }
        Assert-True ($global:deploymentFixture.activeSubscription -eq $previousSubscription) 'CLI subscription was not restored.'
        Assert-True ($env:TF_DATA_DIR -eq $originalData) 'Terraform data directory was not restored.'
        Write-Output "PASS $($case.name)"
    }
} finally {
    $env:LOCALAPPDATA = $originalLocalAppData
    $env:TF_DATA_DIR = $originalData
    Remove-Item -LiteralPath $testDirectory -Recurse -Force
    Remove-Variable -Name deploymentFixture -Scope Global
}
