# Material property reference + zone tagging + pressure-map density
# recommendations for FreeCAD MCP.
#
# NOT an FEA solver. Properties come from published datasheets/general
# literature values (see the "source" field per material) -- not from
# lab testing on Astrid's own prints, and FDM-printed parts are
# anisotropic (layer-direction strength is typically 50-70% of the
# in-plane value). Validate anything load-bearing with a physical test.
#
# Design decisions:
#   - tag_material_zone is non-destructive: it stores a JSON map of
#     {face_index: material_name} as a single App::PropertyString on the
#     object, it doesn't split the solid or alter geometry.
#   - recommend_density_from_pressure_map takes REAL measured pressure
#     readings (e.g. from an in-socket sensor), unlike lightweight_ops's
#     recommend_density_map which uses a geometric load-path proxy. Same
#     density-band style output so both can feed the same downstream
#     slicer workflow.

import json
from typing import Any, Dict, List

import FreeCAD

from .base import BaseHandler

MATERIALS_DB: Dict[str, Dict[str, Any]] = {
    "pla": {
        "category": "thermoplastic_fdm",
        "tensile_strength_mpa": 55.0,
        "density_g_cm3": 1.24,
        "shore_hardness": "D83",
        "notes": "Stiff, low-impact-resistance, easiest to print. Printed-part "
                 "strength is orientation-dependent (~50-70% of these values "
                 "across layers, not along them).",
        "source": "Generic FDM PLA datasheet values (Prusament/Polymaker-class filament)",
    },
    "petg": {
        "category": "thermoplastic_fdm",
        "tensile_strength_mpa": 50.0,
        "density_g_cm3": 1.27,
        "shore_hardness": "D77",
        "notes": "Better layer adhesion and impact resistance than PLA, less stiff. "
                 "Good general-purpose socket shell material.",
        "source": "Generic FDM PETG datasheet values",
    },
    "polycarbonate": {
        "category": "thermoplastic_fdm",
        "tensile_strength_mpa": 60.0,
        "density_g_cm3": 1.20,
        "shore_hardness": "D82",
        "notes": "High heat resistance and toughness, but hygroscopic -- needs "
                 "drying before printing or layer adhesion suffers badly.",
        "source": "Generic FDM PC datasheet values",
    },
    "tpu_95a": {
        "category": "flexible_zone",
        "shore_hardness": "A95",
        "density_g_cm3": 1.21,
        "elongation_at_break_pct": 450.0,
        "notes": "Flexible liner/cushioning material -- good for trim-line edges "
                 "and contact zones, not for load-bearing shell sections.",
        "source": "Generic FDM TPU 95A datasheet values",
    },
    "carbon_fiber_nylon": {
        "category": "reinforced_composite",
        "tensile_strength_mpa": 55.0,
        "density_g_cm3": 1.15,
        "notes": "Strong along the print direction, weak across layers (more so "
                 "than unreinforced filaments) and moisture-sensitive -- dry "
                 "before printing. Good for local stiffening ribs, not full shells.",
        "source": "Generic chopped-carbon-fiber-nylon FDM filament datasheet values",
    },
    "titanium_ti6al4v": {
        "category": "metal_insert",
        "tensile_strength_mpa": 950.0,
        "density_g_cm3": 4.43,
        "notes": "For machined/SLM structural inserts and attachment hardware "
                 "(pyramid adapters, pins) -- not FDM-printable. Biocompatible.",
        "source": "Grade 5 (wrought) titanium alloy datasheet values",
    },
    "mycelium_composite": {
        "category": "experimental",
        "density_g_cm3": 0.2,
        "validated_for_structural_use": False,
        "notes": "Exploratory bio-based material. No peer-reviewed structural "
                 "prosthetic application published as of mid-2026 -- treat as "
                 "insulation/padding-only until real test data exists, not as "
                 "a shell or load-bearing candidate.",
        "source": "General mycelium-composite literature (packaging/insulation "
                  "studies), not prosthetics-specific",
    },
}

# Pressure -> density band. Bands are fractions of max_expected_kpa; each
# band gives an infill percentage/pattern recommendation for that zone.
# Same band-count style as lightweight_ops's proxy-score bands, but keyed
# off a real measured value instead of a geometric proxy.
_PRESSURE_BANDS = [
    (0.25, 15, "gyroid"),
    (0.50, 30, "gyroid"),
    (0.75, 50, "cubic"),
    (1.01, 80, "cubic (consider solid perimeter reinforcement)"),
]


class MaterialsOpsHandler(BaseHandler):
    """Material property reference DB, non-destructive zone tagging on
    existing solids, and pressure-sensor-driven infill density recommendations.
    """

    def list_materials(self, args: Dict[str, Any]) -> str:
        """List materials in the reference DB, optionally filtered by category.

        Args:
          category: optional filter, e.g. "thermoplastic_fdm", "flexible_zone",
                     "metal_insert", "reinforced_composite", "experimental"

        Returns the matching entries (name + full property dict each).
        """
        try:
            category = args.get("category")
            entries = {
                name: props for name, props in MATERIALS_DB.items()
                if not category or props.get("category") == category
            }
            return json.dumps({
                "ok": True,
                "details": {"materials": entries, "count": len(entries)},
                "message": f"{len(entries)} material(s)" + (f" in category '{category}'" if category else ""),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error in list_materials: {e}"})

    def get_material(self, args: Dict[str, Any]) -> str:
        """Get a single material's full property record by name.

        Args:
          name: material key, e.g. "petg", "carbon_fiber_nylon"
        """
        try:
            name = str(args.get("name", "")).lower().strip()
            if not name:
                return json.dumps({"ok": False, "details": {}, "message": "Missing required argument: name"})
            props = MATERIALS_DB.get(name)
            if not props:
                return json.dumps({
                    "ok": False,
                    "details": {"known_materials": sorted(MATERIALS_DB.keys())},
                    "message": f"Unknown material: {name!r}",
                })
            return json.dumps({"ok": True, "details": {"name": name, **props}, "message": f"Material: {name}"})
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error in get_material: {e}"})

    def tag_material_zone(self, args: Dict[str, Any]) -> str:
        """Tag faces of an existing solid with a material name. Non-destructive:
        stores a JSON map on the object as a single App::PropertyString, doesn't
        alter geometry.

        Args:
          shape: object name
          face_indices: list of 1-based face indices to tag
          material: material name (arbitrary strings allowed -- flagged in the
                     response, not rejected, since a custom/unlisted material
                     is still a valid thing to tag a zone with)
        """
        try:
            doc_name = args.get("doc_name")
            doc = FreeCAD.getDocument(doc_name) if doc_name else self.get_document()
            if not doc:
                return json.dumps({"ok": False, "details": {}, "message": f"No document found (doc_name={doc_name!r})"})

            shape_name = args.get("shape")
            obj = self.get_object(shape_name, doc)
            if not obj or not hasattr(obj, "Shape") or obj.Shape.isNull():
                return json.dumps({"ok": False, "details": {}, "message": f"Shape object not found: {shape_name}"})

            face_indices = args.get("face_indices") or []
            n_faces = len(obj.Shape.Faces)
            bad = [i for i in face_indices if not (1 <= int(i) <= n_faces)]
            if bad:
                return json.dumps({
                    "ok": False,
                    "details": {"invalid_indices": bad, "face_count": n_faces},
                    "message": f"Face index out of range (object has {n_faces} faces, 1-based): {bad}",
                })

            material = str(args.get("material", "")).strip()
            if not material:
                return json.dumps({"ok": False, "details": {}, "message": "Missing required argument: material"})

            if not hasattr(obj, "MaterialZoneMap"):
                obj.addProperty("App::PropertyString", "MaterialZoneMap", "MaterialsOps",
                                 "JSON map of {face_index: material_name}, set by materials_operations.tag_material_zone")
                obj.MaterialZoneMap = "{}"

            zone_map = json.loads(obj.MaterialZoneMap or "{}")
            for idx in face_indices:
                zone_map[str(int(idx))] = material
            obj.MaterialZoneMap = json.dumps(zone_map)

            known = material.lower() in MATERIALS_DB
            return json.dumps({
                "ok": True,
                "details": {"shape": obj.Name, "tagged_faces": face_indices, "material": material,
                             "material_known_in_db": known},
                "message": f"Tagged {len(face_indices)} face(s) of '{obj.Name}' as '{material}'"
                           + ("" if known else " (not in the reference DB -- stored as-is)"),
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error in tag_material_zone: {e}"})

    def read_material_zones(self, args: Dict[str, Any]) -> str:
        """Read back tagged zones on a solid, joined with material DB properties
        (where known) and per-face area.

        Args:
          shape: object name
        """
        try:
            doc_name = args.get("doc_name")
            doc = FreeCAD.getDocument(doc_name) if doc_name else self.get_document()
            if not doc:
                return json.dumps({"ok": False, "details": {}, "message": f"No document found (doc_name={doc_name!r})"})

            shape_name = args.get("shape")
            obj = self.get_object(shape_name, doc)
            if not obj or not hasattr(obj, "Shape") or obj.Shape.isNull():
                return json.dumps({"ok": False, "details": {}, "message": f"Shape object not found: {shape_name}"})

            zone_map = json.loads(getattr(obj, "MaterialZoneMap", "{}") or "{}")
            faces = obj.Shape.Faces
            zones = []
            for idx_str, material in sorted(zone_map.items(), key=lambda kv: int(kv[0])):
                idx = int(idx_str)
                area = faces[idx - 1].Area if 1 <= idx <= len(faces) else None
                zones.append({
                    "face_index": idx,
                    "material": material,
                    "area_mm2": area,
                    "properties": MATERIALS_DB.get(material.lower()),
                })

            return json.dumps({
                "ok": True,
                "details": {"shape": obj.Name, "zones": zones, "zone_count": len(zones)},
                "message": f"{len(zones)} tagged zone(s) on '{obj.Name}'",
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error in read_material_zones: {e}"})

    def recommend_density_from_pressure_map(self, args: Dict[str, Any]) -> str:
        """Convert real measured pressure readings into per-point infill density
        recommendations. NOT a validated clinical fitting tool -- a planning aid
        to help decide where a socket needs denser infill, informed by real
        sensor data instead of a geometric proxy.

        Args:
          readings: list of {point_mm: [x,y,z], pressure_kpa: float}
          max_expected_kpa: pressure value mapped to the top density band (default 80.0)
        """
        try:
            readings = args.get("readings") or []
            if not readings:
                return json.dumps({"ok": False, "details": {}, "message": "Missing required argument: readings"})

            max_kpa = float(args.get("max_expected_kpa", 80.0))
            if max_kpa <= 0:
                return json.dumps({"ok": False, "details": {}, "message": "max_expected_kpa must be > 0"})

            recommendations = []
            for r in readings:
                point = r.get("point_mm")
                pressure = float(r.get("pressure_kpa", 0.0))
                frac = max(0.0, pressure) / max_kpa
                density_pct, pattern = _PRESSURE_BANDS[-1][1], _PRESSURE_BANDS[-1][2]
                for threshold, dens, pat in _PRESSURE_BANDS:
                    if frac <= threshold:
                        density_pct, pattern = dens, pat
                        break
                recommendations.append({
                    "point_mm": point,
                    "pressure_kpa": pressure,
                    "recommended_infill_pct": density_pct,
                    "recommended_pattern": pattern,
                })

            recommendations.sort(key=lambda r: r["pressure_kpa"], reverse=True)

            return json.dumps({
                "ok": True,
                "details": {"recommendations": recommendations, "max_expected_kpa": max_kpa},
                "message": f"{len(recommendations)} reading(s) banded into infill recommendations. "
                           "Planning aid, not a validated clinical fitting tool -- confirm against wearer comfort.",
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error in recommend_density_from_pressure_map: {e}"})
