"""
cosmetic_shell_operations - funda/carcasa decorativa de dos piezas (clamshell)
que envuelve el socket + pilar protesico. Ver el capitulo "Recubrimientos
protesicos" de la tesis UPM y las fundas UNYQ que citan ahi.

Operaciones:
    - generate_shell(core_object_name, clearance_mm=3.0, wall_thickness_mm=2.0, name=None):
        genera una cascara hueca que envuelve el core con un espacio libre
        interno (clearance_mm) y un espesor de pared dado, via doble offset
        (offset externo - offset interno).
    - split_clamshell(shell_object_name, plane_point_mm=None, plane_normal_mm=(1,0,0),
        tab_count=3, tab_width_mm=6.0, tab_depth_mm=1.5, name=None):
        corta la cascara en dos mitades por un plano y agrega tabs a presion
        (protuberancia en una mitad, ranura en la otra) repartidos a lo largo
        de la linea de corte.

Se conecta con quick_connect_operations: el core que envuelve esta cascara
suele ser el mismo socket/pilar sobre el que despues armas el conector rapido.

Nota sobre split_clamshell: la distribucion de tabs asume que plane_normal_mm
es aprox (1,0,0) (corte perpendicular al eje X del bounding box). Si cortas
en otro eje, la logica de reparto de tabs a lo largo de "X" hay que
adaptarla -- lo deje simple a proposito para que sea facil de ajustar.

Sin probar contra FreeCAD real.
"""

import json
from typing import Any, Dict

import FreeCAD as App
import Part

from .base import BaseHandler


class CosmeticShellOpsHandler(BaseHandler):
    _ALLOWED_OPERATIONS = {"generate_shell", "split_clamshell"}

    def generate_shell(self, args: Dict[str, Any]) -> str:
        core_object_name = args.get("core_object_name")
        if not core_object_name:
            return json.dumps({"error": "Falta core_object_name"})

        core_obj = self.get_object(core_object_name)
        if core_obj is None:
            return json.dumps({"error": f"No se encontro el objeto '{core_object_name}'"})

        doc = self.get_document()
        if doc is None:
            return json.dumps({"error": "No hay documento activo"})

        clearance_mm = args.get("clearance_mm", 3.0)
        wall_thickness_mm = args.get("wall_thickness_mm", 2.0)
        new_name = args.get("name")

        core = core_obj.Shape
        outer = core.makeOffsetShape(clearance_mm + wall_thickness_mm, 0.01, fill=True)
        inner = core.makeOffsetShape(clearance_mm, 0.01, fill=True)
        shell = outer.cut(inner)

        obj_name = new_name or f"{core_object_name}_shell"
        new_obj = doc.addObject("Part::Feature", obj_name)
        new_obj.Shape = shell
        self.recompute(doc)

        return json.dumps({
            "object_name": new_obj.Name,
            "clearance_mm": clearance_mm,
            "wall_thickness_mm": wall_thickness_mm,
        })

    def split_clamshell(self, args: Dict[str, Any]) -> str:
        shell_object_name = args.get("shell_object_name")
        if not shell_object_name:
            return json.dumps({"error": "Falta shell_object_name"})

        shell_obj = self.get_object(shell_object_name)
        if shell_obj is None:
            return json.dumps({"error": f"No se encontro el objeto '{shell_object_name}'"})

        doc = self.get_document()
        if doc is None:
            return json.dumps({"error": "No hay documento activo"})

        plane_point_mm = args.get("plane_point_mm")
        plane_normal_mm = args.get("plane_normal_mm", (1, 0, 0))
        tab_count = args.get("tab_count", 3)
        tab_width_mm = args.get("tab_width_mm", 6.0)
        tab_depth_mm = args.get("tab_depth_mm", 1.5)
        new_name = args.get("name")

        shp = shell_obj.Shape
        bbox = shp.BoundBox
        if plane_point_mm is None:
            plane_point_mm = [bbox.Center.x, bbox.Center.y, bbox.Center.z]

        point = App.Vector(*plane_point_mm)
        normal = App.Vector(*plane_normal_mm).normalize()
        big = max(bbox.XLength, bbox.YLength, bbox.ZLength) * 3

        half_box = Part.makeBox(big, big, big, App.Vector(-big / 2, -big / 2, -big / 2))
        rot = App.Rotation(App.Vector(1, 0, 0), normal)
        half_box.Placement = App.Placement(point, rot)

        side_a = shp.common(half_box)
        side_b = shp.cut(half_box)

        for i in range(tab_count):
            frac = (i + 1) / (tab_count + 1)
            offset_x = bbox.XMin + bbox.XLength * frac - point.x
            tab_pos = point + App.Vector(offset_x, 0, 0)
            tab = Part.makeBox(
                tab_width_mm, tab_width_mm, tab_depth_mm,
                tab_pos + App.Vector(-tab_width_mm / 2, -tab_width_mm / 2, -tab_depth_mm))
            side_a = side_a.fuse(tab)
            slot_pad = 0.3
            slot = Part.makeBox(
                tab_width_mm + slot_pad, tab_width_mm + slot_pad, tab_depth_mm + slot_pad,
                tab_pos + App.Vector(-(tab_width_mm + slot_pad) / 2, -(tab_width_mm + slot_pad) / 2,
                                      -(tab_depth_mm + slot_pad)))
            side_b = side_b.cut(slot)

        names = []
        for label, piece in (("A", side_a), ("B", side_b)):
            obj_name = f"{new_name or shell_object_name}_{label}"
            new_obj = doc.addObject("Part::Feature", obj_name)
            new_obj.Shape = piece.removeSplitter()
            names.append(new_obj.Name)

        self.recompute(doc)
        return json.dumps({
            "halves": names,
            "tab_count": tab_count,
            "note": "reparto de tabs asume corte ~paralelo al eje X del bbox -- "
                    "ajustar si plane_normal_mm no es (1,0,0)",
        })


# --- schema sugerido para registrar en tu server MCP (AICopilot) ---
# {
#   "name": "cosmetic_shell_operations",
#   "description": "Carcasa/funda decorativa de dos piezas (clamshell) alrededor de un core con tabs a presion.",
#   "parameters": {
#     "properties": {
#       "operation": {"enum": ["generate_shell", "split_clamshell"], "type": "string"},
#       "core_object_name": {"type": "string"},
#       "shell_object_name": {"type": "string"},
#       "clearance_mm": {"type": "number", "default": 3.0},
#       "wall_thickness_mm": {"type": "number", "default": 2.0},
#       "plane_point_mm": {"type": "array", "items": {"type": "number"}},
#       "plane_normal_mm": {"type": "array", "items": {"type": "number"}, "default": [1, 0, 0]},
#       "tab_count": {"type": "integer", "default": 3},
#       "tab_width_mm": {"type": "number", "default": 6.0},
#       "tab_depth_mm": {"type": "number", "default": 1.5},
#       "name": {"type": "string"}
#     },
#     "required": ["operation"]
#   }
# }
