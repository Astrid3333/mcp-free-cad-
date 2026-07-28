"""
finger_segment_operations - generador parametrico de falanges + articulaciones
para dedos protesicos, tipo el mecanismo del paper de UTEZ (falange distal,
articulacion interfalangica, falange proximal, cerrado con hilo/cordon).

Operaciones:
    - create_phalanx(length_mm, width_mm, height_mm, taper=0.85, name=None):
        un segmento de falange (caja ahusada hacia la punta, via loft).
    - create_finger_chain(segment_lengths_mm=None, width_mm=12.0, height_mm=10.0,
        joint_gap_mm=1.0, base_position_mm=(0,0,0), direction_mm=(1,0,0), name=None):
        encadena N falanges con un gap articular entre cada una. Devuelve,
        ademas de las piezas, los joint_positions_mm de cada articulacion --
        pensados para pasarselos DIRECTO a
        tendon_routing_operations(operation="compute_anchor_points", joint_positions_mm=...)
        o a check_tendon_curvature, sin tener que recalcular nada a mano.

No incluye el mecanismo de bisagra en si (pin fisico o living hinge) a
proposito -- para eso ya tenes compliant_operations (create_living_hinge /
create_flexure_array), que se puede aplicar sobre el gap articular que
devuelve create_finger_chain.

Sin probar contra FreeCAD real. Part.makeLoft(wires, solid=True) deberia
andar para el ahusado pero si tu version de FreeCAD se queja, la alternativa
mas simple es reemplazar el loft por un Part.makeBox() sin ahusar (taper=1.0
efectivamente) mientras lo depuras.
"""

import json
from typing import Any, Dict

import FreeCAD as App
import Part

from .base import BaseHandler


def _phalanx_shape(length_mm, width_mm, height_mm, taper):
    base_wire = Part.Wire(Part.makePolygon([
        App.Vector(0, 0, 0), App.Vector(0, width_mm, 0),
        App.Vector(0, width_mm, height_mm), App.Vector(0, 0, height_mm),
        App.Vector(0, 0, 0)]))

    tip_w = width_mm * taper
    tip_h = height_mm * taper
    dw = (width_mm - tip_w) / 2
    dh = (height_mm - tip_h) / 2
    tip_wire = Part.Wire(Part.makePolygon([
        App.Vector(length_mm, dw, dh), App.Vector(length_mm, dw + tip_w, dh),
        App.Vector(length_mm, dw + tip_w, dh + tip_h), App.Vector(length_mm, dw, dh + tip_h),
        App.Vector(length_mm, dw, dh)]))

    return Part.makeLoft([base_wire, tip_wire], True)


class FingerSegmentOpsHandler(BaseHandler):
    _ALLOWED_OPERATIONS = {"create_phalanx", "create_finger_chain"}

    def create_phalanx(self, args: Dict[str, Any]) -> str:
        doc = self.get_document()
        if doc is None:
            return json.dumps({"error": "No hay documento activo"})

        length_mm = args.get("length_mm", 20.0)
        width_mm = args.get("width_mm", 12.0)
        height_mm = args.get("height_mm", 10.0)
        taper = args.get("taper", 0.85)
        new_name = args.get("name")

        shape = _phalanx_shape(length_mm, width_mm, height_mm, taper)

        obj_name = new_name or "phalanx"
        new_obj = doc.addObject("Part::Feature", obj_name)
        new_obj.Shape = shape
        self.recompute(doc)

        return json.dumps({
            "object_name": new_obj.Name,
            "length_mm": length_mm,
            "width_mm": width_mm,
            "height_mm": height_mm,
        })

    def create_finger_chain(self, args: Dict[str, Any]) -> str:
        doc = self.get_document()
        if doc is None:
            return json.dumps({"error": "No hay documento activo"})

        segment_lengths_mm = args.get("segment_lengths_mm") or [25.0, 20.0, 15.0]
        width_mm = args.get("width_mm", 12.0)
        height_mm = args.get("height_mm", 10.0)
        taper = args.get("taper", 0.85)
        joint_gap_mm = args.get("joint_gap_mm", 1.0)
        base_position_mm = args.get("base_position_mm", (0, 0, 0))
        direction_mm = args.get("direction_mm", (1, 0, 0))
        new_name = args.get("name")

        direction = App.Vector(*direction_mm).normalize()
        base = App.Vector(*base_position_mm)

        segments = []
        joint_positions_mm = []
        cursor = 0.0
        for i, seg_len in enumerate(segment_lengths_mm):
            pos = base + direction * cursor
            shape = _phalanx_shape(seg_len, width_mm, height_mm, taper)

            obj_name = f"{new_name or 'finger'}_seg{i}"
            new_obj = doc.addObject("Part::Feature", obj_name)
            new_obj.Shape = shape
            new_obj.Placement = App.Placement(pos, App.Rotation())
            segments.append(new_obj.Name)

            cursor += seg_len
            if i < len(segment_lengths_mm) - 1:
                joint_center = base + direction * cursor
                joint_positions_mm.append(
                    [round(joint_center.x, 2), round(joint_center.y, 2), round(joint_center.z, 2)]
                )
                cursor += joint_gap_mm

        self.recompute(doc)
        return json.dumps({
            "segments": segments,
            "joint_positions_mm": joint_positions_mm,
            "note": "pasar joint_positions_mm directo a tendon_routing_operations "
                    "(compute_anchor_points / check_tendon_curvature) para planear el cordon de cierre; "
                    "para el mecanismo de la bisagra en si, usar compliant_operations sobre cada gap",
        })


# --- schema sugerido para registrar en tu server MCP (AICopilot) ---
# {
#   "name": "finger_segment_operations",
#   "description": "Generador parametrico de falanges/dedos, integrable con tendon_routing_operations.",
#   "parameters": {
#     "properties": {
#       "operation": {"enum": ["create_phalanx", "create_finger_chain"], "type": "string"},
#       "length_mm": {"type": "number"},
#       "width_mm": {"type": "number", "default": 12.0},
#       "height_mm": {"type": "number", "default": 10.0},
#       "taper": {"type": "number", "default": 0.85},
#       "segment_lengths_mm": {"type": "array", "items": {"type": "number"}},
#       "joint_gap_mm": {"type": "number", "default": 1.0},
#       "base_position_mm": {"type": "array", "items": {"type": "number"}, "default": [0, 0, 0]},
#       "direction_mm": {"type": "array", "items": {"type": "number"}, "default": [1, 0, 0]},
#       "name": {"type": "string"}
#     },
#     "required": ["operation"]
#   }
# }
