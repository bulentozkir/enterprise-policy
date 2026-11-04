import re


PICKER_TYPES = {"location", "resourceTypes", "storageSkus", "vmSKUs", "existingResourceGroups"}
RESOURCE_TYPE = re.compile(r"[A-Za-z][A-Za-z0-9.]+(?:/[A-Za-z][A-Za-z0-9]*)+")


def valid_type(value, kind):
    return {
        "String": isinstance(value, str),
        "DateTime": isinstance(value, str),
        "Array": isinstance(value, list),
        "Object": isinstance(value, dict),
        "Boolean": isinstance(value, bool),
        "Integer": isinstance(value, int) and not isinstance(value, bool),
        "Float": isinstance(value, (int, float)) and not isinstance(value, bool),
    }.get(kind, False)


def editable_array(spec):
    defaults = spec.get("defaultValue")
    return (
        spec.get("type") == "Array"
        and not spec.get("metadata", {}).get("strongType")
        and "allowedValues" not in spec
        and isinstance(defaults, list)
        and len(defaults) == 3
        and all(isinstance(item, str) and item.strip() for item in defaults)
    )


def validate_parameter_value(name, spec, value):
    kind = spec["type"]
    if not valid_type(value, kind):
        raise ValueError(f"{name}: expected {kind}, got {type(value).__name__}")
    values = value if kind == "Array" else [value]
    if "allowedValues" in spec:
        if not all(
            any(type(item) is type(allowed) and item == allowed for allowed in spec["allowedValues"])
            for item in values
        ):
            raise ValueError(f"{name}: value is not one of {spec['allowedValues']!r}")
    if spec.get("metadata", {}).get("strongType") or editable_array(spec):
        if any(not isinstance(item, str) or not item.strip() for item in values):
            raise ValueError(f"{name}: values must be nonempty strings")
    if kind == "Array" and not value and ("defaultValue" not in spec or editable_array(spec)):
        raise ValueError(f"{name}: provide at least one value")


def validate_parameter_spec(name, spec):
    kind = spec.get("type")
    if kind == "Boolean":
        raise ValueError(f"{name}: use a String true/false dropdown with defaultValue 'true', not a Boolean text input")
    if kind not in {"String", "Array", "Integer", "Float", "DateTime"} or "schema" in spec:
        raise ValueError(
            f"{name}: only Portal pickers, fixed-choice dropdowns and editable arrays with three defaults are supported"
        )
    picker = spec.get("metadata", {}).get("strongType")
    if picker is not None:
        if (
            kind not in {"String", "Array"}
            or not isinstance(picker, str)
            or not (picker in PICKER_TYPES or RESOURCE_TYPE.fullmatch(picker))
        ):
            raise ValueError(f"{name}: unsupported Portal picker {picker!r}")
    allowed = spec.get("allowedValues")
    if allowed is not None:
        if not isinstance(allowed, list) or not allowed:
            raise ValueError(f"{name}: dropdowns must have a nonempty allowedValues list")
        if kind == "Array":
            valid_choices = all(type(item) in {str, int, float, bool} for item in allowed)
        else:
            valid_choices = all(valid_type(item, kind) for item in allowed)
        if not valid_choices:
            raise ValueError(f"{name}: dropdown choices do not match {kind}")
        if kind == "String" and set(allowed) <= {"true", "false"}:
            if allowed != ["true", "false"] or spec.get("defaultValue") != "true":
                raise ValueError(f"{name}: true/false dropdowns require both choices and defaultValue 'true'")
    if picker is None and allowed is None and not editable_array(spec):
        raise ValueError(
            f"{name}: a Portal picker, fixed dropdown or editable array with three default strings is required"
        )
    if "defaultValue" in spec:
        validate_parameter_value(name, spec, spec["defaultValue"])
