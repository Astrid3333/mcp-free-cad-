"""
print_segmentation_operations - partir una pieza grande en secciones que
entren en la cama de impresion, con pines de alineacion en los cortes.

Mismo problema que resolvieron a mano en el paper de UTEZ: partieron el
antebrazo en 3 piezas por limite de tamano de impresora y dejaron guias
para que embonaran entre si.

Operaciones:
    - plan_segments(object_name, bed_size_mm, axis="auto", margin_mm=5.0):
        calcula cuantos cortes hacen falta a lo largo de un eje (o el eje
        mas largo si axis="auto") y devuelve las posiciones de los planos
        de corte.
    - segment_with_joints(object_name, cut_planes_mm, axis="z", pin_diameter_mm=4.0,
        pin_length_mm=6.0, pin_clearance_mm=0.15, name=None):
        corta la shape en esos planos; en cada interfaz agrega un pin macho
        (fusionado a un lado) y un agujero hembra con clearance (restado del
        otro lado) para que las piezas impresas se autoalineen al pegar.

bed_size_mm se espera como [x, y, z] en mm (tamano util de la cama, ya con
el margen que quieras aplicar vos misma o via margin_mm).

Sin probar contra FreeCAD real - la logica de _cross_section_center asume que
el corte genera una cara plana perpendicular al eje elegido, que es el caso
normal con Part.common contra una caja, pero revisar con geometria rara
(ej. si el corte cae justo en un borde existente de la shape original).

segment_with_joints tiene la geometria de pines simplificada a proposito:
funciona para casos rectos/regulares, pero con formas muy organicas
probablemente haga falta ajustar como se ubica el centro de cada interfaz.
"""

import json
from typing import Any, Dict

import FreeCAD as App
import Part

from .base import BaseHandler

_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def _cross_section_center(piece_shape, coord, idx, tol=1e-2):
    for face in piece_shape.Faces:
        n = face.normalAt(0, 0)
        n_val = (n.x, n.y, n.z)[idx]
        c = face.CenterOfMass
        c_val = (c.x, c.y, c.z)[idx]
        if abs(n_val) > 0.9 and abs(c_val - coord) < tol:
            return c
    return None


class PrintSegmentationOpsHandler(BaseHandler):
    _ALLOWED_OPERATIONS = {"plan_segments", "segment_with_joints"}

    def plan_segments(self, args: Dict[str, Any]) -> str:
        object_name = args.get("object_name")
        if not object_name:
            return json.dumps({"error": "Falta object_name"})

        obj = self.get_object(object_name)
        if obj is None:
            return json.dumps({"error": f"No se encontro el objeto '{object_name}'"})

        bed_size_mm = args.get("bed_size_mm")
        axis = args.get("axis", "auto")
        margin_mm = args.get("margin_mm", 5.0)

        shp = obj.Shape
        bbox = shp.BoundBox
        dims = {"x": bbox.XLength, "y": bbox.YLength, "z": bbox.ZLength}

        if axis == "auto":
            axis = max(dims, key=dims.get)
        idx = _AXIS_INDEX[axis]
        length = dims[axis]
        bed_len = bed_size_mm[idx] if bed_size_mm else None
        usable = (bed_len - 2 * margin_mm) if bed_len else length

        if not bed_len or length <= usable:
            return json.dumps({
                "axis": axis,
                "segments_needed": 1,
                "cut_planes_mm": [],
                "length_mm": round(length, 2),
            })

        n_segments = int(length // usable) + 1
        seg_len = length / n_segments
        lo = [bbox.XMin, bbox.YMin, bbox.ZMin][idx]
        cut_planes = [round(lo + seg_len * i, 2) for i in range(1, n_segments)]

        return json.dumps({
            "axis": axis,
            "length_mm": round(length, 2),
            "usable_bed_length_mm": round(usable, 2),
            "segments_needed": n_segments,
            "cut_planes_mm": cut_planes,
        })

    def segment_with_joints(self, args: Dict[str, Any]) -> str:
        object_name = args.get("object_name")
        if not object_name:
            return json.dumps({"error": "Falta object_name"})

        obj = self.get_object(object_name)
        if obj is None:
            return json.dumps({"error": f"No se encontro el objeto '{object_name}'"})

        doc = self.get_document()
        if doc is None:
            return json.dumps({"error": "No hay documento activo"})

        cut_planes_mm = args.get("cut_planes_mm")
        axis = args.get("axis", "z")
        pin_diameter_mm = args.get("pin_diameter_mm", 4.0)
        pin_length_mm = args.get("pin_length_mm", 6.0)
        pin_clearance_mm = args.get("pin_clearance_mm", 0.15)
        new_name = args.get("name")

        if not cut_planes_mm:
            return json.dumps({"error": "cut_planes_mm vacio: corre plan_segments primero"})

        shp = obj.Shape
        idx = _AXIS_INDEX[axis]
        dir_vec = [0.0, 0.0, 0.0]
        dir_vec[idx] = 1.0
        direction = App.Vector(*dir_vec)

        bbox = shp.BoundBox
        big = max(bbox.XLength, bbox.YLength, bbox.ZLength) * 3
        lo_bound = [bbox.XMin, bbox.YMin, bbox.ZMin][idx]
        hi_bound = [bbox.XMax, bbox.YMax, bbox.ZMax][idx]
        boundaries = [lo_bound] + sorted(cut_planes_mm) + [hi_bound]

        pieces = []
        for i in range(len(boundaries) - 1):
            lo, hi = boundaries[i], boundaries[i + 1]
            origin = [bbox.XMin - big, bbox.YMin - big, bbox.ZMin - big]
            origin[idx] = lo
            dims = [big * 2, big * 2, big * 2]
            dims[idx] = hi - lo
            cutter = Part.makeBox(dims[0], dims[1], dims[2], App.Vector(*origin))
            pieces.append(shp.common(cutter))

        for j, cut_coord in enumerate(sorted(cut_planes_mm)):
            center = _cross_section_center(pieces[j], cut_coord, idx)
            if center is None:
                continue  # el corte no genero la cara plana esperada -- revisar a mano
            half_offset = App.Vector(*(v * pin_length_mm / 2.0 for v in dir_vec))
            boss_origin = center.sub(half_offset)
            boss = Part.makeCylinder(pin_diameter_mm / 2.0, pin_length_mm, boss_origin, direction)
            hole = Part.makeCylinder(pin_diameter_mm / 2.0 + pin_clearance_mm, pin_length_mm, boss_origin, direction)
            pieces[j] = pieces[j].fuse(boss)
            pieces[j + 1] = pieces[j + 1].cut(hole)

        segment_names = []
        for i, piece in enumerate(pieces):
            obj_name = f"{new_name or object_name}_seg{i}"
            new_obj = doc.addObject("Part::Feature", obj_name)
            new_obj.Shape = piece.removeSplitter()
            segment_names.append(new_obj.Name)

        self.recompute(doc)
        return json.dumps({"segments": segment_names, "cut_planes_mm": cut_planes_mm, "axis": axis})


# --- schema sugerido para registrar en tu server MCP (AICopilot) ---
# {
#   "name": "print_segmentation_operations",
#   "description": "Partir piezas grandes en secciones imprimibles con pines de alineacion.",
#   "parameters": {
#     "properties": {
#       "operation": {"enum": ["plan_segments", "segment_with_joints"], "type": "string"},
#       "object_name": {"type": "string"},
#       "bed_size_mm": {"type": "array", "items": {"type": "number"}},
#       "axis": {"enum": ["x", "y", "z", "auto"], "default": "auto", "type": "string"},
#       "margin_mm": {"type": "number", "default": 5.0},
#       "cut_planes_mm": {"type": "array", "items": {"type": "number"}},
#       "pin_diameter_mm": {"type": "number", "default": 4.0},
#       "pin_length_mm": {"type": "number", "default": 6.0},
#       "pin_clearance_mm": {"type": "number", "default": 0.15},
#       "name": {"type": "string"}
#     },
#     "required": ["operation", "object_name"]
#   }
# }
