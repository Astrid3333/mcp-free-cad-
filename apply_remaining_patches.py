#!/usr/bin/env python3
"""
Fixes the two remaining gaps for the 7 new FreeCAD MCP tools
(compliant_ops, tendon_routing_ops, contact_pressure_ops, growth_socket_ops,
quick_connect_ops, fitting_history_ops, lightweight_ops):

  1. AICopilot/freecad_mcp_handler.py — the TOP-LEVEL startup import block
     (the one FreeCAD actually runs on cold boot, not the hot-reload block)
     is missing the 7 new handler class imports. Without this, cold boot
     raises NameError the moment it tries `self.compliant_ops = CompliantOpsHandler(...)`.

  2. freecad_mcp_server.py — no Tool() schemas or dispatch-list entries
     exist yet for the 7 new operation names. This adds both.

Idempotent: each patch checks whether it's already applied and skips if so.
Run with --dry-run first. Backs up every file it touches before writing.
"""

import argparse
import re
import shutil
import time
from pathlib import Path

BASE = Path.home() / "mcp-free-cad-"
HANDLER_PY = BASE / "AICopilot" / "freecad_mcp_handler.py"
SERVER_PY = BASE / "freecad_mcp_server.py"

NEW_HANDLER_NAMES = [
    "CompliantOpsHandler",
    "TendonRoutingHandler",
    "ContactPressureOpsHandler",
    "GrowthSocketOpsHandler",
    "QuickConnectOpsHandler",
    "FittingHistoryOpsHandler",
    "LightweightOpsHandler",
]

NEW_OP_NAMES = [
    "compliant_operations",
    "tendon_routing_operations",
    "contact_pressure_operations",
    "growth_socket_operations",
    "quick_connect_operations",
    "fitting_history_operations",
    "lightweight_operations",
]


def backup(path: Path):
    bak = path.with_name(path.name + f".bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(path, bak)
    print(f"  backed up -> {bak.name}")


# ---------------------------------------------------------------------------
# Patch 1: freecad_mcp_handler.py top-level startup import block
# ---------------------------------------------------------------------------
def patch_handler_import(text: str) -> tuple[str, bool]:
    if all(name in text.split("FreeCAD.Console.PrintMessage(\"Modular handlers loaded")[0] for name in NEW_HANDLER_NAMES):
        return text, False  # already patched

    anchor = (
        "        SketchBuilderOpsHandler,\n"
        "        VerificationOpsHandler,\n"
        "        FixtureOpsHandler,\n"
        "    )\n"
        "    FreeCAD.Console.PrintMessage(\"Modular handlers loaded successfully\\n\")\n"
    )
    count = text.count(anchor)
    assert count == 1, f"[handler top-import] anchor found {count}x, expected 1"

    insert = "".join(f"        {name},\n" for name in NEW_HANDLER_NAMES)
    new_anchor = anchor.replace(
        "        FixtureOpsHandler,\n    )",
        "        FixtureOpsHandler,\n" + insert + "    )",
    )
    return text.replace(anchor, new_anchor), True


# ---------------------------------------------------------------------------
# Patch 2: freecad_mcp_server.py — Tool() schemas
# ---------------------------------------------------------------------------
TOOL_SCHEMAS = r'''
                types.Tool(
                    name="compliant_operations",
                    description=(
                        "Living-hinge / compliant-joint generation for prosthetic mechanisms. "
                        "recommend_hinge_thickness: material+cycle-derated thickness estimate. "
                        "create_living_hinge: cut a reduced-section hinge across a solid. "
                        "create_flexure_array: a row of hinges (segmented compliant finger)."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "operation": {"type": "string", "enum": [
                                "recommend_hinge_thickness", "create_living_hinge", "create_flexure_array"]},
                            "material": {"type": "string", "enum": ["petg", "tpu", "pla"], "default": "tpu"},
                            "flex_angle_deg": {"type": "number", "default": 90.0},
                            "hinge_length_mm": {"type": "number", "default": 10.0},
                            "expected_cycles": {"type": "integer", "default": 10000},
                            "shape": {"type": "string", "description": "Object to cut the hinge into"},
                            "position_mm": {"type": "array", "items": {"type": "number"}},
                            "axis": {"type": "string", "enum": ["x", "y", "z"], "default": "z"},
                            "thickness_mm": {"type": "number", "default": 0.8},
                            "width_mm": {"type": "number", "default": 10.0},
                            "name": {"type": "string"},
                            "start_mm": {"type": "array", "items": {"type": "number"}},
                            "end_mm": {"type": "array", "items": {"type": "number"}},
                            "count": {"type": "integer", "default": 3},
                        },
                        "required": ["operation"],
                    },
                    annotations=types.ToolAnnotations(readOnlyHint=False, destructiveHint=True),
                ),

                types.Tool(
                    name="tendon_routing_operations",
                    description=(
                        "Geometric tendon-path planning and clearance checks for tendon-driven "
                        "prosthetic joints. compute_anchor_points: offset anchors from a joint chain. "
                        "check_tendon_curvature: verify bend radius against cable minimums. "
                        "check_tendon_path_clearance: sample a straight segment for collisions with solid material."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "operation": {"type": "string", "enum": [
                                "compute_anchor_points", "check_tendon_curvature", "check_tendon_path_clearance"]},
                            "joint_positions_mm": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
                            "segment_radii_mm": {"type": "array", "items": {"type": "number"}},
                            "offset_fraction": {"type": "number", "default": 0.8},
                            "anchor_points_mm": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
                            "cable_type": {"type": "string", "enum": [
                                "fishing_line_20lb", "fishing_line_50lb", "paracord_thin",
                                "steel_cable_1mm", "dyneema_1mm"]},
                            "min_bend_radius_mm": {"type": "number"},
                            "shape": {"type": "string"},
                            "point_a_mm": {"type": "array", "items": {"type": "number"}},
                            "point_b_mm": {"type": "array", "items": {"type": "number"}},
                            "samples": {"type": "integer", "default": 10},
                        },
                        "required": ["operation"],
                    },
                    annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False),
                ),

                types.Tool(
                    name="contact_pressure_operations",
                    description=(
                        "Geometric proxy analysis for socket-to-limb contact/fit quality (NOT FEA "
                        "or clinical pressure mapping — a first-pass screen). sample_socket_clearance: "
                        "grid-sample the socket's inner surface against a limb model. "
                        "summarize_pressure_zones: cluster flagged samples into actionable problem zones."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "operation": {"type": "string", "enum": [
                                "sample_socket_clearance", "summarize_pressure_zones"]},
                            "socket_shape": {"type": "string"},
                            "limb_model_shape": {"type": "string"},
                            "samples_per_face": {"type": "integer", "default": 5},
                            "inner_face_indices": {"type": "array", "items": {"type": "integer"}},
                            "samples": {"type": "array", "items": {"type": "object"},
                                        "description": "Output of sample_socket_clearance, passed to summarize_pressure_zones"},
                            "cluster_radius_mm": {"type": "number", "default": 5.0},
                            "risk_levels": {"type": "array", "items": {"type": "string"},
                                            "default": ["overlap", "high_pressure"]},
                        },
                        "required": ["operation"],
                    },
                    annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False),
                ),

                types.Tool(
                    name="growth_socket_operations",
                    description=(
                        "Telescoping / nested-liner pediatric socket generation. create_outer_shell: "
                        "fixed shell sized to accept the largest liner plus clearance. "
                        "create_liner_family: a size family of liner inserts from one base profile."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "operation": {"type": "string", "enum": [
                                "create_outer_shell", "create_liner_family"]},
                            "profile_sketch": {"type": "string"},
                            "length_mm": {"type": "number", "default": 120.0},
                            "max_liner_offset_mm": {"type": "number", "default": 6.0},
                            "wall_thickness_mm": {"type": "number", "default": 3.0},
                            "clearance_mm": {"type": "number", "default": 0.3},
                            "name": {"type": "string"},
                            "growth_offsets_mm": {"type": "array", "items": {"type": "number"}, "default": [0, 2, 4, 6]},
                            "liner_thickness_mm": {"type": "number", "default": 2.0},
                            "name_prefix": {"type": "string"},
                        },
                        "required": ["operation", "profile_sketch"],
                    },
                    annotations=types.ToolAnnotations(readOnlyHint=False, destructiveHint=True),
                ),

                types.Tool(
                    name="quick_connect_operations",
                    description=(
                        "Parametric socket-to-terminal-device quick-connect interfaces. "
                        "list_connector_presets: built-in presets. create_bayonet_pair / "
                        "create_threaded_pair: matched male/female halves. "
                        "add_magnetic_retention: retention-aid recesses on an existing pair "
                        "(does not replace the mechanical lock)."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "operation": {"type": "string", "enum": [
                                "list_connector_presets", "create_bayonet_pair",
                                "create_threaded_pair", "add_magnetic_retention"]},
                            "diameter_mm": {"type": "number"},
                            "lug_count": {"type": "integer", "default": 3},
                            "lug_length_mm": {"type": "number", "default": 6.0},
                            "lug_thickness_mm": {"type": "number", "default": 2.0},
                            "lug_travel_deg": {"type": "number", "default": 30.0},
                            "barrel_length_mm": {"type": "number", "default": 15.0},
                            "male_position_mm": {"type": "array", "items": {"type": "number"}},
                            "female_position_mm": {"type": "array", "items": {"type": "number"}},
                            "name_prefix": {"type": "string"},
                            "pitch_mm": {"type": "number", "default": 2.0},
                            "length_mm": {"type": "number", "default": 15.0},
                            "male_shape": {"type": "string"},
                            "female_shape": {"type": "string"},
                            "magnet_diameter_mm": {"type": "number", "default": 6.0},
                            "magnet_thickness_mm": {"type": "number", "default": 2.0},
                            "position_mm": {"type": "array", "items": {"type": "number"}},
                            "name_suffix": {"type": "string"},
                        },
                        "required": ["operation"],
                    },
                    annotations=types.ToolAnnotations(readOnlyHint=False, destructiveHint=True),
                ),

                types.Tool(
                    name="fitting_history_operations",
                    description=(
                        "Session-log layer over save_fixture/compare_to_fixture for tracking "
                        "prosthetic socket-fitting iterations per patient over time. "
                        "log_fitting_session: snapshot geometry + append structured session notes. "
                        "get_fitting_history: full logged history for a patient_id. "
                        "compare_to_last_fitting: geometric diff against the most recent session. "
                        "patient_id must be a non-identifying code (initials + number), never PII."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "operation": {"type": "string", "enum": [
                                "log_fitting_session", "get_fitting_history", "compare_to_last_fitting"]},
                            "shape": {"type": "string"},
                            "patient_id": {"type": "string", "description": "Non-identifying code, alphanumerics/underscores/hyphens only"},
                            "session_notes": {"type": "string"},
                            "pressure_complaints": {"type": "array", "items": {"type": "string"}},
                            "donning_time_sec": {"type": "number"},
                            "fit_rating": {"type": "integer", "description": "Subjective fit rating 1-5"},
                        },
                        "required": ["operation"],
                    },
                    annotations=types.ToolAnnotations(readOnlyHint=False, destructiveHint=False),
                ),

                types.Tool(
                    name="lightweight_operations",
                    description=(
                        "Load-guided infill/lattice density recommendations for reducing prosthetic "
                        "part weight. Geometric proxy screening, NOT a structural solver — validate "
                        "any load-bearing print with a physical test. recommend_density_map: grid "
                        "cells scored by proximity to an approximate load path. "
                        "estimate_weight_savings: solid-vs-lightweighted weight estimate."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "operation": {"type": "string", "enum": [
                                "recommend_density_map", "estimate_weight_savings"]},
                            "shape": {"type": "string"},
                            "load_start_mm": {"type": "array", "items": {"type": "number"}},
                            "load_end_mm": {"type": "array", "items": {"type": "number"}},
                            "axis_divisions": {"type": "integer", "default": 6},
                            "cross_divisions": {"type": "integer", "default": 3},
                            "cells": {"type": "array", "items": {"type": "object"},
                                      "description": "Output of recommend_density_map, passed to estimate_weight_savings"},
                            "material_density_g_cm3": {"type": "number", "default": 1.24},
                        },
                        "required": ["operation", "shape"],
                    },
                    annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False),
                ),
'''


def patch_server_tools(text: str) -> tuple[str, bool]:
    if "name=\"compliant_operations\"" in text:
        return text, False  # already patched

    pattern = re.compile(r'\n( *)\]\n( *)return base_tools \+ smart_dispatchers\n')
    matches = list(pattern.finditer(text))
    assert len(matches) == 1, f"[server tools] closing anchor found {len(matches)}x, expected 1"
    m = matches[0]
    insert_at = m.start() + 1
    new_text = text[:insert_at] + TOOL_SCHEMAS + text[insert_at:]
    return new_text, True


def patch_server_dispatch(text: str) -> tuple[str, bool]:
    if '"compliant_operations"' in text.split("smart_dispatchers")[-1] or '"compliant_operations", "tendon_routing_operations"' in text:
        return text, False  # already patched

    anchor = '"organic_operations", "surface_operations", "fillet_chamfer"]:'
    count = text.count(anchor)
    assert count == 1, f"[server dispatch] anchor found {count}x, expected 1"

    new_names = ", ".join(f'"{n}"' for n in NEW_OP_NAMES)
    replacement = (
        '"organic_operations", "surface_operations", "fillet_chamfer",\n'
        f'                      {new_names}]:'
    )
    return text.replace(anchor, replacement), True


def run(dry_run: bool):
    print("=== freecad_mcp_handler.py: top-level import fix ===")
    handler_text = HANDLER_PY.read_text()
    new_handler_text, changed1 = patch_handler_import(handler_text)
    print("  needs patch:", changed1)

    print("=== freecad_mcp_server.py: Tool schemas ===")
    server_text = SERVER_PY.read_text()
    new_server_text, changed2 = patch_server_tools(server_text)
    print("  needs patch:", changed2)

    print("=== freecad_mcp_server.py: dispatch list ===")
    new_server_text, changed3 = patch_server_dispatch(new_server_text)
    print("  needs patch:", changed3)

    if dry_run:
        print("\n--dry-run: no files written.")
        return

    if changed1:
        backup(HANDLER_PY)
        HANDLER_PY.write_text(new_handler_text)
        print(f"wrote {HANDLER_PY}")

    if changed2 or changed3:
        backup(SERVER_PY)
        SERVER_PY.write_text(new_server_text)
        print(f"wrote {SERVER_PY}")

    if not (changed1 or changed2 or changed3):
        print("\nNothing to do — both files already fully patched.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(args.dry_run)
