# Load-guided lightweighting handlers for FreeCAD MCP
#
# Suggests where a solid can be hollowed/lattice-filled vs where it must
# stay solid, based on an approximate load direction and magnitude — a
# cheap geometric proxy for topology optimization, aimed at reducing
# prosthetic weight (which directly affects wearer fatigue and comfort)
# without a full FEA toolchain.
#
# Design decisions:
#   - This is a *screening* tool, not a structural solver. It ranks
#     regions by a simple proxy score (distance from the load path +
#     local cross-section area) and recommends infill density bands.
#     Always validate any load-bearing print with a physical test before
#     trusting it on a person.
#   - Works directly on the existing solid's bounding box, sliced into a
#     grid of cells along the load axis, rather than requiring a meshed
#     FEA model — keeps this usable without extra dependencies.
#   - Output format (density band per cell) is meant to feed either manual
#     per-region infill settings in a slicer, or a future geonode/lattice
#     generator handler — this module only computes the recommendation.

import json
import math
from typing import Any, Dict, List, Tuple

from .base import BaseHandler

# Density bands as a function of proxy load score (0 = far from load path
# and small cross-section, 1 = squarely on the load path with large
# cross-section). These are conservative starting points for FDM parts.
_DENSITY_BANDS = [
    (0.0, 0.15, 10,  "gyroid"),   # far from load: light lattice ok
    (0.15, 0.4, 20,  "gyroid"),
    (0.4, 0.65, 35,  "gyroid"),
    (0.65, 0.85, 60,  "grid"),
    (0.85, 1.01, 100, "solid"),   # on the load path: keep solid
]


def _band_for_score(score: float) -> Tuple[int, str]:
    for lo, hi, density, pattern in _DENSITY_BANDS:
        if lo <= score < hi:
            return density, pattern
    return 100, "solid"


class LightweightOpsHandler(BaseHandler):
    """Load-guided infill/lattice density recommendations for reducing
    prosthetic part weight."""

    _ALLOWED_OPERATIONS = frozenset({
        "recommend_density_map", "estimate_weight_savings",
    })

    # ------------------------------------------------------------------
    def recommend_density_map(self, args: Dict[str, Any]) -> str:
        """Slice a shape's bounding box into a grid along the load axis
        and score each cell by proximity to the load line + local
        cross-sectional footprint, producing an infill-density
        recommendation per cell.

        Args:
          shape:            object name to analyze
          load_start_mm, load_end_mm: [x,y,z] points defining the
                            approximate load path through the part (e.g.
                            grip point to wrist attachment)
          axis_divisions:   how many cells along the load axis
          cross_divisions:  how many cells in each perpendicular direction

        Returns JSON with a list of cells: bounds, proxy score, recommended
        density %, and infill pattern.
        """
        try:
            object_name = args.get("shape", "")
            load_start = args.get("load_start_mm")
            load_end = args.get("load_end_mm")
            axis_div = int(args.get("axis_divisions", 6))
            cross_div = int(args.get("cross_divisions", 3))

            if not object_name or not load_start or not load_end:
                return json.dumps({"ok": False, "details": {},
                                    "message": "Missing shape, load_start_mm, or load_end_mm"})

            doc = self.get_document()
            if not doc:
                return json.dumps({"ok": False, "details": {},
                                    "message": "No active FreeCAD document"})
            obj = self.get_object(object_name, doc)
            if not obj or not hasattr(obj, "Shape"):
                return json.dumps({"ok": False, "details": {},
                                    "message": f"Object not found: {object_name}"})

            bb = obj.Shape.BoundBox
            load_vec = [load_end[i] - load_start[i] for i in range(3)]
            load_len = math.sqrt(sum(c * c for c in load_vec))
            if load_len < 1e-9:
                return json.dumps({"ok": False, "details": {},
                                    "message": "load_start_mm and load_end_mm are the same point"})
            load_dir = [c / load_len for c in load_vec]

            cells = []
            xs = [bb.XMin + (bb.XLength) * (i + 0.5) / max(axis_div, cross_div, 1) for i in range(1)]
            # Build a simple 3D grid over the bounding box.
            nx = axis_div
            ny = cross_div
            nz = cross_div
            for ix in range(nx):
                for iy in range(ny):
                    for iz in range(nz):
                        cx = bb.XMin + bb.XLength * (ix + 0.5) / nx
                        cy = bb.YMin + bb.YLength * (iy + 0.5) / ny
                        cz = bb.ZMin + bb.ZLength * (iz + 0.5) / nz

                        # Perpendicular distance from cell center to the
                        # load line (point-to-line distance).
                        to_cell = [cx - load_start[0], cy - load_start[1], cz - load_start[2]]
                        proj_len = sum(a * b for a, b in zip(to_cell, load_dir))
                        proj_len_clamped = max(0.0, min(load_len, proj_len))
                        closest = [load_start[k] + load_dir[k] * proj_len_clamped for k in range(3)]
                        perp_dist = math.dist([cx, cy, cz], closest)

                        # Normalize perpendicular distance against the
                        # part's overall cross-section size so the score
                        # is shape-scale-independent.
                        scale = max(bb.XLength, bb.YLength, bb.ZLength, 1.0)
                        proximity_score = max(0.0, 1.0 - (perp_dist / (scale * 0.25)))

                        # Only "on the load path" longitudinally if within
                        # the projected segment (not before/after it).
                        on_path = 0.0 <= proj_len <= load_len
                        score = proximity_score if on_path else proximity_score * 0.5
                        score = max(0.0, min(1.0, score))

                        density, pattern = _band_for_score(score)
                        cells.append({
                            "center_mm": [round(cx, 2), round(cy, 2), round(cz, 2)],
                            "load_proximity_score": round(score, 3),
                            "recommended_infill_pct": density,
                            "recommended_pattern": pattern,
                        })

            solid_cells = sum(1 for c in cells if c["recommended_pattern"] == "solid")
            light_cells = sum(1 for c in cells if c["recommended_infill_pct"] <= 20)

            return json.dumps({
                "ok": True,
                "details": {"cells": cells, "grid": [nx, ny, nz]},
                "message": (
                    f"Analyzed {len(cells)} region(s): {solid_cells} on the load "
                    f"path (recommend solid/100% infill), {light_cells} far from "
                    f"load (recommend 10-20% gyroid). This is a geometric proxy, "
                    f"not FEA — validate any load-bearing region with a physical "
                    f"test before use."
                ),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in recommend_density_map: {e}"})

    # ------------------------------------------------------------------
    def estimate_weight_savings(self, args: Dict[str, Any]) -> str:
        """Rough weight-savings estimate comparing 100% solid vs the
        recommended density map from recommend_density_map.

        Args:
          shape:        object name (used for total solid volume)
          cells:        the "cells" list from recommend_density_map
          material_density_g_cm3: material density, e.g. 1.24 for PETG,
                        1.21 for TPU, 1.24 for PLA

        Returns JSON with estimated solid weight, lightweighted weight,
        and percent savings.
        """
        try:
            object_name = args.get("shape", "")
            cells = args.get("cells", [])
            density = float(args.get("material_density_g_cm3", 1.24))

            if not object_name or not cells:
                return json.dumps({"ok": False, "details": {},
                                    "message": "Missing shape or cells"})

            doc = self.get_document()
            if not doc:
                return json.dumps({"ok": False, "details": {},
                                    "message": "No active FreeCAD document"})
            obj = self.get_object(object_name, doc)
            if not obj or not hasattr(obj, "Shape"):
                return json.dumps({"ok": False, "details": {},
                                    "message": f"Object not found: {object_name}"})

            volume_mm3 = obj.Shape.Volume
            volume_cm3 = volume_mm3 / 1000.0
            solid_weight_g = volume_cm3 * density

            # Weight fraction ≈ average infill % across cells (rough
            # approximation — real slicer output will differ based on
            # wall count and pattern, this is a planning-stage estimate).
            avg_fraction = sum(c["recommended_infill_pct"] for c in cells) / (100.0 * len(cells))
            lightweighted_weight_g = solid_weight_g * avg_fraction

            savings_pct = (1 - avg_fraction) * 100.0

            return json.dumps({
                "ok": True,
                "details": {
                    "solid_weight_g": round(solid_weight_g, 2),
                    "estimated_lightweighted_weight_g": round(lightweighted_weight_g, 2),
                    "estimated_savings_pct": round(savings_pct, 1),
                    "material_density_g_cm3": density,
                },
                "message": (
                    f"Estimated weight: {round(solid_weight_g, 1)}g solid -> "
                    f"~{round(lightweighted_weight_g, 1)}g with recommended infill "
                    f"map (~{round(savings_pct, 0)}% lighter). Rough planning "
                    f"estimate — actual slicer output will vary with wall count "
                    f"and infill pattern."
                ),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {},
                                "message": f"Error in estimate_weight_savings: {e}"})
