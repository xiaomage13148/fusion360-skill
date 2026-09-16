#!/usr/bin/env python3
"""Validate a part parameter JSON before driving Fusion360 MCP modeling.

Checks:
  1. Structure   - part name, units, non-empty ordered feature list, positive numeric params.
  2. Manufacture - static printability heuristics (wall thickness, hole size,
                   fillet radius, draft angle, deep-cavity hints).

Parameter JSON template:

    {
      "part_name": "bracket",
      "units": "mm",
      "process": "FDM",
      "features": [
        {"step": 1, "type": "extrude",
         "params": {"width_mm": 40, "height_mm": 20, "depth_mm": 5}},
        {"step": 2, "type": "hole",
         "params": {"hole_dia_mm": 3.2, "count": 2, "wall_mm": 1.6}}
      ]
    }

Usage:
    python validate_part_params.py params.json
    python validate_part_params.py -            # read from stdin
    python validate_part_params.py params.json --process FDM --json

Exit codes:
    0 - no errors (warnings allowed)
    1 - one or more errors
"""

import argparse
import json
import re
import sys

WALL_HINTS = ("wall", "thickness", "shell")
HOLE_HINTS = ("hole", "dia", "diam", "bore", "drill")
RADIUS_HINTS = ("fillet", "radius", "chamfer")
DRAFT_HINTS = ("draft", "taper")
DEPTH_HINTS = ("depth", "height", "thickness", "wall")

MIN_WALL_MM = {"FDM": 1.2, "SLA": 0.8, "SLS": 0.8}
MIN_HOLE_MM = 1.0
MIN_FILLET_MM = 0.5
MIN_DRAFT_DEG = 1.0
DEEP_CAVITY_MM = 20.0


if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _matches(key, hints):
    lowered = key.lower()
    return any(hint in lowered for hint in hints)


def _numeric_items(params):
    """Yield (key, value) for finite numeric parameter values."""
    for key, value in params.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            yield key, float(value)


def validate(data, process):
    errors, warnings, infos = [], [], []

    if not isinstance(data, dict):
        return ["top-level JSON must be an object"], [], [], None, (process or "FDM").upper()

    # ---- structure -------------------------------------------------------
    part_name = data.get("part_name") or data.get("name")
    if not isinstance(part_name, str) or not part_name.strip():
        errors.append("missing or empty 'part_name'")
    else:
        part_name = part_name.strip()

    units = str(data.get("units", "")).strip().lower()
    if units not in ("mm", "millimeter", "millimetre"):
        if units in ("cm", "m", "in", "inch"):
            errors.append("units '%s' is not mm; convert all values to mm before modeling" % units)
        else:
            errors.append("'units' must be 'mm' (got %r)" % data.get("units"))

    process = (process or data.get("process") or "FDM").upper()
    if process not in MIN_WALL_MM:
        infos.append("unknown process '%s'; FDM wall limit applied" % process)
        process = "FDM"

    features = data.get("features")
    if not isinstance(features, list) or not features:
        errors.append("'features' must be a non-empty array")
        features = []

    seen_steps = set()
    for index, feature in enumerate(features, start=1):
        label = "features[%d]" % (index - 1)
        if not isinstance(feature, dict):
            errors.append("%s must be an object" % label)
            continue

        step = feature.get("step")
        if not isinstance(step, int) or step < 1:
            errors.append("%s: 'step' must be a positive integer" % label)
        elif step in seen_steps:
            errors.append("%s: duplicate step %d" % (label, step))
        else:
            seen_steps.add(step)

        feature_type = feature.get("type")
        if not isinstance(feature_type, str) or not feature_type.strip():
            errors.append("%s: 'type' must be a non-empty string (e.g. sketch/extrude/hole)" % label)

        params = feature.get("params", {})
        if not isinstance(params, dict) or not params:
            errors.append("%s: 'params' must be a non-empty object" % label)
            continue

        for key, value in _numeric_items(params):
            name = key.lower()
            if value != value or value in (float("inf"), float("-inf")):
                errors.append("%s: '%s' is not a finite number" % (label, key))
                continue

            if _matches(name, DRAFT_HINTS):
                if value != 0 and abs(value) < MIN_DRAFT_DEG:
                    warnings.append("%s: draft '%s' = %g deg is below %g deg; release may bind"
                                    % (label, key, value, MIN_DRAFT_DEG))
                continue

            if _matches(name, HOLE_HINTS):
                if value < MIN_HOLE_MM:
                    warnings.append("%s: hole '%s' = %g mm is below printable minimum %g mm"
                                    % (label, key, value, MIN_HOLE_MM))
                continue

            if _matches(name, RADIUS_HINTS):
                if value < MIN_FILLET_MM:
                    infos.append("%s: radius '%s' = %g mm is very small; expect fillet failure"
                                 % (label, key, value))
                continue

            if _matches(name, WALL_HINTS):
                limit = MIN_WALL_MM[process]
                if value < limit:
                    warnings.append("%s: wall '%s' = %g mm is below %s minimum %g mm"
                                    % (label, key, value, process, limit))
                continue

            # depth/height style dimensions: only sanity-check the sign
            if value <= 0:
                warnings.append("%s: dimension '%s' = %g is not positive; verify direction handling"
                                % (label, key, value))

        # deep cavity hint: depth-like value far exceeding wall-like value
        depth_like = [v for k, v in _numeric_items(params) if _matches(k.lower(), DEPTH_HINTS)]
        if depth_like and max(depth_like) > DEEP_CAVITY_MM and not any(
            _matches(k.lower(), DRAFT_HINTS) for k in params
        ):
            infos.append("%s: feature deeper than %g mm without a draft angle; consider 1-3 deg draft"
                         % (label, DEEP_CAVITY_MM))

    if features and seen_steps:
        expected = list(range(1, len(features) + 1))
        if sorted(seen_steps) != expected:
            warnings.append("steps %s are not a contiguous 1..%d sequence; execution order may be ambiguous"
                            % (sorted(seen_steps), len(features)))

    return errors, warnings, infos, part_name, process


def main():
    parser = argparse.ArgumentParser(description="Validate part parameter JSON for Fusion360 MCP modeling.")
    parser.add_argument("source", help="path to the JSON file, or '-' to read from stdin")
    parser.add_argument("--process", default=None, help="printing process: FDM / SLA / SLS (default FDM or JSON field)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON report")
    args = parser.parse_args()

    try:
        if args.source == "-":
            raw = sys.stdin.read().lstrip("\ufeff")
        else:
            # utf-8-sig tolerates a BOM written by Notepad / PowerShell
            with open(args.source, "r", encoding="utf-8-sig") as handle:
                raw = handle.read()
        data = json.loads(raw)
    except FileNotFoundError:
        print("ERROR: file not found: %s" % args.source)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print("ERROR: invalid JSON - %s" % exc)
        sys.exit(1)

    errors, warnings, infos, part_name, process = validate(data, args.process)
    verdict = "FAIL" if errors else ("PASS WITH WARNINGS" if warnings else "PASS")

    report = {
        "part_name": part_name,
        "process": process,
        "verdict": verdict,
        "errors": errors,
        "warnings": warnings,
        "infos": infos,
    }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("Part parameter validation")
        print("  part    : %s" % (part_name or "<unnamed>"))
        print("  process : %s" % process)
        for label, items in (("ERROR", errors), ("WARN", warnings), ("INFO", infos)):
            for item in items:
                print("  %-5s : %s" % (label, item))
        print("  verdict : %s" % verdict)

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
