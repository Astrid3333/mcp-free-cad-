"""
mesh_repair_operations - reparacion de mallas escaneadas (STL/PLY) con huecos.

Flujo de digitalizacion por escaner 3D (tesis Martinez Fernandez, UPM):
detecta bordes abiertos (huecos) en una malla importada y los tapa.

Operaciones:
    - analyze_mesh_defects(object_name): detecta huecos, perimetro/diametro/centroide.
    - patch_holes(object_name, hole_indices=None, method="planar", name=None):
      tapa los huecos indicados (o todos). method="planar" (mas robusto para huecos
      casi planos) o "filled" (Part.makeFilledFace, mejor para huecos no planos pero
      puede devolver normal invertida - mismo problema que el trim cutter del socket
      transradial).

Sin probar contra FreeCAD real - revisar antes de confiar en el resultado.
"""

import json
from typing import Any, Dict

import Part

from .base import BaseHandler


def _find_open_wires(shape):
    """Wires que bordean huecos (edges usados por una sola cara)."""
    edge_face_count = {}
    for face in shape.Faces:
        for edge in face.Edges:
            key = edge.hashCode()
            edge_face_count[key] = edge_face_count.get(key, 0) + 1
    naked_edges = [e for f in shape.Faces for e in f.Edges if edge_face_count[e.hashCode()] == 1]
    if not naked_edges:
        return []
    wire_groups = Part.sortEdges(naked_edges)
    return [Part.Wire(group) for group in wire_groups]


def _shape_from_obj(obj, tolerance=0.1):
    """Devuelve un Part.Shape utilizable tanto para Part::Feature (obj.Shape)
    como para Mesh::Feature (obj.Mesh) -- este ultimo es el caso comun al
    importar STL/PLY escaneados, que es justamente el flujo que este modulo
    dice soportar. Sin este fallback, analyze_mesh_defects/patch_holes
    fallaban con AttributeError contra cualquier malla real importada."""
    shp = getattr(obj, "Shape", None)
    if shp is not None and not shp.isNull():
        return shp
    mesh = getattr(obj, "Mesh", None)
    if mesh is not None:
        shape = Part.Shape()
        shape.makeShapeFromMesh(mesh.Topology, tolerance)
        return shape
    raise AttributeError(
        f"'{obj.Name}' no tiene ni .Shape ni .Mesh -- tipo no soportado ({obj.TypeId})"
    )


class MeshRepairOpsHandler(BaseHandler):
    _ALLOWED_OPERATIONS = {"analyze_mesh_defects", "patch_holes"}

    def analyze_mesh_defects(self, args: Dict[str, Any]) -> str:
        object_name = args.get("object_name")
        if not object_name:
            return json.dumps({"error": "Falta object_name"})

        obj = self.get_object(object_name)
        if obj is None:
            return json.dumps({"error": f"No se encontro el objeto '{object_name}'"})

        shp = _shape_from_obj(obj)
        wires = _find_open_wires(shp)
        holes = []
        for i, w in enumerate(wires):
            try:
                bbox = w.BoundBox
                c = w.CenterOfMass
                holes.append({
                    "index": i,
                    "closed": w.isClosed(),
                    "perimeter_mm": round(w.Length, 2),
                    "approx_diameter_mm": round(max(bbox.XLength, bbox.YLength, bbox.ZLength), 2),
                    "centroid_mm": [round(c.x, 2), round(c.y, 2), round(c.z, 2)],
                })
            except Exception as e:
                holes.append({"index": i, "error": str(e)})

        return json.dumps({
            "object_name": object_name,
            "is_watertight": len(wires) == 0,
            "hole_count": len(wires),
            "holes": holes,
        })

    def patch_holes(self, args: Dict[str, Any]) -> str:
        object_name = args.get("object_name")
        if not object_name:
            return json.dumps({"error": "Falta object_name"})

        obj = self.get_object(object_name)
        if obj is None:
            return json.dumps({"error": f"No se encontro el objeto '{object_name}'"})

        doc = self.get_document()
        if doc is None:
            return json.dumps({"error": "No hay documento activo"})

        method = args.get("method", "planar")
        hole_indices = args.get("hole_indices")
        new_name = args.get("name")

        shp = _shape_from_obj(obj)
        wires = _find_open_wires(shp)
        if not wires:
            return json.dumps({"object_name": object_name, "patched": 0, "message": "no se detectaron huecos"})

        targets = wires if hole_indices is None else [wires[i] for i in hole_indices]
        patch_faces = []
        failed = []
        for i, w in enumerate(targets):
            try:
                face = Part.makeFilledFace(w.Edges) if method == "filled" else Part.Face(w)
                patch_faces.append(face)
            except Exception as e:
                failed.append({"index": i, "error": str(e)})

        if not patch_faces:
            return json.dumps({"object_name": object_name, "patched": 0, "failed": failed})

        all_faces = list(shp.Faces) + patch_faces
        shell = Part.Shell(all_faces)
        # cosido geometrico -- _find_open_wires compara edges por hashCode(), y
        # Part.Face(w) suele regenerar geometria de edge al construir la cara de
        # parche, asi que dos edges coincidentes en el espacio pueden tener
        # hashCode distinto. sewShape() fusiona por coincidencia geometrica
        # dentro de una tolerancia, no por identidad de hash.
        shell.sewShape()
        try:
            solid = Part.Solid(shell)
        except Exception:
            solid = shell  # no cerro del todo -- queda como shell, revisar remaining_holes

        obj_name = new_name or f"{object_name}_repaired"
        new_obj = doc.addObject("Part::Feature", obj_name)
        new_obj.Shape = solid
        self.recompute(doc)

        return json.dumps({
            "object_name": new_obj.Name,
            "patched": len(patch_faces),
            "failed": failed,
            "remaining_holes": len(_find_open_wires(new_obj.Shape)),
        })


# --- schema sugerido para registrar en tu server MCP (AICopilot) ---
# {
#   "name": "mesh_repair_operations",
#   "description": "Deteccion y reparacion de huecos en mallas escaneadas (STL/PLY).",
#   "parameters": {
#     "properties": {
#       "operation": {"enum": ["analyze_mesh_defects", "patch_holes"], "type": "string"},
#       "object_name": {"type": "string"},
#       "hole_indices": {"type": "array", "items": {"type": "integer"}},
#       "method": {"enum": ["planar", "filled"], "default": "planar", "type": "string"},
#       "name": {"type": "string"}
#     },
#     "required": ["operation", "object_name"]
#   }
# }
