#!/usr/bin/env python3
"""
Parchea mcp-free-cad- para exponer los 7 handlers nuevos:
  compliant_ops, tendon_routing_ops, contact_pressure_ops,
  growth_socket_ops, quick_connect_ops, fitting_history_ops, lightweight_ops

Toca 3 archivos:
  1. AICopilot/handlers/__init__.py       (imports + __all__)
  2. AICopilot/freecad_mcp_handler.py     (instanciacion x2, dispatch dict,
                                            reload module list, reload import)
  3. freecad_mcp_server.py                (7 Tool() + dispatch elif list)

Uso:
    python3 apply_7_tools_patch.py            # aplica el patch
    python3 apply_7_tools_patch.py --dry-run  # solo valida, no escribe nada

Cada paso hace backup con timestamp antes de escribir, y cada anchor se
verifica con assert de conteo exacto antes de tocar nada. Si algun anchor
no aparece exactamente donde se espera, el script aborta sin modificar
ese archivo (los archivos ya escritos en pasos previos quedan con backup
al lado, asi que siempre podes revertir con el .bak-<timestamp> mas reciente).
"""
import sys
import re
from datetime import datetime
from pathlib import Path

DRY_RUN = "--dry-run" in sys.argv

BASE = Path.home() / "mcp-free-cad-"
AICOPILOT = BASE / "AICopilot"
INIT_PY = AICOPILOT / "handlers" / "__init__.py"
HANDLER_PY = AICOPILOT / "freecad_mcp_handler.py"
SERVER_PY = BASE / "freecad_mcp_server.py"

for p in (INIT_PY, HANDLER_PY, SERVER_PY):
    if not p.is_file():
        sys.exit(f"ERROR: no encuentro {p}")


def backup(path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = path.with_name(path.name + f".bak-{ts}")
    bak.write_text(path.read_text())
    return bak


def apply_unique(text: str, anchor: str, build_replacement, label: str) -> str:
    """anchor debe aparecer EXACTAMENTE una vez en text. build_replacement(anchor)->str."""
    count = text.count(anchor)
    assert count == 1, f"[{label}] anchor aparece {count} veces (esperaba 1): {anchor[:80]!r}..."
    return text.replace(anchor, build_replacement(anchor), 1)


# ---------------------------------------------------------------------------
# 1. handlers/__init__.py
# ---------------------------------------------------------------------------

NEW_IMPORTS = (
    "from .compliant_ops import CompliantOpsHandler\n"
    "from .tendon_routing_ops import TendonRoutingHandler\n"
    "from .contact_pressure_ops import ContactPressureOpsHandler\n"
    "from .growth_socket_ops import GrowthSocketOpsHandler\n"
    "from .quick_connect_ops import QuickConnectOpsHandler\n"
    "from .fitting_history_ops import FittingHistoryOpsHandler\n"
    "from .lightweight_ops import LightweightOpsHandler\n"
)

NEW_ALL_ENTRIES = (
    "    'CompliantOpsHandler',\n"
    "    'TendonRoutingHandler',\n"
    "    'ContactPressureOpsHandler',\n"
    "    'GrowthSocketOpsHandler',\n"
    "    'QuickConnectOpsHandler',\n"
    "    'FittingHistoryOpsHandler',\n"
    "    'LightweightOpsHandler',\n"
)

init_text = INIT_PY.read_text()

init_text = apply_unique(
    init_text,
    "from .fixture_ops import FixtureOpsHandler\n",
    lambda a: a + NEW_IMPORTS,
    "init.py imports",
)

init_text = apply_unique(
    init_text,
    "    'FixtureOpsHandler',\n]",
    lambda a: "    'FixtureOpsHandler',\n" + NEW_ALL_ENTRIES + "]",
    "init.py __all__",
)

# ---------------------------------------------------------------------------
# 2. freecad_mcp_handler.py
# ---------------------------------------------------------------------------

handler_text = HANDLER_PY.read_text()

# 2a. Instanciacion principal (dentro de __init__, seguida del comentario
#     "GUI-sensitive handlers..." que solo aparece ahi, no en el bloque reload)
MAIN_INSTANTIATION_NEW = (
    "        self.compliant_ops = CompliantOpsHandler(self, _log_operation, _capture_state)\n"
    "        self.tendon_routing_ops = TendonRoutingHandler(self, _log_operation, _capture_state)\n"
    "        self.contact_pressure_ops = ContactPressureOpsHandler(self, _log_operation, _capture_state)\n"
    "        self.growth_socket_ops = GrowthSocketOpsHandler(self, _log_operation, _capture_state)\n"
    "        self.quick_connect_ops = QuickConnectOpsHandler(self, _log_operation, _capture_state)\n"
    "        self.fitting_history_ops = FittingHistoryOpsHandler(self, _log_operation, _capture_state)\n"
    "        self.lightweight_ops = LightweightOpsHandler(self, _log_operation, _capture_state)\n"
)

handler_text = apply_unique(
    handler_text,
    "        self.fixture_ops = FixtureOpsHandler(self, _log_operation, _capture_state)\n"
    "        # GUI-sensitive handlers get the task queues for thread safety\n",
    lambda a: (
        "        self.fixture_ops = FixtureOpsHandler(self, _log_operation, _capture_state)\n"
        + MAIN_INSTANTIATION_NEW
        + "        # GUI-sensitive handlers get the task queues for thread safety\n"
    ),
    "handler.py main __init__ instantiation",
)

# 2b. generic_dispatch_map
DISPATCH_ENTRIES_NEW = (
    '            "compliant_operations": self.compliant_ops,\n'
    '            "tendon_routing_operations": self.tendon_routing_ops,\n'
    '            "contact_pressure_operations": self.contact_pressure_ops,\n'
    '            "growth_socket_operations": self.growth_socket_ops,\n'
    '            "quick_connect_operations": self.quick_connect_ops,\n'
    '            "fitting_history_operations": self.fitting_history_ops,\n'
    '            "lightweight_operations": self.lightweight_ops,\n'
)

handler_text = apply_unique(
    handler_text,
    '            "fixture_operations": self.fixture_ops,\n        }',
    lambda a: (
        '            "fixture_operations": self.fixture_ops,\n'
        + DISPATCH_ENTRIES_NEW
        + "        }"
    ),
    "handler.py generic_dispatch_map",
)

# 2c. handler_modules reload list
RELOAD_MODULES_NEW = (
    "                'handlers.compliant_ops',\n"
    "                'handlers.tendon_routing_ops',\n"
    "                'handlers.contact_pressure_ops',\n"
    "                'handlers.growth_socket_ops',\n"
    "                'handlers.quick_connect_ops',\n"
    "                'handlers.fitting_history_ops',\n"
    "                'handlers.lightweight_ops',\n"
)

handler_text = apply_unique(
    handler_text,
    "                'handlers.fixture_ops',\n            ]",
    lambda a: (
        "                'handlers.fixture_ops',\n"
        + RELOAD_MODULES_NEW
        + "            ]"
    ),
    "handler.py handler_modules reload list",
)

# 2d. reimport block "from handlers import (...)"
REIMPORT_NEW = (
    "                FixtureOpsHandler,\n"
    "                CompliantOpsHandler,\n"
    "                TendonRoutingHandler,\n"
    "                ContactPressureOpsHandler,\n"
    "                GrowthSocketOpsHandler,\n"
    "                QuickConnectOpsHandler,\n"
    "                FittingHistoryOpsHandler,\n"
    "                LightweightOpsHandler,\n"
    "            )"
)

handler_text = apply_unique(
    handler_text,
    "                FixtureOpsHandler,\n            )",
    lambda a: REIMPORT_NEW,
    "handler.py reimport block",
)

# 2e. Reinstanciacion en el bloque reload (sin el comentario GUI-sensitive,
#     seguida directo de self.view_ops = ViewOpsHandler( con indent de 12)
RELOAD_INSTANTIATION_NEW = (
    "            self.compliant_ops = CompliantOpsHandler(self, _log_operation, _capture_state)\n"
    "            self.tendon_routing_ops = TendonRoutingHandler(self, _log_operation, _capture_state)\n"
    "            self.contact_pressure_ops = ContactPressureOpsHandler(self, _log_operation, _capture_state)\n"
    "            self.growth_socket_ops = GrowthSocketOpsHandler(self, _log_operation, _capture_state)\n"
    "            self.quick_connect_ops = QuickConnectOpsHandler(self, _log_operation, _capture_state)\n"
    "            self.fitting_history_ops = FittingHistoryOpsHandler(self, _log_operation, _capture_state)\n"
    "            self.lightweight_ops = LightweightOpsHandler(self, _log_operation, _capture_state)\n"
)

handler_text = apply_unique(
    handler_text,
    "            self.fixture_ops = FixtureOpsHandler(self, _log_operation, _capture_state)\n"
    "            self.view_ops = ViewOpsHandler(\n",
    lambda a: (
        "            self.fixture_ops = FixtureOpsHandler(self, _log_operation, _capture_state)\n"
        + RELOAD_INSTANTIATION_NEW
        + "            self.view_ops = ViewOpsHandler(\n"
    ),
    "handler.py reload-block instantiation",
)

# ---------------------------------------------------------------------------
# 3. freecad_mcp_server.py
# ---------------------------------------------------------------------------

server_text = SERVER_PY.read_text()

NEW_TOOLS_BLOCK = '''
                types.Tool(
                    name="compliant_operations",
                    description=(
                        "Compliant-mechanism (living-hinge / flexure) generation for "
                        "print-in-place prosthetic joints — replaces pin-and-pivot joints "
                        "that wear and jam. recommend_hinge_thickness computes a starting "
                        "thickness from material, flex angle, and expected cycle count. "
                        "create_living_hinge cuts a reduced-section hinge across an "
                        "existing solid. create_flexure_array places a row of hinges "
                        "along a line for a segmented compliant finger. "
                        "Always validate with a physical fatigue sample before clinical use."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "operation": {
                                "type": "string",
                                "enum": ["recommend_hinge_thickness", "create_living_hinge",
                                         "create_flexure_array"],
                                "description": (
                                    "recommend_hinge_thickness: suggest thickness (mm) from "
                                    "material/flex_angle_deg/hinge_length_mm/expected_cycles. "
                                    "create_living_hinge: cut a single hinge into shape. "
                                    "create_flexure_array: cut a row of count hinges between "
                                    "start_mm and end_mm."
                                )
                            },
                            "material": {
                                "type": "string",
                                "enum": ["petg", "tpu", "pla"],
                                "description": "Material for recommend_hinge_thickness (default 'tpu').",
                                "default": "tpu"
                            },
                            "flex_angle_deg": {"type": "number", "description": "Total bend angle in degrees", "default": 90.0},
                            "hinge_length_mm": {"type": "number", "description": "Hinge length along the bend axis", "default": 10.0},
                            "expected_cycles": {"type": "integer", "description": "Expected flex-cycle count", "default": 10000},
                            "shape": {"type": "string", "description": "Object name to cut the hinge(s) into"},
                            "position_mm": {
                                "type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                                "description": "Center point [x,y,z] of a single hinge cut (create_living_hinge)"
                            },
                            "axis": {
                                "type": "string", "enum": ["x", "y", "z"], "default": "z",
                                "description": "Bend axis — hinge cut runs perpendicular to this axis"
                            },
                            "thickness_mm": {"type": "number", "description": "Remaining material thickness at the hinge", "default": 0.8},
                            "width_mm": {"type": "number", "description": "Width of the hinge cut across the part", "default": 10.0},
                            "name": {"type": "string", "description": "Name for the resulting feature"},
                            "start_mm": {
                                "type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                                "description": "Start point [x,y,z] of a flexure array (create_flexure_array)"
                            },
                            "end_mm": {
                                "type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                                "description": "End point [x,y,z] of a flexure array (create_flexure_array)"
                            },
                            "count": {"type": "integer", "description": "Number of hinges in the array", "default": 3},
                        },
                        "required": ["operation"]
                    },
                    annotations=types.ToolAnnotations(readOnlyHint=False, destructiveHint=True),
                ),

                types.Tool(
                    name="tendon_routing_operations",
                    description=(
                        "Geometric planning and validation for tendon-driven prosthetic "
                        "finger joints. compute_anchor_points places tendon anchors offset "
                        "from a chain of joint centers. check_tendon_curvature flags any "
                        "turn in the tendon path tighter than the cable's rated minimum "
                        "bend radius. check_tendon_path_clearance samples a straight segment "
                        "between two points and reports any that fall inside solid material "
                        "(i.e. a channel needs to be added there)."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "operation": {
                                "type": "string",
                                "enum": ["compute_anchor_points", "check_tendon_curvature",
                                         "check_tendon_path_clearance"],
                                "description": (
                                    "compute_anchor_points: from joint_positions_mm + "
                                    "segment_radii_mm. check_tendon_curvature: from "
                                    "anchor_points_mm + cable_type/min_bend_radius_mm. "
                                    "check_tendon_path_clearance: from shape + point_a_mm/point_b_mm."
                                )
                            },
                            "joint_positions_mm": {
                                "type": "array",
                                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                                "description": "Joint centers [x,y,z], proximal to distal (compute_anchor_points)"
                            },
                            "segment_radii_mm": {
                                "type": "array", "items": {"type": "number"},
                                "description": "Segment radii used to offset each anchor from its joint center"
                            },
                            "offset_fraction": {"type": "number", "description": "Fraction of radius to offset anchor toward -Z", "default": 0.8},
                            "anchor_points_mm": {
                                "type": "array",
                                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                                "description": "Tendon path points to check for tight turns (check_tendon_curvature)"
                            },
                            "cable_type": {
                                "type": "string",
                                "enum": ["fishing_line_20lb", "fishing_line_50lb", "paracord_thin",
                                         "steel_cable_1mm", "dyneema_1mm"],
                                "description": "Preset cable type — sets the minimum safe bend radius"
                            },
                            "min_bend_radius_mm": {"type": "number", "description": "Explicit minimum bend radius override, mm"},
                            "shape": {"type": "string", "description": "Object name to check path clearance against"},
                            "point_a_mm": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3, "description": "Segment start [x,y,z]"},
                            "point_b_mm": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3, "description": "Segment end [x,y,z]"},
                            "samples": {"type": "integer", "description": "Number of points to sample along the segment", "default": 10},
                        },
                        "required": ["operation"]
                    },
                    annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False),
                ),

                types.Tool(
                    name="contact_pressure_operations",
                    description=(
                        "Geometry-only proxy for socket-fit quality. sample_socket_clearance "
                        "samples points on a socket's inner faces and reports signed distance "
                        "to a limb-model shape (negative = overlap = must fix). "
                        "summarize_pressure_zones clusters the raw samples from "
                        "sample_socket_clearance into contiguous problem zones. "
                        "NOT a substitute for FEA or clinical pressure mapping — a first-pass "
                        "screen to catch pinch points before a physical fitting."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "operation": {
                                "type": "string",
                                "enum": ["sample_socket_clearance", "summarize_pressure_zones"],
                                "description": (
                                    "sample_socket_clearance: from socket_shape + limb_model_shape. "
                                    "summarize_pressure_zones: from the 'samples' list it returned."
                                )
                            },
                            "socket_shape": {"type": "string", "description": "Socket object name"},
                            "limb_model_shape": {"type": "string", "description": "Simplified limb-model object name"},
                            "samples_per_face": {"type": "integer", "description": "Grid resolution per face", "default": 5},
                            "inner_face_indices": {
                                "type": "array", "items": {"type": "integer"},
                                "description": "1-based indices of the socket's inner (limb-facing) faces. Omit to sample all faces."
                            },
                            "samples": {
                                "type": "array", "items": {"type": "object"},
                                "description": "The 'samples' list returned by sample_socket_clearance (summarize_pressure_zones)"
                            },
                            "cluster_radius_mm": {"type": "number", "description": "Max distance between points in the same cluster", "default": 5.0},
                            "risk_levels": {
                                "type": "array", "items": {"type": "string"},
                                "description": "Which risk labels to cluster",
                                "default": ["overlap", "high_pressure"]
                            },
                        },
                        "required": ["operation"]
                    },
                    annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False),
                ),

                types.Tool(
                    name="growth_socket_operations",
                    description=(
                        "Telescoping pediatric socket generation: a fixed outer shell plus a "
                        "family of inner-liner inserts at increasing growth offsets, so only "
                        "the liner needs reprinting as the child grows. create_outer_shell "
                        "builds the fixed shell sized for the largest liner. "
                        "create_liner_family builds the liner inserts from the same base "
                        "profile at a list of growth offsets."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "operation": {
                                "type": "string",
                                "enum": ["create_outer_shell", "create_liner_family"],
                                "description": (
                                    "create_outer_shell: fixed shell from profile_sketch + "
                                    "max_liner_offset_mm. create_liner_family: liner inserts "
                                    "from profile_sketch + growth_offsets_mm."
                                )
                            },
                            "profile_sketch": {"type": "string", "description": "Closed Sketch defining the base cross-section"},
                            "length_mm": {"type": "number", "description": "Extrusion length along the socket axis", "default": 120.0},
                            "max_liner_offset_mm": {"type": "number", "description": "Largest liner offset the shell must accept", "default": 6.0},
                            "wall_thickness_mm": {"type": "number", "description": "Outer shell wall thickness", "default": 3.0},
                            "clearance_mm": {"type": "number", "description": "Gap between largest liner and shell inner wall", "default": 0.3},
                            "name": {"type": "string", "description": "Name for the resulting shell object", "default": "SocketOuterShell"},
                            "growth_offsets_mm": {
                                "type": "array", "items": {"type": "number"},
                                "description": "Offsets (mm) to grow the profile outward for each liner size",
                                "default": [0, 2, 4, 6]
                            },
                            "liner_thickness_mm": {"type": "number", "description": "Wall thickness of each liner", "default": 2.0},
                            "name_prefix": {"type": "string", "description": "Base name for created liner objects", "default": "SocketLiner"},
                        },
                        "required": ["operation", "profile_sketch"]
                    },
                    annotations=types.ToolAnnotations(readOnlyHint=False, destructiveHint=True),
                ),

                types.Tool(
                    name="quick_connect_operations",
                    description=(
                        "Parametric socket-to-terminal-device quick-connect interfaces so one "
                        "socket can accept different hands/hooks. Each create_* op generates a "
                        "matched male/female pair in one call so the two halves never drift out "
                        "of sync. list_connector_presets returns recommended starting dimensions. "
                        "create_bayonet_pair: quarter-turn lock, no loose hardware — default for "
                        "daily-use. create_threaded_pair: higher torque resistance, falls back to "
                        "a friction-taper (with a warning) if this FreeCAD build lacks a thread-sweep "
                        "API. add_magnetic_retention cuts magnet recesses into an existing pair as a "
                        "retention aid — not a substitute for the mechanical lock."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "operation": {
                                "type": "string",
                                "enum": ["list_connector_presets", "create_bayonet_pair",
                                         "create_threaded_pair", "add_magnetic_retention"],
                                "description": "Which quick-connect action to perform."
                            },
                            "diameter_mm": {"type": "number", "description": "Mating cylinder outer diameter", "default": 25.0},
                            "lug_count": {"type": "integer", "description": "Number of bayonet lugs (2-4 typical)", "default": 3},
                            "lug_length_mm": {"type": "number", "description": "Bayonet lug length", "default": 6.0},
                            "lug_thickness_mm": {"type": "number", "description": "Bayonet lug thickness", "default": 2.0},
                            "lug_travel_deg": {"type": "number", "description": "Quarter-turn travel angle in degrees", "default": 30.0},
                            "barrel_length_mm": {"type": "number", "description": "Bayonet barrel length", "default": 15.0},
                            "male_position_mm": {
                                "type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                                "description": "Placement [x,y,z] for the male half", "default": [0, 0, 0]
                            },
                            "female_position_mm": {
                                "type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                                "description": "Placement [x,y,z] for the female half", "default": [40, 0, 0]
                            },
                            "name_prefix": {"type": "string", "description": "Base name for created objects", "default": "Bayonet"},
                            "pitch_mm": {"type": "number", "description": "Thread pitch (create_threaded_pair)", "default": 2.0},
                            "length_mm": {"type": "number", "description": "Thread engagement length (create_threaded_pair)", "default": 15.0},
                            "male_shape": {"type": "string", "description": "Existing male-half object name (add_magnetic_retention)"},
                            "female_shape": {"type": "string", "description": "Existing female-half object name (add_magnetic_retention)"},
                            "magnet_diameter_mm": {"type": "number", "description": "Disc-magnet diameter", "default": 6.0},
                            "magnet_thickness_mm": {"type": "number", "description": "Disc-magnet thickness", "default": 2.0},
                            "position_mm": {
                                "type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                                "description": "Center [x,y,z] of the magnet recess on each part", "default": [0, 0, 0]
                            },
                            "name_suffix": {"type": "string", "description": "Suffix appended to output object names", "default": "_MagRecess"},
                        },
                        "required": ["operation"]
                    },
                    annotations=types.ToolAnnotations(readOnlyHint=False, destructiveHint=True),
                ),

                types.Tool(
                    name="fitting_history_operations",
                    description=(
                        "Session-log layer over fixture_operations for tracking socket-fitting "
                        "iterations per patient over time. log_fitting_session saves a geometry "
                        "fixture for the current socket plus structured notes (pressure "
                        "complaints, donning time, fit rating), append-only. "
                        "get_fitting_history returns the full logged history for a patient. "
                        "compare_to_last_fitting diffs the current socket against the most "
                        "recently logged session. Use a non-identifying patient_id (e.g. "
                        "initials + number) — no PII required or stored."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "operation": {
                                "type": "string",
                                "enum": ["log_fitting_session", "get_fitting_history",
                                         "compare_to_last_fitting"],
                                "description": "Which fitting-history action to perform."
                            },
                            "shape": {"type": "string", "description": "Socket object name to snapshot or compare"},
                            "patient_id": {
                                "type": "string",
                                "description": "Non-identifying code for the patient (alphanumerics/underscores/hyphens only)"
                            },
                            "session_notes": {"type": "string", "description": "Free-text notes for this session (log_fitting_session)"},
                            "pressure_complaints": {
                                "type": "array", "items": {"type": "string"},
                                "description": "e.g. ['tight at distal end']"
                            },
                            "donning_time_sec": {"type": "number", "description": "How long it took to put the socket on"},
                            "fit_rating": {"type": "integer", "description": "Subjective fit rating, 1-5"},
                        },
                        "required": ["operation", "patient_id"]
                    },
                    annotations=types.ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False),
                ),

                types.Tool(
                    name="lightweight_operations",
                    description=(
                        "Load-guided infill/lattice density screening for reducing prosthetic "
                        "part weight — a geometric proxy, not FEA. recommend_density_map slices "
                        "a shape's bounding box into a grid along an approximate load path and "
                        "recommends an infill density band per cell. estimate_weight_savings "
                        "compares 100% solid weight against the recommended density map. Always "
                        "validate any load-bearing region with a physical test before use."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "operation": {
                                "type": "string",
                                "enum": ["recommend_density_map", "estimate_weight_savings"],
                                "description": (
                                    "recommend_density_map: from shape + load_start_mm/load_end_mm. "
                                    "estimate_weight_savings: from shape + the 'cells' list it returned."
                                )
                            },
                            "shape": {"type": "string", "description": "Object name to analyze"},
                            "load_start_mm": {
                                "type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                                "description": "Approximate load-path start point [x,y,z]"
                            },
                            "load_end_mm": {
                                "type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3,
                                "description": "Approximate load-path end point [x,y,z]"
                            },
                            "axis_divisions": {"type": "integer", "description": "Grid cells along the load axis", "default": 6},
                            "cross_divisions": {"type": "integer", "description": "Grid cells in each perpendicular direction", "default": 3},
                            "cells": {
                                "type": "array", "items": {"type": "object"},
                                "description": "The 'cells' list returned by recommend_density_map (estimate_weight_savings)"
                            },
                            "material_density_g_cm3": {
                                "type": "number",
                                "description": "Material density, e.g. 1.24 PETG/PLA, 1.21 TPU",
                                "default": 1.24
                            },
                        },
                        "required": ["operation", "shape"]
                    },
                    annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False),
                ),
'''

# 3a. Insertar los 7 Tool() justo antes del cierre de smart_dispatchers
pattern = re.compile(r'\n( *)\]\n( *)return base_tools \+ smart_dispatchers\n')
matches = list(pattern.finditer(server_text))
assert len(matches) == 1, f"[server.py Tool insert] patron aparece {len(matches)} veces (esperaba 1)"
m = matches[0]
insert_at = m.start() + 1  # justo despues del \n que precede a ']'
server_text = server_text[:insert_at] + NEW_TOOLS_BLOCK + server_text[insert_at:]

# 3b. Agregar los 7 nombres a la lista de dispatch (elif name in [...])
DISPATCH_LIST_ANCHOR = '"organic_operations", "surface_operations", "fillet_chamfer"]:'
DISPATCH_LIST_NEW = (
    '"organic_operations", "surface_operations", "fillet_chamfer",\n'
    '                      "compliant_operations", "tendon_routing_operations", '
    '"contact_pressure_operations",\n'
    '                      "growth_socket_operations", "quick_connect_operations", '
    '"fitting_history_operations",\n'
    '                      "lightweight_operations"]:'
)

server_text = apply_unique(
    server_text,
    DISPATCH_LIST_ANCHOR,
    lambda a: DISPATCH_LIST_NEW,
    "server.py dispatch elif list",
)

# ---------------------------------------------------------------------------
# Todo validado — ahora sí escribimos (salvo --dry-run)
# ---------------------------------------------------------------------------

if DRY_RUN:
    print("DRY RUN: todos los anchors se encontraron OK. No se escribio nada.")
    sys.exit(0)

for path, new_text in (
    (INIT_PY, init_text),
    (HANDLER_PY, handler_text),
    (SERVER_PY, server_text),
):
    bak = backup(path)
    path.write_text(new_text)
    print(f"OK: {path}  (backup: {bak.name})")

print("\nAhora compila los 3 archivos:")
print(f"  python3 -m py_compile {INIT_PY}")
print(f"  python3 -m py_compile {HANDLER_PY}")
print(f"  python3 -m py_compile {SERVER_PY}")
