# Deploy the ALZ custom audit initiatives to another Azure tenant

Deploys the `alz-global-custom-audit`, `alz-hub-custom-audit` and `alz-landingzone-custom-audit` initiatives and their 97 custom policy definitions to one management group with the Terraform CLI. It creates no policy assignments, role assignments or other resources.

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

   ```
   terraform init
   terraform plan -out="deploy.tfplan" -var="tenant_id=<TENANT_ID>" -var="subscription_id=<SUBSCRIPTION_ID>" -var="management_group_name=<MANAGEMENT_GROUP_NAME>" -var="acknowledge_coverage_gaps=true"
   ```

   `acknowledge_coverage_gaps=true` confirms you accept the two controls that cannot be audited with a custom policy: Key Vault certificate expiry and Service Health billing updates (see `Global/manifest.json`).

   The plan must be additions only: `Plan: 101 to add, 0 to change, 0 to destroy.` (97 definitions, 3 initiatives and 1 internal tracking resource).

5. Apply.

   ```
   terraform apply deploy.tfplan
   ```
