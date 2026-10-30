#!/usr/bin/env python3
"""Offline parameter validation, not CAD geometry or manufacturing certification.

Python 3.10+, standard library only. See references/parameter-format.md.
Exit 0: no errors (warnings allowed); exit 1: invalid input or I/O error.
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

LENGTH_UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}
ALIASES = {"millimeter": "mm", "millimetre": "mm", "inch": "in"}
KINDS = {"length", "diameter", "wall", "radius", "count", "angle", "offset",
         "coordinate", "clearance", "scalar"}
POSITIVE = {"length", "diameter", "wall", "radius"}
FEATURES = {"sketch", "extrude", "hole", "cut", "revolve", "pattern", "fillet",
            "chamfer", "shell", "sweep", "loft", "combine", "offset", "parameter"}
WALL_START_MM = {"FDM": 1.2, "SLA": 0.8, "DLP": 0.8}


def unit_name(value):
    return ALIASES.get(value.strip().lower(), value.strip().lower()) if isinstance(value, str) else None


def finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def infer_parameter(key):
    """Conservative legacy shorthand; tokens, not arbitrary substring matches."""
    parts = key.lower().split("_")
    suffix = parts[-1]
    unit = suffix if suffix in {*LENGTH_UNITS, "deg", "rad"} else None
    tokens = set(parts[:-1] if unit else parts)
    if "count" in tokens:
        return "count", unit
    if tokens & {"angle", "draft", "taper"} or unit in {"deg", "rad"}:
        return "angle", unit
    if tokens & {"x", "y", "z", "coordinate", "position", "center"}:
        return "coordinate", unit
    if "offset" in tokens:
        return "offset", unit
    if tokens & {"clearance", "gap"}:
        return "clearance", unit
    if tokens & {"dia", "diam", "diameter", "bore"}:
        return "diameter", unit
    if tokens & {"wall", "thickness"}:
        return "wall", unit
    if tokens & {"radius", "fillet", "chamfer"}:
        return "radius", unit
    if unit in LENGTH_UNITS or tokens & {"width", "height", "depth", "length", "pitch", "distance"}:
        return "length", unit
    return None, unit


def validate(data, process=None):
    """Return (errors, warnings, infos, part_name, process); never mutates input."""
    errors, warnings, infos = [], [], []
    if not isinstance(data, dict):
        return ["top-level JSON must be an object"], [], [], None, None
    name = data.get("part_name", data.get("name"))
    if not isinstance(name, str) or not name.strip():
        errors.append("'part_name' must be a non-empty string")
        name = None
    else:
        name = name.strip()
    if "schema_version" in data and (type(data["schema_version"]) is not int or data["schema_version"] != 1):
        errors.append("only integer schema_version 1 is supported")
    units = unit_name(data.get("units"))
    if units not in LENGTH_UNITS:
        errors.append("'units' must be mm, cm, m or in")
    selected = process if process is not None else data.get("process")
    if selected is not None:
        if not isinstance(selected, str) or not selected.strip():
            errors.append("'process' must be a non-empty string or null")
            selected = None
        else:
            selected = selected.strip().upper()
    if selected and selected not in WALL_START_MM:
        warnings.append("process '%s' has no built-in manufacturing checks; generic checks only" % selected)
    unknown = set(data) - {"schema_version", "part_name", "name", "units", "process", "features"}
    for key in sorted(unknown):
        warnings.append("top-level field '%s' preserved but not validated" % key)
    features = data.get("features")
    if not isinstance(features, list) or not features:
        errors.append("'features' must be a non-empty array")
        features = []
    previous = set()
    for index, feature in enumerate(features, 1):
        label = "features[%d]" % (index - 1)
        if not isinstance(feature, dict):
            errors.append(label + " must be an object")
            continue
        step = feature.get("step")
        if type(step) is not int or step != index:
            errors.append(label + ": step must equal array position %d (ordered 1..N)" % index)
        kind = feature.get("type")
        if not isinstance(kind, str) or not kind.strip():
            errors.append(label + ": type must be a non-empty string")
        elif kind not in FEATURES:
            warnings.append(label + ": feature type '%s' not covered by built-in checks" % kind)
        deps = feature.get("depends_on", [])
        if not isinstance(deps, list):
            errors.append(label + ": depends_on must be an array of prior step numbers")
        else:
            for dep in deps:
                if type(dep) is not int or dep not in previous:
                    errors.append(label + ": dependency must refer to an earlier valid step")
        if type(step) is int and step == index:
            previous.add(step)
        for key in sorted(set(feature) - {"step", "type", "params", "depends_on"}):
            warnings.append(label + ": field '%s' preserved but not validated" % key)
        params = feature.get("params")
        if not isinstance(params, dict) or not params:
            errors.append(label + ": params must be a non-empty object")
            continue
        for key, raw in params.items():
            if not isinstance(key, str) or not key.strip():
                errors.append(label + ": parameter name must be a non-empty string")
                continue
            field = label + ".params." + key
            inferred, suffix = infer_parameter(key)
            if isinstance(raw, dict) and "kind" in raw:
                pkind, value = raw.get("kind"), raw.get("value")
                if not isinstance(pkind, str) or pkind not in KINDS:
                    errors.append(field + ": unsupported parameter kind")
                    continue
                if inferred and inferred != pkind:
                    errors.append(field + ": declared kind conflicts with recognized parameter name")
                    continue
                punit = unit_name(raw.get("unit")) if "unit" in raw else None
                if "unit" in raw and not punit:
                    errors.append(field + ": unit must be a non-empty string")
                    continue
                if suffix and punit and suffix != punit:
                    errors.append(field + ": unit conflicts with name suffix")
                    continue
                punit = punit or suffix
                for extra in sorted(set(raw) - {"kind", "value", "unit"}):
                    warnings.append(field + ": field '%s' preserved but not validated" % extra)
            else:
                pkind, value, punit = inferred, raw, suffix
            if pkind is None:
                if isinstance(value, (int, float)) and not isinstance(value, bool) and not finite_number(value):
                    errors.append(field + ": number must be finite")
                else:
                    warnings.append(field + ": unrecognized parameter preserved but not validated; declare kind/value")
                continue
            if not finite_number(value):
                errors.append(field + ": expected a finite number, not a boolean, string or object")
                continue
            if pkind == "count":
                if type(value) is not int or value < 1 or punit is not None:
                    errors.append(field + ": count must be a positive integer without units")
                continue
            if pkind == "scalar":
                if punit is not None:
                    errors.append(field + ": scalar must not have a unit")
                continue
            if pkind == "angle":
                if punit not in {"deg", "rad"}:
                    errors.append(field + ": angle requires explicit deg or rad unit")
                continue
            punit = punit or units
            if punit not in LENGTH_UNITS:
                errors.append(field + ": length quantity needs mm, cm, m or in")
                continue
            if pkind in POSITIVE and value <= 0:
                errors.append(field + ": %s must be greater than zero" % pkind)
                continue
            if pkind == "clearance" and value < 0:
                errors.append(field + ": clearance must be non-negative; model interference explicitly")
                continue
            try:
                mm = value * LENGTH_UNITS[punit]
            except OverflowError:
                mm = float("inf")
            if not math.isfinite(mm):
                errors.append(field + ": converted length is not finite")
                continue
            if selected in WALL_START_MM:
                if pkind == "wall" and mm < WALL_START_MM[selected]:
                    warnings.append(field + ": %g mm below %s wall starting point %g mm; process calibration required"
                                    % (mm, selected, WALL_START_MM[selected]))
                if pkind == "diameter" and mm < 1.0:
                    warnings.append(field + ": small printable hole; verify process capability and compensation")
    infos.append("Static parameter checks only; geometry, fit, global wall thickness and manufacturing are not verified")
    return errors, warnings, infos, name, selected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="JSON path or '-' for stdin")
    parser.add_argument("--process", help="optional manufacturing process override; no default process")
    parser.add_argument("--json", action="store_true", help="emit a JSON report, including on input errors")
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.read().lstrip("\ufeff") if args.source == "-" else Path(args.source).read_text(encoding="utf-8-sig")
        data = json.loads(raw)
        errors, warnings, infos, name, process = validate(data, args.process)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        errors, warnings, infos, name, process = ["input error: %s" % exc], [], [], None, None
    report = {"part_name": name, "process": process,
              "verdict": "FAIL" if errors else ("PASS WITH WARNINGS" if warnings else "PASS"),
              "scope": "static-parameters-only", "errors": errors, "warnings": warnings, "infos": infos}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("Part: %s; process: %s; %s" % (name, process or "unspecified", report["verdict"]))
        for label, messages in (("ERROR", errors), ("WARN", warnings), ("INFO", infos)):
            for message in messages:
                print("%s: %s" % (label, message))
    return 1 if errors else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
