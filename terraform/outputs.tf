output "management_group_id" {
  value = local.management_group_id
}

output "initiative_ids" {
  value = {
    for set_name, initiative in azurerm_management_group_policy_set_definition.initiative :
    set_name => initiative.id
  }
}

output "custom_policy_count" {
  value = length(azurerm_policy_definition.custom)
}

output "portal_url" {
  value = "https://portal.azure.com/#view/Microsoft_Azure_Policy/PolicyMenuBlade/~/Definitions"
}
