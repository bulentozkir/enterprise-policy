output "management_group_id" {
  value = local.management_group_id
}

output "initiative_ids" {
  value = {
    for set_name, initiative in azapi_resource.initiative :
    set_name => initiative.id
  }
}

output "custom_policy_count" {
  value = length(azapi_resource.custom)
}

output "portal_url" {
  value = "https://portal.azure.com/#view/Microsoft_Azure_Policy/PolicyMenuBlade/~/Definitions"
}
