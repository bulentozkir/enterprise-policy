# Deploy the ALZ custom audit initiatives to another Azure tenant

Deploys the `alz-global-custom-audit`, `alz-hub-custom-audit` and `alz-landingzone-custom-audit` initiatives and their 75 custom policy definitions (Global 23, Hub 12, LandingZone 40) to one management group with the Terraform CLI. It creates no policy assignments, role assignments or other resources.

## Assignment inputs

Policy and initiative parameters use **Portal pickers** (`metadata.strongType`) or **fixed-choice dropdowns** (`allowedValues`). Every true/false input is a `String` dropdown with choices `"true"` and `"false"`, defaulting to `"true"`; policy rules convert the choice to a Boolean with `bool()`. There are no Boolean text boxes, free-text scalar or JSON-object inputs. Required-tag controls R04/R05/R06 are the editable-array exception: each starts with `["owner", "costcenter", "environment"]`, which you can replace, add to, or shorten.

Conditional checks are enabled by default: `"true"` checks every matching resource in the assignment scope; `"false"` skips the check. For example, Global's `r26_enabled` controls both Windows VM and VM scale-set Hybrid Benefit checks, with no VM selection. Confirm licensing eligibility before assigning, and select `"false"` for ineligible scopes; use assignment exclusions or exemptions for exceptions. R26 and R27 check incompatible Windows license types, so disable the inapplicable check. Kubernetes warning, host-network allowance and privilege-escalation dropdowns also default to `"true"` as requested; L13 therefore allows host networking by default but still allows no host ports.

Resource-target lists are not exposed; use assignment exclusions/exemptions for exceptions. Resource pickers remain only for required destinations and approved peer networks. H07 checks each Public IP's own DDoS protection mode and accepts `Enabled` with or without a plan; it requires no plan selection. Inherited or unspecified protection is reported for separate verification, not assumed protected.

R18/R20/R21/R23/R24/R25/R31/R32/R34/R35/R36, H11/H20 and L49 were removed by request, including all four R25 and all three R32 variants. L49's hub-selection and remote-gateway inputs are removed, not left as free-text fields. Custom DNS addresses (H17), host-path allowances (L10), and UID/GID ranges (L11) remain excluded because no approved address/path/range catalog was supplied. The manifests retain all removal and coverage-gap reasons.

**Previous verified deployment:** on 2026-11-04, the preceding 84-definition revision and three initiatives were deployed to the requested Tenant Root Group and verified without drift. The unassigned previous Contoso package was retired, including the 13 policies removed in that revision. The current 75-definition source removes R24, all four R25 variants, R34, H11/H20 and L49, changes H07 and L14, and uses default-true dropdowns; it has not been deployed. No Azure resources were changed by these source updates.

**Breaking input change:** Azure does not allow removing existing policy-definition parameters or changing their types in place. Boolean assignment values must now be quoted strings, for example `{"r26_enabled": {"value": "false"}}`. Use fresh/versioned definitions and a separately reviewed migration; do not apply this package directly over an existing deployment. Removing deployed definitions also requires explicit migration review. Terraform's deletion/replacement protections remain enabled.

## Policy review corrections

- R05 reports missing or empty required tags with a guarded value expression; count variables are not used in field accessors.
- R09 accepts TLS versions above the selected minimum.
- H07 accepts per-Public-IP DDoS IP Protection without a mandatory DDoS plan.
- H10 requires a nonempty, Entra-only point-to-site authentication list.
- L14 is now "Azure Kubernetes Service Clusters should not use Local Authentication" and audits `disableLocalAccounts != true`. Entra integration alone does not pass. L15 remains unchanged, so these controls now overlap; L14 no longer independently audits Entra integration.
- L17 rejects empty authorized-range lists on public AKS APIs; approved CIDR validation remains out of scope.
- L26 reports public PostgreSQL access and incomplete private configuration while preserving VNet integration.
- L45 requires an actual nonzero SQL long-term retention duration; it does not claim to verify backup storage redundancy.
- R30 excludes the `master` database with `name != master`; the earlier `*/master` pattern could never match because the policy `name` field is the short resource name.
- H07 and L14 were renamed to `hub-h07-public-ip-ddos-protection-enabled` and `landingzone-l14-aks-local-authentication-disabled` so definition names match behavior.
- H04 and H21 no longer refer to removed target selections. H16, H19, L03, L04 and L05 are audit-first, so their names and descriptions no longer say they deny; L04 labels its next-hop dropdown as prohibited types. The three initiative descriptions now match the dropdown contract.
- H21 accepted IDPS modes default to Alert and Deny, so the Hub initiative has no required inputs.
- All field aliases and resource types in the 75 definitions were checked against live Azure provider metadata (no unknown entries), rules were re-compared with their public upstream sources, and `policy-lifecycle-report.json` was refreshed (59 public sources, none deprecated or retired). Azure Policy language acceptance of `bool()` expressions can only be confirmed by creating the definitions; documentation lists `bool()` as an allowed template function.

## Requirements

- Terraform 1.7 or later (before 2.0)
- Azure CLI
- Resource Policy Contributor (or Owner) on the target management group. Entra roles alone are not enough.

## Steps

1. Get the repository (or copy the whole folder) and open the `terraform` folder. The `Global`, `Hub`, `LandingZone` and `terraform` folders must stay together.

   ```
   git clone https://github.com/bulentozkir/enterprise-policy.git
   cd enterprise-policy/terraform
   ```

2. Sign in to the target tenant and select any subscription in it. The subscription is only used to sign in; everything is created at the management group.

   ```
   az login --tenant <TENANT_ID>
   az account set --subscription <SUBSCRIPTION_ID>
   ```

3. Find the management group name. Use the `Name` column, not the display name.

   ```
   az account management-group list --query "[].{Name:name, DisplayName:displayName}" -o table
   ```

4. Initialize and plan.

   On Windows, prefer the guarded script, which checks the requested user and isolates state by tenant and management group:

   ```powershell
   .\deploy.ps1 -TenantId <TENANT_ID> -SubscriptionId <SUBSCRIPTION_ID> -ManagementGroupName <MANAGEMENT_GROUP_NAME> -ExpectedUserPrincipalName <USER_UPN> -AcknowledgeCoverageGaps
   ```

   For the tenant root management group, use the tenant ID as `ManagementGroupName`. Add `-Apply` to the same command to plan, inspect and apply. The script never creates policy assignments.

   Alternatively, initialize an explicitly target-specific backend before using Terraform directly:

   ```
   terraform init -backend-config="path=<TARGET_SPECIFIC_STATE_PATH>"
   terraform plan -out="deploy.tfplan" -var="tenant_id=<TENANT_ID>" -var="subscription_id=<SUBSCRIPTION_ID>" -var="management_group_name=<MANAGEMENT_GROUP_NAME>" -var="acknowledge_coverage_gaps=true"
   ```

   `acknowledge_coverage_gaps=true` confirms you accept all documented gaps: the fourteen rows removed by request, H17/L10/L11, Key Vault certificate expiry, and Service Health billing updates (see each set's manifest and `terraform/catalog.json`).

   For a fresh target, the plan must be additions only: `Plan: 79 to add, 0 to change, 0 to destroy.` (75 definitions, 3 initiatives and 1 internal tracking resource).

5. Apply.

   ```
   terraform apply deploy.tfplan
   ```
