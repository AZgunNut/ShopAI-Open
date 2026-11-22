#!/usr/bin/env python3
import json
import re
import subprocess
import sys
import time
from pathlib import Path

FREECADCMD = Path.home() / "ShopAI/work/freecad-bridge-test/squashfs-root/usr/bin/freecadcmd"
BASE = Path.home() / "ShopAI/freecad_bridge"
OUTPUTS = BASE / "outputs"
LOGS = BASE / "logs"

ALLOWED_ACTIONS = {"create_box", "create_part_from_features"}
ALLOWED_EXPORTS = {
    "FCStd",
    "STEP",
    "SVG_TOP",
    "DXF_TOP",
    "SVG_FRONT",
    "DXF_FRONT",
    "SVG_RIGHT",
    "DXF_RIGHT",
    "SVG_LEFT",
    "DXF_LEFT",
    "SVG_BACK",
    "DXF_BACK",
    "SVG_BOTTOM",
    "DXF_BOTTOM",
}
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def fail(message, code=1):
    print(json.dumps({"ok": False, "error": message}, indent=2))
    sys.exit(code)


def clean_name(value, field):
    if not isinstance(value, str) or not NAME_RE.match(value):
        fail(f"Invalid {field}. Use letters, numbers, underscore, or dash only.")
    return value


def clean_positive_number(action, key, max_value=10000):
    value = action.get(key)
    if not isinstance(value, (int, float)):
        fail(f"{key} must be a number")
    if value <= 0 or value > max_value:
        fail(f"{key} out of allowed range")
    return float(value)


def clean_exports(action):
    exports = action.get("exports", ["FCStd"])
    if not isinstance(exports, list) or not exports:
        fail("exports must be a non-empty list")

    clean = []
    for item in exports:
        if item not in ALLOWED_EXPORTS:
            fail(f"Unsupported export: {item}")
        if item not in clean:
            clean.append(item)
    return clean


def clean_confidence(feature, index):
    confidence = feature.get("confidence", 1.0)
    if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
        fail(f"feature {index} confidence must be 0.0 to 1.0")
    return float(confidence)


def clean_xy(feature, key, index):
    value = feature.get(key)
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(isinstance(v, (int, float)) for v in value)
    ):
        fail(f"feature {index} {key} must be [x, y] numbers")
    return [float(value[0]), float(value[1])]


def clean_xyz(feature, key, index, default=None):
    value = feature.get(key, default)
    if (
        not isinstance(value, list)
        or len(value) != 3
        or not all(isinstance(v, (int, float)) for v in value)
    ):
        fail(f"feature {index} {key} must be [x, y, z] numbers")
    return [float(value[0]), float(value[1]), float(value[2])]


def load_action(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            action = json.load(f)
    except Exception as exc:
        fail(f"Could not read action JSON: {exc}")

    if not isinstance(action, dict):
        fail("Action must be a JSON object")

    if action.get("action") not in ALLOWED_ACTIONS:
        fail("Unsupported action")

    return action


def validate_feature(feature, index):
    if not isinstance(feature, dict):
        fail(f"feature {index} must be an object")

    feature_type = feature.get("type")
    feature_id = clean_name(feature.get("id"), f"feature {index} id")
    confidence = clean_confidence(feature, index)
    source = str(feature.get("source", ""))[:200]

    if feature_type == "box":
        return {
            "id": feature_id,
            "type": "box",
            "length_mm": clean_positive_number(feature, "length_mm"),
            "width_mm": clean_positive_number(feature, "width_mm"),
            "height_mm": clean_positive_number(feature, "height_mm"),
            "origin_mm": clean_xyz(feature, "origin_mm", index, [0, 0, 0]),
            "confidence": confidence,
            "source": source,
        }

    if feature_type == "through_hole_z":
        return {
            "id": feature_id,
            "type": "through_hole_z",
            "center_mm": clean_xy(feature, "center_mm", index),
            "diameter_mm": clean_positive_number(feature, "diameter_mm"),
            "confidence": confidence,
            "source": source,
        }

    if feature_type == "round_slot_z":
        length = clean_positive_number(feature, "length_mm")
        width = clean_positive_number(feature, "width_mm")
        if length < width:
            fail(f"feature {index} slot length must be >= width")

        angle = feature.get("angle_deg", 0)
        if not isinstance(angle, (int, float)):
            fail(f"feature {index} angle_deg must be a number")

        return {
            "id": feature_id,
            "type": "round_slot_z",
            "center_mm": clean_xy(feature, "center_mm", index),
            "length_mm": float(length),
            "width_mm": float(width),
            "angle_deg": float(angle),
            "confidence": confidence,
            "source": source,
        }

    if feature_type in {"rectangular_cutout_z", "rectangular_pocket_z", "channel_z"}:
        angle = feature.get("angle_deg", 0)
        if not isinstance(angle, (int, float)):
            fail(f"feature {index} angle_deg must be a number")

        clean = {
            "id": feature_id,
            "type": feature_type,
            "center_mm": clean_xy(feature, "center_mm", index),
            "length_mm": clean_positive_number(feature, "length_mm"),
            "width_mm": clean_positive_number(feature, "width_mm"),
            "angle_deg": float(angle),
            "confidence": confidence,
            "source": source,
        }

        if feature_type in {"rectangular_pocket_z", "channel_z"}:
            clean["depth_mm"] = clean_positive_number(feature, "depth_mm")

        return clean

    if feature_type == "boss_cylinder_z":
        return {
            "id": feature_id,
            "type": "boss_cylinder_z",
            "center_mm": clean_xy(feature, "center_mm", index),
            "diameter_mm": clean_positive_number(feature, "diameter_mm"),
            "height_mm": clean_positive_number(feature, "height_mm"),
            "base_z_mm": float(feature.get("base_z_mm", 0)),
            "confidence": confidence,
            "source": source,
        }

    if feature_type == "counterbore_z":
        return {
            "id": feature_id,
            "type": "counterbore_z",
            "center_mm": clean_xy(feature, "center_mm", index),
            "hole_diameter_mm": clean_positive_number(feature, "hole_diameter_mm"),
            "counterbore_diameter_mm": clean_positive_number(feature, "counterbore_diameter_mm"),
            "counterbore_depth_mm": clean_positive_number(feature, "counterbore_depth_mm"),
            "confidence": confidence,
            "source": source,
        }

    if feature_type == "countersink_z":
        return {
            "id": feature_id,
            "type": "countersink_z",
            "center_mm": clean_xy(feature, "center_mm", index),
            "hole_diameter_mm": clean_positive_number(feature, "hole_diameter_mm"),
            "countersink_diameter_mm": clean_positive_number(feature, "countersink_diameter_mm"),
            "countersink_angle_deg": clean_positive_number(feature, "countersink_angle_deg", 179),
            "confidence": confidence,
            "source": source,
        }

    if feature_type == "round_pocket_z":
        return {
            "id": feature_id,
            "type": "round_pocket_z",
            "center_mm": clean_xy(feature, "center_mm", index),
            "diameter_mm": clean_positive_number(feature, "diameter_mm"),
            "depth_mm": clean_positive_number(feature, "depth_mm"),
            "confidence": confidence,
            "source": source,
        }

    if feature_type == "bolt_circle_holes_z":
        count = feature.get("count")
        if not isinstance(count, int) or count < 1 or count > 360:
            fail(f"feature {index} count must be an integer from 1 to 360")

        start_angle = feature.get("start_angle_deg", 0)
        if not isinstance(start_angle, (int, float)):
            fail(f"feature {index} start_angle_deg must be a number")

        return {
            "id": feature_id,
            "type": "bolt_circle_holes_z",
            "center_mm": clean_xy(feature, "center_mm", index),
            "bolt_circle_diameter_mm": clean_positive_number(feature, "bolt_circle_diameter_mm"),
            "hole_diameter_mm": clean_positive_number(feature, "hole_diameter_mm"),
            "count": count,
            "start_angle_deg": float(start_angle),
            "confidence": confidence,
            "source": source,
        }

    if feature_type == "cone_frustum_z":
        mode = feature.get("mode", "add")
        if mode not in {"add", "cut"}:
            fail(f"feature {index} mode must be add or cut")

        return {
            "id": feature_id,
            "type": "cone_frustum_z",
            "center_mm": clean_xy(feature, "center_mm", index),
            "bottom_diameter_mm": clean_positive_number(feature, "bottom_diameter_mm"),
            "top_diameter_mm": clean_positive_number(feature, "top_diameter_mm"),
            "height_mm": clean_positive_number(feature, "height_mm"),
            "base_z_mm": float(feature.get("base_z_mm", 0)),
            "mode": mode,
            "confidence": confidence,
            "source": source,
        }

    if feature_type == "tapered_hole_z":
        return {
            "id": feature_id,
            "type": "tapered_hole_z",
            "center_mm": clean_xy(feature, "center_mm", index),
            "bottom_diameter_mm": clean_positive_number(feature, "bottom_diameter_mm"),
            "top_diameter_mm": clean_positive_number(feature, "top_diameter_mm"),
            "depth_mm": clean_positive_number(feature, "depth_mm"),
            "confidence": confidence,
            "source": source,
        }

    if feature_type == "polygon_prism_z":
        sides = feature.get("sides")
        if not isinstance(sides, int) or sides < 3 or sides > 64:
            fail(f"feature {index} sides must be integer 3..64")

        mode = feature.get("mode", "add")
        if mode not in {"add", "cut"}:
            fail(f"feature {index} mode must be add or cut")

        angle = feature.get("angle_deg", 0)
        if not isinstance(angle, (int, float)):
            fail(f"feature {index} angle_deg must be a number")

        return {
            "id": feature_id,
            "type": "polygon_prism_z",
            "center_mm": clean_xy(feature, "center_mm", index),
            "sides": sides,
            "across_flats_mm": clean_positive_number(feature, "across_flats_mm"),
            "height_mm": clean_positive_number(feature, "height_mm"),
            "base_z_mm": float(feature.get("base_z_mm", 0)),
            "angle_deg": float(angle),
            "mode": mode,
            "confidence": confidence,
            "source": source,
        }

    if feature_type == "linear_pattern_holes_z":
        start = clean_xy(feature, "start_mm", index)
        spacing = clean_xy(feature, "spacing_mm", index)
        count = feature.get("count")
        if not isinstance(count, int) or count < 1 or count > 200:
            fail(f"feature {index} count must be an integer from 1 to 200")
        return {
            "id": feature_id,
            "type": "linear_pattern_holes_z",
            "start_mm": start,
            "spacing_mm": spacing,
            "count": count,
            "diameter_mm": clean_positive_number(feature, "diameter_mm"),
            "confidence": clean_confidence(feature, index),
            "source": str(feature.get("source", ""))[:200],
        }

    if feature_type == "rectangular_pattern_holes_z":
        origin = clean_xy(feature, "origin_mm", index)
        x_count = feature.get("x_count")
        y_count = feature.get("y_count")
        if not isinstance(x_count, int) or x_count < 1 or x_count > 100:
            fail(f"feature {index} x_count must be an integer from 1 to 100")
        if not isinstance(y_count, int) or y_count < 1 or y_count > 100:
            fail(f"feature {index} y_count must be an integer from 1 to 100")
        return {
            "id": feature_id,
            "type": "rectangular_pattern_holes_z",
            "origin_mm": origin,
            "x_count": x_count,
            "y_count": y_count,
            "x_spacing_mm": clean_positive_number(feature, "x_spacing_mm"),
            "y_spacing_mm": clean_positive_number(feature, "y_spacing_mm"),
            "diameter_mm": clean_positive_number(feature, "diameter_mm"),
            "confidence": clean_confidence(feature, index),
            "source": str(feature.get("source", ""))[:200],
        }

    if feature_type == "rib_web_z":
        return {
            "id": feature_id,
            "type": "rib_web_z",
            "start_mm": clean_xy(feature, "start_mm", index),
            "end_mm": clean_xy(feature, "end_mm", index),
            "thickness_mm": clean_positive_number(feature, "thickness_mm"),
            "height_mm": clean_positive_number(feature, "height_mm"),
            "base_z_mm": float(feature.get("base_z_mm", 0)),
            "confidence": clean_confidence(feature, index),
            "source": str(feature.get("source", ""))[:200],
        }

    if feature_type == "sphere_z":
        mode = feature.get("mode", "add")
        if mode not in ("add", "cut"):
            fail(f"feature {index} mode must be add or cut")
        return {
            "id": feature_id,
            "type": "sphere_z",
            "center_mm": clean_xy(feature, "center_mm", index),
            "radius_mm": clean_positive_number(feature, "radius_mm"),
            "center_z_mm": float(feature.get("center_z_mm", 0)),
            "mode": mode,
            "confidence": clean_confidence(feature, index),
            "source": str(feature.get("source", ""))[:200],
        }

    if feature_type == "hemisphere_dome_z":
        mode = feature.get("mode", "add")
        if mode not in ("add", "cut"):
            fail(f"feature {index} mode must be add or cut")
        return {
            "id": feature_id,
            "type": "hemisphere_dome_z",
            "center_mm": clean_xy(feature, "center_mm", index),
            "radius_mm": clean_positive_number(feature, "radius_mm"),
            "base_z_mm": float(feature.get("base_z_mm", 0)),
            "mode": mode,
            "confidence": clean_confidence(feature, index),
            "source": str(feature.get("source", ""))[:200],
        }

    if feature_type == "spherical_cap_z":
        mode = feature.get("mode", "add")
        if mode not in ("add", "cut"):
            fail(f"feature {index} mode must be add or cut")
        return {
            "id": feature_id,
            "type": "spherical_cap_z",
            "center_mm": clean_xy(feature, "center_mm", index),
            "radius_mm": clean_positive_number(feature, "radius_mm"),
            "cap_height_mm": clean_positive_number(feature, "cap_height_mm"),
            "base_z_mm": float(feature.get("base_z_mm", 0)),
            "mode": mode,
            "confidence": clean_confidence(feature, index),
            "source": str(feature.get("source", ""))[:200],
        }

    if feature_type == "ogive_z":
        mode = feature.get("mode", "add")
        if mode not in ("add", "cut"):
            fail(f"feature {index} mode must be add or cut")
        return {
            "id": feature_id,
            "type": "ogive_z",
            "center_mm": clean_xy(feature, "center_mm", index),
            "base_diameter_mm": clean_positive_number(feature, "base_diameter_mm"),
            "height_mm": clean_positive_number(feature, "height_mm"),
            "tip_diameter_mm": float(feature.get("tip_diameter_mm", 0)),
            "base_z_mm": float(feature.get("base_z_mm", 0)),
            "mode": mode,
            "confidence": clean_confidence(feature, index),
            "source": str(feature.get("source", ""))[:200],
        }

    if feature_type == "spline_path_z":
        points = feature.get("points_mm")
        if (
            not isinstance(points, list)
            or len(points) < 2
            or not all(isinstance(p, list) and len(p) == 2 and all(isinstance(v, (int, float)) for v in p) for p in points)
        ):
            fail(f"feature {index} points_mm must be at least two [x, y] points")
        return {
            "id": feature_id,
            "type": "spline_path_z",
            "points_mm": [[float(p[0]), float(p[1])] for p in points],
            "width_mm": clean_positive_number(feature, "width_mm"),
            "depth_mm": clean_positive_number(feature, "depth_mm"),
            "base_z_mm": float(feature.get("base_z_mm", 0)),
            "mode": feature.get("mode", "cut"),
            "confidence": clean_confidence(feature, index),
            "source": str(feature.get("source", ""))[:200],
        }

    if feature_type in ("involute_gear_external_z", "involute_gear_internal_z"):
        teeth = feature.get("teeth")
        if not isinstance(teeth, int) or teeth < 3 or teeth > 1000:
            fail(f"feature {index} teeth must be an integer from 3 to 1000")
        return {
            "id": feature_id,
            "type": feature_type,
            "center_mm": clean_xy(feature, "center_mm", index),
            "teeth": teeth,
            "module_mm": clean_positive_number(feature, "module_mm"),
            "pressure_angle_deg": float(feature.get("pressure_angle_deg", 20)),
            "face_width_mm": clean_positive_number(feature, "face_width_mm"),
            "bore_diameter_mm": float(feature.get("bore_diameter_mm", 0)),
            "base_z_mm": float(feature.get("base_z_mm", 0)),
            "standard": str(feature.get("standard", "metric_involute"))[:80],
            "confidence": clean_confidence(feature, index),
            "source": str(feature.get("source", ""))[:200],
        }

    if feature_type in ("straight_groove_z", "keyway_slot_z"):
        angle = feature.get("angle_deg", 0)
        return {
            "id": feature_id,
            "type": feature_type,
            "center_mm": clean_xy(feature, "center_mm", index),
            "length_mm": clean_positive_number(feature, "length_mm"),
            "width_mm": clean_positive_number(feature, "width_mm"),
            "depth_mm": clean_positive_number(feature, "depth_mm"),
            "base_z_mm": float(feature.get("base_z_mm", 0)),
            "angle_deg": float(angle),
            "confidence": clean_confidence(feature, index),
            "source": str(feature.get("source", ""))[:200],
        }

    if feature_type == "v_groove_z":
        angle = feature.get("angle_deg", 0)
        included = feature.get("included_angle_deg", 90)
        if not isinstance(included, (int, float)) or included <= 0 or included >= 170:
            fail(f"feature {index} included_angle_deg must be 0 to 170")
        return {
            "id": feature_id,
            "type": "v_groove_z",
            "center_mm": clean_xy(feature, "center_mm", index),
            "length_mm": clean_positive_number(feature, "length_mm"),
            "top_width_mm": clean_positive_number(feature, "top_width_mm"),
            "depth_mm": clean_positive_number(feature, "depth_mm"),
            "base_z_mm": float(feature.get("base_z_mm", 0)),
            "angle_deg": float(angle),
            "included_angle_deg": float(included),
            "confidence": clean_confidence(feature, index),
            "source": str(feature.get("source", ""))[:200],
        }

    if feature_type == "dovetail_slot_z":
        angle = feature.get("angle_deg", 0)
        return {
            "id": feature_id,
            "type": "dovetail_slot_z",
            "center_mm": clean_xy(feature, "center_mm", index),
            "length_mm": clean_positive_number(feature, "length_mm"),
            "top_width_mm": clean_positive_number(feature, "top_width_mm"),
            "bottom_width_mm": clean_positive_number(feature, "bottom_width_mm"),
            "depth_mm": clean_positive_number(feature, "depth_mm"),
            "base_z_mm": float(feature.get("base_z_mm", 0)),
            "angle_deg": float(angle),
            "confidence": clean_confidence(feature, index),
            "source": str(feature.get("source", ""))[:200],
        }

    if feature_type in ("thread_external_z", "thread_internal_z"):
        hand = feature.get("hand", "right")
        if hand not in ("right", "left"):
            fail(f"feature {index} hand must be right or left")
        model_mode = feature.get("model_mode", "metadata")
        if model_mode not in ("metadata", "cylinder"):
            fail(f"feature {index} model_mode must be metadata or cylinder")
        return {
            "id": feature_id,
            "type": feature_type,
            "center_mm": clean_xy(feature, "center_mm", index),
            "standard": str(feature.get("standard", "unknown"))[:80],
            "designation": str(feature.get("designation", ""))[:80],
            "major_diameter_mm": clean_positive_number(feature, "major_diameter_mm"),
            "minor_diameter_mm": float(feature.get("minor_diameter_mm", 0)),
            "pitch_mm": float(feature.get("pitch_mm", 0)),
            "tpi": float(feature.get("tpi", 0)),
            "thread_length_mm": clean_positive_number(feature, "thread_length_mm"),
            "base_z_mm": float(feature.get("base_z_mm", 0)),
            "hand": hand,
            "class_fit": str(feature.get("class_fit", ""))[:40],
            "starts": int(feature.get("starts", 1)),
            "model_mode": model_mode,
            "operation": str(feature.get("operation", ""))[:80],
            "confidence": clean_confidence(feature, index),
            "source": str(feature.get("source", ""))[:200],
        }

    if feature_type == "thread_relief_groove_z":
        return {
            "id": feature_id,
            "type": "thread_relief_groove_z",
            "center_mm": clean_xy(feature, "center_mm", index),
            "diameter_mm": clean_positive_number(feature, "diameter_mm"),
            "groove_width_mm": clean_positive_number(feature, "groove_width_mm"),
            "groove_depth_mm": clean_positive_number(feature, "groove_depth_mm"),
            "base_z_mm": float(feature.get("base_z_mm", 0)),
            "orientation": str(feature.get("orientation", "external"))[:40],
            "confidence": clean_confidence(feature, index),
            "source": str(feature.get("source", ""))[:200],
        }

    if feature_type in ("thread_mill_path_metadata", "lathe_thread_metadata"):
        clean = dict(feature)
        clean["id"] = feature_id
        clean["type"] = feature_type
        clean["confidence"] = clean_confidence(feature, index)
        clean["source"] = str(feature.get("source", ""))[:200]
        return clean

    if feature_type == "thread_metadata":
        clean = dict(feature)
        clean["id"] = feature_id
        clean["type"] = feature_type
        clean["confidence"] = confidence
        clean["source"] = source
        return clean

    fail(f"feature {index} unsupported type")


def validate_create_box(action):
    return {
        "action": "create_box",
        "part_name": clean_name(action.get("name"), "name"),
        "features": [
            {
                "id": "base_box",
                "type": "box",
                "length_mm": clean_positive_number(action, "length_mm"),
                "width_mm": clean_positive_number(action, "width_mm"),
                "height_mm": clean_positive_number(action, "height_mm"),
                "origin_mm": [0.0, 0.0, 0.0],
                "confidence": 1.0,
                "source": "direct create_box action",
            }
        ],
        "exports": clean_exports(action),
        "datums": {},
    }


def validate_ledger(action):
    if action.get("units") != "mm":
        fail("Only units=mm is supported right now")

    features = action.get("features")
    if not isinstance(features, list) or not features:
        fail("features must be a non-empty list")

    return {
        "action": "create_part_from_features",
        "part_name": clean_name(action.get("part_name"), "part_name"),
        "features": [validate_feature(feature, i) for i, feature in enumerate(features)],
        "exports": clean_exports(action),
        "datums": action.get("datums", {}),
    }


def validate_action(action):
    if action["action"] == "create_box":
        return validate_create_box(action)
    if action["action"] == "create_part_from_features":
        return validate_ledger(action)
    fail("Unsupported action")


def run_freecad(spec):
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    run_name = f"{timestamp}-{spec['part_name']}"
    outdir = OUTPUTS / run_name
    outdir.mkdir(parents=True, exist_ok=False)
    LOGS.mkdir(parents=True, exist_ok=True)

    script_path = outdir / "freecad_job.py"
    report_path = outdir / "report.json"
    stdout_path = LOGS / f"{run_name}.stdout.txt"
    stderr_path = LOGS / f"{run_name}.stderr.txt"

    paths = {
        "fcstd": str(outdir / f"{spec['part_name']}.FCStd"),
        "step": str(outdir / f"{spec['part_name']}.step"),
        "svg_top": str(outdir / f"{spec['part_name']}_top.svg"),
        "dxf_top": str(outdir / f"{spec['part_name']}_top.dxf"),
        "svg_front": str(outdir / f"{spec['part_name']}_front.svg"),
        "dxf_front": str(outdir / f"{spec['part_name']}_front.dxf"),
        "svg_right": str(outdir / f"{spec['part_name']}_right.svg"),
        "dxf_right": str(outdir / f"{spec['part_name']}_right.dxf"),
        "svg_left": str(outdir / f"{spec['part_name']}_left.svg"),
        "dxf_left": str(outdir / f"{spec['part_name']}_left.dxf"),
        "svg_back": str(outdir / f"{spec['part_name']}_back.svg"),
        "dxf_back": str(outdir / f"{spec['part_name']}_back.dxf"),
        "svg_bottom": str(outdir / f"{spec['part_name']}_bottom.svg"),
        "dxf_bottom": str(outdir / f"{spec['part_name']}_bottom.dxf"),
        "report": str(report_path),
    }

    job = r'''
import json
import os
import sys
import traceback

SPEC = __SPEC_JSON__
PATHS = __PATHS_JSON__

report = {
    "ok": False,
    "stage": "start",
    "outputs": {},
    "checks": {},
    "error": None
}

try:
    import FreeCAD as App
    import Part
    import TechDraw
    import math

    doc = App.newDocument(SPEC["part_name"])
    created = []
    body_shape = None
    body_height = None
    body_min_z = 0

    for feature in SPEC["features"]:
        if feature["type"] == "box":
            box = Part.makeBox(
                feature["length_mm"],
                feature["width_mm"],
                feature["height_mm"],
                App.Vector(
                    feature["origin_mm"][0],
                    feature["origin_mm"][1],
                    feature["origin_mm"][2],
                ),
            )
            if body_shape is None:
                body_shape = box
                body_height = feature["height_mm"]
                body_min_z = feature["origin_mm"][2]
            else:
                body_shape = body_shape.fuse(box)

        elif feature["type"] == "through_hole_z":
            if body_shape is None:
                raise RuntimeError("through_hole_z requires a box before it")

            radius = feature["diameter_mm"] / 2.0
            hole_depth = (body_height or 1) + 2.0
            hole = Part.makeCylinder(
                radius,
                hole_depth,
                App.Vector(feature["center_mm"][0], feature["center_mm"][1], body_min_z - 1.0),
                App.Vector(0, 0, 1),
            )
            body_shape = body_shape.cut(hole)

        elif feature["type"] == "round_slot_z":
            if body_shape is None:
                raise RuntimeError("round_slot_z requires a box before it")

            cx = feature["center_mm"][0]
            cy = feature["center_mm"][1]
            length = feature["length_mm"]
            width = feature["width_mm"]
            angle_deg = feature.get("angle_deg", 0)
            angle = math.radians(angle_deg)
            radius = width / 2.0
            straight = max(length - width, 0.001)
            hole_depth = (body_height or 1) + 2.0
            zbase = body_min_z - 1.0

            dx = math.cos(angle)
            dy = math.sin(angle)

            sx = cx - dx * straight / 2.0
            sy = cy - dy * straight / 2.0
            ex = cx + dx * straight / 2.0
            ey = cy + dy * straight / 2.0

            cyl1 = Part.makeCylinder(radius, hole_depth, App.Vector(sx, sy, zbase), App.Vector(0, 0, 1))
            cyl2 = Part.makeCylinder(radius, hole_depth, App.Vector(ex, ey, zbase), App.Vector(0, 0, 1))

            rect = Part.makeBox(straight, width, hole_depth, App.Vector(-straight / 2.0, -width / 2.0, zbase))
            rect.rotate(App.Vector(0, 0, zbase), App.Vector(0, 0, 1), angle_deg)
            rect.translate(App.Vector(cx, cy, 0))

            cutter = cyl1.fuse(cyl2).fuse(rect)
            body_shape = body_shape.cut(cutter)

        elif feature["type"] in ("rectangular_cutout_z", "rectangular_pocket_z", "channel_z"):
            if body_shape is None:
                raise RuntimeError(feature["type"] + " requires a box before it")

            cx = feature["center_mm"][0]
            cy = feature["center_mm"][1]
            length = feature["length_mm"]
            width = feature["width_mm"]
            angle_deg = feature.get("angle_deg", 0)

            if feature["type"] == "rectangular_cutout_z":
                cut_depth = (body_height or 1) + 2.0
                zbase = body_min_z - 1.0
            else:
                cut_depth = feature["depth_mm"]
                zbase = body_min_z + (body_height or 0) - cut_depth

            cutter = Part.makeBox(length, width, cut_depth + 0.001, App.Vector(-length / 2.0, -width / 2.0, zbase))
            cutter.rotate(App.Vector(0, 0, zbase), App.Vector(0, 0, 1), angle_deg)
            cutter.translate(App.Vector(cx, cy, 0))
            body_shape = body_shape.cut(cutter)

        elif feature["type"] == "boss_cylinder_z":
            if body_shape is None:
                raise RuntimeError("boss_cylinder_z requires a box before it")

            radius = feature["diameter_mm"] / 2.0
            boss = Part.makeCylinder(
                radius,
                feature["height_mm"],
                App.Vector(feature["center_mm"][0], feature["center_mm"][1], feature.get("base_z_mm", 0)),
                App.Vector(0, 0, 1),
            )
            body_shape = body_shape.fuse(boss)

        elif feature["type"] == "counterbore_z":
            if body_shape is None:
                raise RuntimeError("counterbore_z requires a box before it")

            through_radius = feature["hole_diameter_mm"] / 2.0
            cbore_radius = feature["counterbore_diameter_mm"] / 2.0
            hole_depth = (body_height or 1) + 2.0

            through_hole = Part.makeCylinder(
                through_radius,
                hole_depth,
                App.Vector(feature["center_mm"][0], feature["center_mm"][1], body_min_z - 1.0),
                App.Vector(0, 0, 1),
            )

            cbore = Part.makeCylinder(
                cbore_radius,
                feature["counterbore_depth_mm"] + 0.001,
                App.Vector(
                    feature["center_mm"][0],
                    feature["center_mm"][1],
                    body_min_z + (body_height or 0) - feature["counterbore_depth_mm"],
                ),
                App.Vector(0, 0, 1),
            )

            body_shape = body_shape.cut(through_hole).cut(cbore)

        elif feature["type"] == "countersink_z":
            if body_shape is None:
                raise RuntimeError("countersink_z requires a box before it")

            through_radius = feature["hole_diameter_mm"] / 2.0
            top_radius = feature["countersink_diameter_mm"] / 2.0
            angle_rad = math.radians(feature["countersink_angle_deg"] / 2.0)
            csink_depth = (top_radius - through_radius) / math.tan(angle_rad)
            hole_depth = (body_height or 1) + 2.0

            through_hole = Part.makeCylinder(
                through_radius,
                hole_depth,
                App.Vector(feature["center_mm"][0], feature["center_mm"][1], body_min_z - 1.0),
                App.Vector(0, 0, 1),
            )

            cone = Part.makeCone(
                through_radius,
                top_radius,
                csink_depth + 0.001,
                App.Vector(
                    feature["center_mm"][0],
                    feature["center_mm"][1],
                    body_min_z + (body_height or 0) - csink_depth,
                ),
                App.Vector(0, 0, 1),
            )

            body_shape = body_shape.cut(through_hole).cut(cone)

        elif feature["type"] == "round_pocket_z":
            if body_shape is None:
                raise RuntimeError("round_pocket_z requires a box before it")

            pocket = Part.makeCylinder(
                feature["diameter_mm"] / 2.0,
                feature["depth_mm"] + 0.001,
                App.Vector(
                    feature["center_mm"][0],
                    feature["center_mm"][1],
                    body_min_z + (body_height or 0) - feature["depth_mm"],
                ),
                App.Vector(0, 0, 1),
            )
            body_shape = body_shape.cut(pocket)

        elif feature["type"] == "bolt_circle_holes_z":
            if body_shape is None:
                raise RuntimeError("bolt_circle_holes_z requires a box before it")

            radius = feature["bolt_circle_diameter_mm"] / 2.0
            hole_radius = feature["hole_diameter_mm"] / 2.0
            hole_depth = (body_height or 1) + 2.0

            for i in range(feature["count"]):
                angle_deg = feature.get("start_angle_deg", 0) + (360.0 * i / feature["count"])
                angle = math.radians(angle_deg)
                x = feature["center_mm"][0] + math.cos(angle) * radius
                y = feature["center_mm"][1] + math.sin(angle) * radius
                hole = Part.makeCylinder(
                    hole_radius,
                    hole_depth,
                    App.Vector(x, y, body_min_z - 1.0),
                    App.Vector(0, 0, 1),
                )
                body_shape = body_shape.cut(hole)

        elif feature["type"] == "cone_frustum_z":
            if body_shape is None and feature.get("mode", "add") == "cut":
                raise RuntimeError("cone_frustum_z cut requires a box before it")

            cone = Part.makeCone(
                feature["bottom_diameter_mm"] / 2.0,
                feature["top_diameter_mm"] / 2.0,
                feature["height_mm"],
                App.Vector(feature["center_mm"][0], feature["center_mm"][1], feature.get("base_z_mm", 0)),
                App.Vector(0, 0, 1),
            )

            if feature.get("mode", "add") == "add":
                body_shape = cone if body_shape is None else body_shape.fuse(cone)
            else:
                body_shape = body_shape.cut(cone)

        elif feature["type"] == "tapered_hole_z":
            if body_shape is None:
                raise RuntimeError("tapered_hole_z requires a box before it")

            zbase = body_min_z + (body_height or 0) - feature["depth_mm"]
            cutter = Part.makeCone(
                feature["bottom_diameter_mm"] / 2.0,
                feature["top_diameter_mm"] / 2.0,
                feature["depth_mm"] + 0.001,
                App.Vector(feature["center_mm"][0], feature["center_mm"][1], zbase),
                App.Vector(0, 0, 1),
            )
            body_shape = body_shape.cut(cutter)

        elif feature["type"] == "polygon_prism_z":
            if body_shape is None and feature.get("mode", "add") == "cut":
                raise RuntimeError("polygon_prism_z cut requires a box before it")

            sides = feature["sides"]
            apothem = feature["across_flats_mm"] / 2.0
            radius = apothem / math.cos(math.pi / sides)
            angle_offset = math.radians(feature.get("angle_deg", 0))

            points = []
            for i in range(sides):
                a = angle_offset + 2.0 * math.pi * i / sides
                points.append(App.Vector(
                    feature["center_mm"][0] + math.cos(a) * radius,
                    feature["center_mm"][1] + math.sin(a) * radius,
                    feature.get("base_z_mm", 0),
                ))

            wire = Part.makePolygon(points + [points[0]])
            face = Part.Face(wire)
            prism = face.extrude(App.Vector(0, 0, feature["height_mm"]))

            if feature.get("mode", "add") == "add":
                body_shape = prism if body_shape is None else body_shape.fuse(prism)
            else:
                body_shape = body_shape.cut(prism)

        elif feature["type"] == "linear_pattern_holes_z":
            if body_shape is None:
                raise RuntimeError("linear_pattern_holes_z requires a body before it")
            sx, sy = feature["start_mm"]
            dx, dy = feature["spacing_mm"]
            radius = feature["diameter_mm"] / 2.0
            for i in range(feature["count"]):
                cx = sx + dx * i
                cy = sy + dy * i
                cutter = Part.makeCylinder(
                    radius,
                    body_shape.BoundBox.ZLength + 2,
                    App.Vector(cx, cy, body_shape.BoundBox.ZMin - 1),
                    App.Vector(0, 0, 1),
                )
                body_shape = body_shape.cut(cutter)

        elif feature["type"] == "rectangular_pattern_holes_z":
            if body_shape is None:
                raise RuntimeError("rectangular_pattern_holes_z requires a body before it")
            ox, oy = feature["origin_mm"]
            radius = feature["diameter_mm"] / 2.0
            for ix in range(feature["x_count"]):
                for iy in range(feature["y_count"]):
                    cx = ox + feature["x_spacing_mm"] * ix
                    cy = oy + feature["y_spacing_mm"] * iy
                    cutter = Part.makeCylinder(
                        radius,
                        (body_height or 1) + 2,
                        App.Vector(cx, cy, body_min_z - 1),
                        App.Vector(0, 0, 1),
                    )
                    body_shape = body_shape.cut(cutter)

        elif feature["type"] == "rib_web_z":
            if body_shape is None:
                raise RuntimeError("rib_web_z requires a body before it")
            import math
            x1, y1 = feature["start_mm"]
            x2, y2 = feature["end_mm"]
            dx = x2 - x1
            dy = y2 - y1
            length = math.hypot(dx, dy)
            if length <= 0:
                raise RuntimeError("rib_web_z start and end cannot be the same point")
            nx = -dy / length
            ny = dx / length
            half = feature["thickness_mm"] / 2.0
            z = feature["base_z_mm"]
            pts = [
                App.Vector(x1 + nx * half, y1 + ny * half, z),
                App.Vector(x2 + nx * half, y2 + ny * half, z),
                App.Vector(x2 - nx * half, y2 - ny * half, z),
                App.Vector(x1 - nx * half, y1 - ny * half, z),
                App.Vector(x1 + nx * half, y1 + ny * half, z),
            ]
            wire = Part.makePolygon(pts)
            face = Part.Face(wire)
            rib = face.extrude(App.Vector(0, 0, feature["height_mm"]))
            body_shape = body_shape.fuse(rib)

        elif feature["type"] == "sphere_z":
            cx, cy = feature["center_mm"]
            sphere = Part.makeSphere(
                feature["radius_mm"],
                App.Vector(cx, cy, feature["center_z_mm"]),
            )
            if feature.get("mode", "add") == "add":
                body_shape = sphere if body_shape is None else body_shape.fuse(sphere)
            else:
                if body_shape is None:
                    raise RuntimeError("sphere_z cut requires a body before it")
                body_shape = body_shape.cut(sphere)

        elif feature["type"] == "hemisphere_dome_z":
            if body_shape is None and feature.get("mode", "add") == "cut":
                raise RuntimeError("hemisphere_dome_z cut requires a body before it")
            cx, cy = feature["center_mm"]
            r = feature["radius_mm"]
            base_z = feature["base_z_mm"]
            sphere = Part.makeSphere(r, App.Vector(cx, cy, base_z))
            clip = Part.makeBox(
                r * 2.4,
                r * 2.4,
                r * 1.2,
                App.Vector(cx - r * 1.2, cy - r * 1.2, base_z),
            )
            dome = sphere.common(clip)
            if feature.get("mode", "add") == "add":
                body_shape = dome if body_shape is None else body_shape.fuse(dome)
            else:
                body_shape = body_shape.cut(dome)

        elif feature["type"] == "spherical_cap_z":
            if body_shape is None and feature.get("mode", "add") == "cut":
                raise RuntimeError("spherical_cap_z cut requires a body before it")
            cx, cy = feature["center_mm"]
            r = feature["radius_mm"]
            h = feature["cap_height_mm"]
            base_z = feature["base_z_mm"]
            sphere_center_z = base_z + h - r
            sphere = Part.makeSphere(r, App.Vector(cx, cy, sphere_center_z))
            clip = Part.makeBox(
                r * 2.4,
                r * 2.4,
                h,
                App.Vector(cx - r * 1.2, cy - r * 1.2, base_z),
            )
            cap = sphere.common(clip)
            if feature.get("mode", "add") == "add":
                body_shape = cap if body_shape is None else body_shape.fuse(cap)
            else:
                body_shape = body_shape.cut(cap)

        elif feature["type"] == "ogive_z":
            if body_shape is None and feature.get("mode", "add") == "cut":
                raise RuntimeError("ogive_z cut requires a body before it")
            cx, cy = feature["center_mm"]
            base_r = feature["base_diameter_mm"] / 2.0
            tip_r = feature["tip_diameter_mm"] / 2.0
            ogive = Part.makeCone(
                base_r,
                tip_r,
                feature["height_mm"],
                App.Vector(cx, cy, feature["base_z_mm"]),
                App.Vector(0, 0, 1),
            )
            if feature.get("mode", "add") == "add":
                body_shape = ogive if body_shape is None else body_shape.fuse(ogive)
            else:
                body_shape = body_shape.cut(ogive)

        elif feature["type"] in ("straight_groove_z", "keyway_slot_z"):
            if body_shape is None:
                raise RuntimeError(feature["type"] + " requires a body before it")
            import math
            cx, cy = feature["center_mm"]
            length = feature["length_mm"]
            width = feature["width_mm"]
            depth = feature["depth_mm"]
            top_z = feature["base_z_mm"]
            angle = math.radians(feature["angle_deg"])
            dx = math.cos(angle)
            dy = math.sin(angle)
            px = -dy
            py = dx
            pts = [
                App.Vector(cx - dx * length / 2 - px * width / 2, cy - dy * length / 2 - py * width / 2, top_z - depth),
                App.Vector(cx + dx * length / 2 - px * width / 2, cy + dy * length / 2 - py * width / 2, top_z - depth),
                App.Vector(cx + dx * length / 2 + px * width / 2, cy + dy * length / 2 + py * width / 2, top_z - depth),
                App.Vector(cx - dx * length / 2 + px * width / 2, cy - dy * length / 2 + py * width / 2, top_z - depth),
                App.Vector(cx - dx * length / 2 - px * width / 2, cy - dy * length / 2 - py * width / 2, top_z - depth),
            ]
            cutter = Part.Face(Part.makePolygon(pts)).extrude(App.Vector(0, 0, depth + 1))
            body_shape = body_shape.cut(cutter)

        elif feature["type"] == "v_groove_z":
            if body_shape is None:
                raise RuntimeError("v_groove_z requires a body before it")
            import math
            cx, cy = feature["center_mm"]
            length = feature["length_mm"]
            width = feature["top_width_mm"]
            depth = feature["depth_mm"]
            top_z = feature["base_z_mm"]
            angle = math.radians(feature["angle_deg"])
            dx = math.cos(angle)
            dy = math.sin(angle)
            px = -dy
            py = dx

            p1 = App.Vector(cx - dx * length / 2 - px * width / 2, cy - dy * length / 2 - py * width / 2, top_z)
            p2 = App.Vector(cx + dx * length / 2 - px * width / 2, cy + dy * length / 2 - py * width / 2, top_z)
            p3 = App.Vector(cx + dx * length / 2 + px * width / 2, cy + dy * length / 2 + py * width / 2, top_z)
            p4 = App.Vector(cx - dx * length / 2 + px * width / 2, cy - dy * length / 2 + py * width / 2, top_z)
            c1 = App.Vector(cx - dx * length / 2, cy - dy * length / 2, top_z - depth)
            c2 = App.Vector(cx + dx * length / 2, cy + dy * length / 2, top_z - depth)

            cutter = Part.makeShell([
                Part.Face(Part.makePolygon([p1, p2, c2, c1, p1])),
                Part.Face(Part.makePolygon([p4, c1, c2, p3, p4])),
                Part.Face(Part.makePolygon([p1, c1, p4, p1])),
                Part.Face(Part.makePolygon([p2, p3, c2, p2])),
                Part.Face(Part.makePolygon([p1, p4, p3, p2, p1])),
            ])
            cutter = Part.Solid(cutter)
            body_shape = body_shape.cut(cutter)

        elif feature["type"] == "dovetail_slot_z":
            if body_shape is None:
                raise RuntimeError("dovetail_slot_z requires a body before it")
            import math
            cx, cy = feature["center_mm"]
            length = feature["length_mm"]
            top_w = feature["top_width_mm"]
            bottom_w = feature["bottom_width_mm"]
            depth = feature["depth_mm"]
            top_z = feature["base_z_mm"]
            angle = math.radians(feature["angle_deg"])
            dx = math.cos(angle)
            dy = math.sin(angle)
            px = -dy
            py = dx

            top1 = App.Vector(cx - dx * length / 2 - px * top_w / 2, cy - dy * length / 2 - py * top_w / 2, top_z)
            top2 = App.Vector(cx + dx * length / 2 - px * top_w / 2, cy + dy * length / 2 - py * top_w / 2, top_z)
            top3 = App.Vector(cx + dx * length / 2 + px * top_w / 2, cy + dy * length / 2 + py * top_w / 2, top_z)
            top4 = App.Vector(cx - dx * length / 2 + px * top_w / 2, cy - dy * length / 2 + py * top_w / 2, top_z)

            bot1 = App.Vector(cx - dx * length / 2 - px * bottom_w / 2, cy - dy * length / 2 - py * bottom_w / 2, top_z - depth)
            bot2 = App.Vector(cx + dx * length / 2 - px * bottom_w / 2, cy + dy * length / 2 - py * bottom_w / 2, top_z - depth)
            bot3 = App.Vector(cx + dx * length / 2 + px * bottom_w / 2, cy + dy * length / 2 + py * bottom_w / 2, top_z - depth)
            bot4 = App.Vector(cx - dx * length / 2 + px * bottom_w / 2, cy - dy * length / 2 + py * bottom_w / 2, top_z - depth)

            cutter = Part.makeShell([
                Part.Face(Part.makePolygon([top1, top2, bot2, bot1, top1])),
                Part.Face(Part.makePolygon([top2, top3, bot3, bot2, top2])),
                Part.Face(Part.makePolygon([top3, top4, bot4, bot3, top3])),
                Part.Face(Part.makePolygon([top4, top1, bot1, bot4, top4])),
                Part.Face(Part.makePolygon([top1, top4, top3, top2, top1])),
                Part.Face(Part.makePolygon([bot1, bot2, bot3, bot4, bot1])),
            ])
            cutter = Part.Solid(cutter)
            body_shape = body_shape.cut(cutter)

        elif feature["type"] == "spline_path_z":
            # Metadata-only for now. This requires path sweep groove geometry before safe modeling.
            pass

        elif feature["type"] in ("involute_gear_external_z", "involute_gear_internal_z"):
            import sys
            GEAR_ROOT = "/media/shopai/Extra Space/Apps/FreeCAD/installed-addons/freecad.gears"
            if GEAR_ROOT not in sys.path:
                sys.path.insert(0, GEAR_ROOT)
            gear_freecad_path = GEAR_ROOT + "/freecad"
            if gear_freecad_path not in sys.path:
                sys.path.insert(0, gear_freecad_path)

            if feature["type"] == "involute_gear_external_z":
                import gears.involutegear as gearmod
                gear_class = gearmod.InvoluteGear
                gear_name = feature["id"]
            else:
                import gears.internalinvolutegear as gearmod
                gear_class = gearmod.InternalInvoluteGear
                gear_name = feature["id"]

            gear_obj = doc.addObject("Part::FeaturePython", gear_name)
            gear_class(gear_obj)

            gear_obj.num_teeth = feature["teeth"]
            gear_obj.module = feature["module_mm"]
            gear_obj.pressure_angle = feature["pressure_angle_deg"]
            gear_obj.height = feature["face_width_mm"]

            if feature.get("bore_diameter_mm", 0) > 0:
                if "axle_hole" in gear_obj.PropertiesList:
                    gear_obj.axle_hole = True
                if "axle_holesize" in gear_obj.PropertiesList:
                    gear_obj.axle_holesize = feature["bore_diameter_mm"]

            cx, cy = feature["center_mm"]
            gear_obj.Placement.Base = App.Vector(cx, cy, feature["base_z_mm"])

            doc.recompute()

            if not hasattr(gear_obj, "Shape") or gear_obj.Shape.isNull():
                raise RuntimeError("Gear feature did not generate a valid shape")

            gear_shape = gear_obj.Shape.copy()
            created.append(gear_obj)

            if body_shape is None:
                body_shape = gear_shape
            else:
                if feature["type"] == "involute_gear_external_z":
                    body_shape = body_shape.fuse(gear_shape)
                else:
                    body_shape = body_shape.cut(gear_shape)

        elif feature["type"] in ("thread_external_z", "thread_internal_z"):
            if feature.get("model_mode", "metadata") == "cylinder":
                cx, cy = feature["center_mm"]
                length = feature["thread_length_mm"]
                if feature["type"] == "thread_external_z":
                    radius = feature["major_diameter_mm"] / 2.0
                    cyl = Part.makeCylinder(radius, length, App.Vector(cx, cy, feature["base_z_mm"]), App.Vector(0, 0, 1))
                    body_shape = cyl if body_shape is None else body_shape.fuse(cyl)
                else:
                    if body_shape is None:
                        raise RuntimeError("thread_internal_z cylinder mode requires a body before it")
                    dia = feature["minor_diameter_mm"] if feature.get("minor_diameter_mm", 0) > 0 else feature["major_diameter_mm"] * 0.8
                    cutter = Part.makeCylinder(dia / 2.0, length + 2, App.Vector(cx, cy, feature["base_z_mm"] - 1), App.Vector(0, 0, 1))
                    body_shape = body_shape.cut(cutter)
            else:
                pass

        elif feature["type"] == "thread_relief_groove_z":
            if body_shape is None:
                raise RuntimeError("thread_relief_groove_z requires a body before it")
            cx, cy = feature["center_mm"]
            outer_r = feature["diameter_mm"] / 2.0
            inner_r = max(0.01, outer_r - feature["groove_depth_mm"])
            z = feature["base_z_mm"]
            width = feature["groove_width_mm"]
            outer = Part.makeCylinder(outer_r, width, App.Vector(cx, cy, z), App.Vector(0, 0, 1))
            inner = Part.makeCylinder(inner_r, width + 2, App.Vector(cx, cy, z - 1), App.Vector(0, 0, 1))
            ring_cutter = outer.cut(inner)
            if feature.get("orientation", "external") == "internal":
                body_shape = body_shape.fuse(ring_cutter)
            else:
                body_shape = body_shape.cut(ring_cutter)

        elif feature["type"] in ("thread_mill_path_metadata", "lathe_thread_metadata"):
            pass

        elif feature["type"] == "thread_metadata":
            # Metadata-only for now. Preserved in action/report, not modeled yet.
            pass

        else:
            raise RuntimeError("Unsupported feature type: " + feature["type"])

    if body_shape is None:
        raise RuntimeError("No solid body created")

    body_obj = doc.addObject("Part::Feature", SPEC["part_name"] + "_body")
    body_obj.Shape = body_shape
    created.append(body_obj)

    doc.recompute()

    if "FCStd" in SPEC["exports"]:
        report["stage"] = "save_fcstd"
        doc.saveAs(PATHS["fcstd"])
        report["outputs"]["fcstd"] = PATHS["fcstd"]

    if "STEP" in SPEC["exports"]:
        report["stage"] = "export_step"
        Part.export(created, PATHS["step"])
        report["outputs"]["step"] = PATHS["step"]

    projection_exports = {
        "SVG_TOP": ("svg_top", PATHS["svg_top"], App.Vector(0, 0, 1), "svg"),
        "DXF_TOP": ("dxf_top", PATHS["dxf_top"], App.Vector(0, 0, 1), "dxf"),
        "SVG_FRONT": ("svg_front", PATHS["svg_front"], App.Vector(0, -1, 0), "svg"),
        "DXF_FRONT": ("dxf_front", PATHS["dxf_front"], App.Vector(0, -1, 0), "dxf"),
        "SVG_RIGHT": ("svg_right", PATHS["svg_right"], App.Vector(1, 0, 0), "svg"),
        "DXF_RIGHT": ("dxf_right", PATHS["dxf_right"], App.Vector(1, 0, 0), "dxf"),
        "SVG_LEFT": ("svg_left", PATHS["svg_left"], App.Vector(-1, 0, 0), "svg"),
        "DXF_LEFT": ("dxf_left", PATHS["dxf_left"], App.Vector(-1, 0, 0), "dxf"),
        "SVG_BACK": ("svg_back", PATHS["svg_back"], App.Vector(0, 1, 0), "svg"),
        "DXF_BACK": ("dxf_back", PATHS["dxf_back"], App.Vector(0, 1, 0), "dxf"),
        "SVG_BOTTOM": ("svg_bottom", PATHS["svg_bottom"], App.Vector(0, 0, -1), "svg"),
        "DXF_BOTTOM": ("dxf_bottom", PATHS["dxf_bottom"], App.Vector(0, 0, -1), "dxf"),
    }

    if any(key in SPEC["exports"] for key in projection_exports):
        report["stage"] = "project_views"
        for export_key, (label, path, direction, fmt) in projection_exports.items():
            if export_key not in SPEC["exports"]:
                continue
            if fmt == "svg":
                content = TechDraw.projectToSVG(body_obj.Shape, direction)
            else:
                content = TechDraw.projectToDXF(body_obj.Shape, direction)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            report["outputs"][label] = path

    report["stage"] = "verify_outputs"
    for label, path in report["outputs"].items():
        report["checks"][label + "_exists"] = os.path.exists(path)
        report["checks"][label + "_size"] = os.path.getsize(path) if os.path.exists(path) else 0
        if not report["checks"][label + "_exists"]:
            raise RuntimeError(label + " output missing")

    report["ok"] = True
    report["stage"] = "done"

except Exception:
    report["error"] = traceback.format_exc()

finally:
    with open(PATHS["report"], "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(json.dumps(report, indent=2))
    sys.exit(0 if report["ok"] else 1)
'''

    job = job.replace("__SPEC_JSON__", json.dumps(spec, indent=2))
    job = job.replace("__PATHS_JSON__", json.dumps(paths, indent=2))
    script_path.write_text(job, encoding="utf-8")

    cmd = [str(FREECADCMD), "--safe-mode", str(script_path)]

    with open(stdout_path, "w", encoding="utf-8") as out, open(stderr_path, "w", encoding="utf-8") as err:
        completed = subprocess.run(cmd, stdout=out, stderr=err, text=True)

    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    else:
        report = {"ok": False, "error": "FreeCAD did not create report.json"}

    final = {
        "ok": completed.returncode == 0 and report.get("ok") is True,
        "action": spec,
        "run_name": run_name,
        "output_dir": str(outdir),
        "report": report,
        "logs": {
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
        },
        "returncode": completed.returncode,
    }

    summary_path = outdir / "bridge_summary.json"
    summary_path.write_text(json.dumps(final, indent=2), encoding="utf-8")
    print(json.dumps(final, indent=2))

    if not final["ok"]:
        sys.exit(1)


def main():
    if len(sys.argv) != 2:
        fail("Usage: bridge_runner.py ACTION_JSON")

    if not FREECADCMD.exists():
        fail(f"freecadcmd not found: {FREECADCMD}")

    action = load_action(sys.argv[1])
    spec = validate_action(action)
    run_freecad(spec)


if __name__ == "__main__":
    main()
