ALZ CUSTOM AUDIT SOURCE PACKAGES

The Global, Hub and LandingZone folders cover the 91 recommendation rows authored
for the three-sheet workbook. These files are source definitions, not assignments.
Some recommendation rows require more than one resource-specific policy.

CONTENTS OF EACH SET
  policies\                 Custom policy definitions: {name, properties}.
  initiative.json           Initiative definition; custom IDs target management group contoso.
  initiative.template.json  Management-group ARM template defining policies/initiative.
  manifest.json             Workbook-row mapping, upstream provenance and limitations.
  required-inputs.json      Organization-specific parameters that have no default.
  assignment.parameter-defaults.json  Defaults only, NOT a complete assignment input.

SCOPE AND SAFETY
The requested definition location is the ALZ intermediate root contoso. Create definitions where the
assignment scopes can reference them. Global assignments are inherited by Hub and
LandingZone. Child Audit does not override an inherited Deny. Hub Connectivity,
Management and Identity controls have different target scopes; use their required
target inputs or scoped assignments, not a blanket effect change.

Default effects are Audit or AuditIfNotExists. Policies contain no governed-resource
deployment, modification, append, role grant or remediation instructions. The ARM
templates define policy resources only. The 97 Custom definitions (Global 39, Hub 15, LandingZone 43) and three
initiatives are defined for contoso; no assignments or workload resources were created. Azure holds this exact
revision (deployed 2026-11-03): 97 definitions, three initiatives, no differences from the package.
Azure assigns Custom policyType when a definition is created. Standalone source
files show Custom for clarity; request templates omit this read-only property.

AuditIfNotExists means read-only related-resource configuration checking, not literal
Audit. It cannot simply be changed to Deny. Audit/Deny members must be piloted
individually before future Deny. Configuration checks do not prove telemetry arrival,
alert delivery, backup success, restores, licensing entitlement or effective traffic.

VERSION FLEXIBILITY
Policy applicability contains no OS release lists, Marketplace image offers/SKUs,
image-version comparisons, distribution release lists or request-API-version gates.
Periodic assessment uses resource type and Windows/Linux OS-family fields only;
there is no supported-image comparison profile to maintain as new releases arrive.
OS-family matching does not certify Update Manager support for every appliance,
custom image or client OS. Record approved unsupported/service-managed exceptions
explicitly through excludedResourceIds, not OS release filters.
Kubernetes ConstraintTemplates are embedded as Base64Encoded content with readable
copies in LandingZone\templates. No external version-pinned implementation URLs or
template-URL assignment inputs are used. Structural template API versions remain.
Kubernetes.Data selects clusters by a required existing tag name/value because that
mode does not support ARM id field filters. Untagged clusters are not evaluated.
Required API/schema/content versions remain structural protocol information.
Security thresholds such as minimum TLS are parameters with safe defaults; flexibility
does not mean all protocol versions are compliant.

KEY VAULT COVERAGE LIMITATION
The unsupported Microsoft.KeyVault.Data clones have been removed entirely.
Fresh All-mode custom rules cover approved ARM-managed key/secret expiry metadata
and ARM key rotation configuration, using real management-plane aliases. These are
NOT equivalent to vault-wide data-plane inventory and do not guarantee coverage of
objects or versions written only through the Key Vault data plane.
R17 certificate-expiry auditing has no equivalent supported custom management-plane
implementation and is explicitly recorded as a coverage gap in Global\manifest.json.
No fake compliance tag, unsupported mode, or built-in reference replaces it.
See https://learn.microsoft.com/azure/governance/policy/concepts/definition-structure-basics

OFFLINE USE
From this directory:
  python validate.py

Copy the default parameters and supply every parameter listed in required-inputs.json
using the standard {"parameterName": {"value": ...}} shape. Keep effects at Audit or
AuditIfNotExists for the initial rollout. No resource IDs or licensing eligibility
were guessed. Run, substituting your actual definition-location MG name and paths:
  python render.py Global --management-group contoso --parameters YOUR_INPUTS.json --output RENDERED_DIRECTORY

The renderer checks required types/allowed values and materializes concrete custom
definition IDs. It also checks Object parameter schemas, including nonempty scope
selections. It uses Python's jsonschema package (already
present in the authoring environment). It makes no Azure calls or assignments.

ADOPTION
Review each manifest limitation, source derivative, required parameter and target
scope. In particular, SQL Hybrid Benefit checks are conditional on independently
verified eligibility and exclude centrally managed licensing scopes. Private access,
paid telemetry, Premium firewall and backup profiles are conditional design choices.
Do not configure AKS-managed VMSS resources through unsupported Compute interfaces.

Local validation checks JSON/property schemas, references, parameter bindings,
default effects and catalog-row coverage. It is not Azure service-side policy
validation or a compliance evaluation. Before adoption, validate/import at an isolated
ALZ test management group, test compliant/noncompliant fixtures and supported service
APIs, and pilot assignment scope. The current revision's definitions and initiatives
were accepted by Azure with live member counts matching source and no Terraform
changes (see verification-report.json).
No assignments or assigned-resource compliance evaluations have been performed.

UPSTREAM SOURCES AND LICENSES
Sources are recorded per definition in manifest.json. Source definitions came from
Microsoft Azure policy, ALZ, Azure community-policy and AMBA public repositories,
discovered through the four requested catalogs. Their MIT notices are in LICENSES.txt.
The current upstream lifecycle inspection is in policy-lifecycle-report.json.
No retired/deprecated source definitions are included. Active policies governing
retired resource types are not themselves retired and remain in the catalog.
