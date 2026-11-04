import argparse
import json
from pathlib import Path
import re
import sys

from policy_inputs import valid_type, validate_parameter_spec, validate_parameter_value


ROOT = Path(__file__).parent


def materialize(set_name, management_group, supplied):
    folder = ROOT / set_name
    initiative = json.loads((folder / "initiative.json").read_text(encoding="utf-8"))
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    definitions = initiative["properties"]["parameters"]
    unknown = set(supplied) - set(definitions)
    if unknown:
        raise ValueError("Unknown initiative parameters: " + ", ".join(sorted(unknown)))
    params = {}
    missing = []
    for name, spec in definitions.items():
        validate_parameter_spec(name, spec)
        if name in supplied:
            if not isinstance(supplied[name], dict) or set(supplied[name]) != {"value"}:
                raise ValueError(f"{name}: expected an object containing only 'value'")
            value = supplied[name]["value"]
        elif "defaultValue" in spec:
            value = spec["defaultValue"]
        else:
            missing.append(name)
            continue
        validate_parameter_value(name, spec, value)
        params[name] = {"value": value}
    if missing:
        raise ValueError(
            "Required organizational inputs were not supplied:\n  " + "\n  ".join(missing)
            + "\nSee " + str(folder / "required-inputs.json")
        )
    expected_names = {
        item["name"] for item in manifest["policies"] if item["publishable"]
    }
    for member in initiative["properties"]["policyDefinitions"]:
        name = member["policyDefinitionReferenceId"]
        if name not in expected_names:
            raise ValueError(f"Unknown member {name}")
        member["policyDefinitionId"] = (
            f"/providers/Microsoft.Management/managementGroups/{management_group}"
            f"/providers/Microsoft.Authorization/policyDefinitions/{name}"
        )
    return initiative, params


def main():
    parser = argparse.ArgumentParser(
        description="Materialize local initiative IDs and validated assignment parameters. No Azure calls."
    )
    parser.add_argument("set", choices=["Global", "Hub", "LandingZone"])
    parser.add_argument("--management-group", required=True, help="Definition-location MG name, not assignment scope.")
    parser.add_argument("--parameters", type=Path, help="JSON with a 'parameters' map, or a parameter-name map.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.()-]{1,90}", args.management_group):
        parser.error("Provide an actual management-group name, not a path or placeholder.")
    supplied = {}
    if args.parameters:
        supplied = json.loads(args.parameters.read_text(encoding="utf-8-sig"))
        if not isinstance(supplied, dict):
            parser.error("The parameters input must be an object.")
        supplied = supplied.get("parameters", supplied)
        if not isinstance(supplied, dict):
            parser.error("The parameters input must be an object.")
    try:
        initiative, params = materialize(args.set, args.management_group, supplied)
    except ValueError as error:
        parser.exit(2, str(error) + "\n")
    args.output.mkdir(parents=True, exist_ok=True)
    for name, data in [
        ("initiative.json", initiative),
        ("assignment.parameters.json", {"parameters": params}),
    ]:
        target = args.output / name
        if target.exists():
            parser.exit(2, f"Refusing to overwrite {target}\n")
        target.write_text(json.dumps(data, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(f"Rendered {len(initiative['properties']['policyDefinitions'])} custom policy references.")
    print("No Azure resources, definitions, assignments or permissions were changed.")


if __name__ == "__main__":
    main()
