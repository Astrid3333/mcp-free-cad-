"""
FreeCAD Prosthetics Fastener Operations Handler
"""
import json
import FreeCAD as App
import Part
from FreeCAD import Vector
from .base import BaseHandler

ISO_METRIC_SPECS = {
    "M3": {"d": 3.0, "p": 0.5, "h": 0.433, "d2": 2.675, "clearance": 3.3},
    "M4": {"d": 4.0, "p": 0.7, "h": 0.604, "d2": 3.545, "clearance": 4.5},
    "M5": {"d": 5.0, "p": 0.8, "h": 0.693, "d2": 4.480, "clearance": 5.5},
    "M6": {"d": 6.0, "p": 1.0, "h": 0.866, "d2": 5.350, "clearance": 6.6},
    "M8": {"d": 8.0, "p": 1.25, "h": 1.083, "d2": 7.188, "clearance": 9.0},
}


class ShoulderPinProxy:
    def __init__(self, obj):
        obj.addProperty("App::PropertyLength", "shank_diameter", "Geometry", "Shank outer diameter (mm)")
        obj.addProperty("App::PropertyLength", "shank_length", "Geometry", "Total shank length (mm)")
        obj.addProperty("App::PropertyLength", "shoulder_diameter", "Geometry", "Shoulder step-down diameter (mm)")
        obj.addProperty("App::PropertyLength", "shoulder_position", "Geometry", "Position of shoulder (mm)")
        obj.addProperty("App::PropertyLength", "head_diameter", "Geometry", "Bearing face diameter (mm)")
        obj.addProperty("App::PropertyLength", "head_height", "Geometry", "Bearing face height (mm)")
        obj.addProperty("App::PropertyBool", "chamfered", "Geometry", "Add 0.5mm chamfer")
        obj.addProperty("App::PropertyString", "material", "Annotation", "Material designation")
        obj.shank_diameter = 8.0
        obj.shank_length = 50.0
        obj.shoulder_diameter = 6.0
        obj.shoulder_position = 10.0
        obj.head_diameter = 10.0
        obj.head_height = 3.0
        obj.chamfered = True
        obj.material = "Steel"
        obj.Proxy = self

    def onChanged(self, obj, prop):
        pass

    def execute(self, obj):
        shank = Part.makeCylinder(obj.shank_diameter / 2, obj.shank_length)
        shoulder_cut_len = obj.shank_length - obj.shoulder_position
        if shoulder_cut_len > 0:
            shoulder_bore = Part.makeCylinder(
                obj.shank_diameter / 2, shoulder_cut_len,
                Vector(0, 0, obj.shoulder_position), Vector(0, 0, 1)
            )
            shank = shank.cut(shoulder_bore)
            shoulder_section = Part.makeCylinder(
                obj.shoulder_diameter / 2, shoulder_cut_len,
                Vector(0, 0, obj.shoulder_position), Vector(0, 0, 1)
            )
            shank = shank.fuse(shoulder_section)
        if obj.head_diameter > 0 and obj.head_height > 0:
            head = Part.makeCylinder(
                obj.head_diameter / 2, obj.head_height,
                Vector(0, 0, obj.shank_length), Vector(0, 0, 1)
            )
            shank = shank.fuse(head)
        obj.Shape = shank


class IsoMetricThreadProxy:
    def __init__(self, obj):
        obj.addProperty("App::PropertyEnumeration", "size", "Geometry", "Thread size (M3-M8)")
        obj.addProperty("App::PropertyLength", "length", "Geometry", "Thread length (mm)")
        obj.addProperty("App::PropertyBool", "internal", "Geometry", "Internal (hole) vs external (bolt)")
        obj.addProperty("App::PropertyInteger", "turns", "Geometry", "Number of complete turns")
        obj.addProperty("App::PropertyString", "material", "Annotation", "Material")
        obj.size = list(ISO_METRIC_SPECS.keys())
        obj.size = "M6"
        obj.length = 20.0
        obj.internal = False
        obj.turns = 0
        obj.material = "Steel"
        obj.Proxy = self

    def onChanged(self, obj, prop):
        pass

    def execute(self, obj):
        spec = ISO_METRIC_SPECS.get(obj.size, {})
        d = spec.get("d2" if obj.internal else "d", 6.0)
        core = Part.makeCylinder(d / 2, obj.length)
        obj.Shape = core


class BushingProxy:
    def __init__(self, obj):
        obj.addProperty("App::PropertyLength", "outer_diameter", "Geometry", "Outer diameter (mm)")
        obj.addProperty("App::PropertyLength", "inner_diameter", "Geometry", "Inner bore diameter (mm)")
        obj.addProperty("App::PropertyLength", "length", "Geometry", "Axial length (mm)")
        obj.addProperty("App::PropertyLength", "radial_clearance", "Tolerance", "Radial clearance")
        obj.addProperty("App::PropertyBool", "flanged", "Geometry", "Add radial flange")
        obj.addProperty("App::PropertyLength", "flange_diameter", "Geometry", "Flange diameter (mm)")
        obj.addProperty("App::PropertyLength", "flange_thickness", "Geometry", "Flange thickness (mm)")
        obj.addProperty("App::PropertyString", "material", "Annotation", "Material")
        obj.outer_diameter = 10.0
        obj.inner_diameter = 8.0
        obj.length = 6.0
        obj.radial_clearance = 1.0
        obj.flanged = False
        obj.flange_diameter = 14.0
        obj.flange_thickness = 2.0
        obj.material = "Bronze"
        obj.Proxy = self

    def onChanged(self, obj, prop):
        if prop in ["outer_diameter", "inner_diameter"]:
            obj.radial_clearance = (obj.outer_diameter - obj.inner_diameter) / 2

    def execute(self, obj):
        outer = Part.makeCylinder(obj.outer_diameter / 2, obj.length)
        bore = Part.makeCylinder(obj.inner_diameter / 2, obj.length)
        bushing = outer.cut(bore)
        if obj.flanged and obj.flange_diameter > obj.outer_diameter:
            flange = Part.makeCylinder(obj.flange_diameter / 2, obj.flange_thickness)
            bushing = bushing.fuse(flange)
        obj.Shape = bushing


class FastenerMechanicalOpsHandler(BaseHandler):
    """Parametric prosthetic fasteners: shoulder pins, ISO M3-M8 threads, bushings.

    Cada operacion: def op(self, args: Dict[str, Any]) -> str, retorna
    json.dumps({"ok": bool, "details": {...}, "message": str}) -- mismo
    contrato que socket_pattern_operations.py, despachado via
    _dispatch_to_handler / _ALLOWED_OPERATIONS.
    """

    _ALLOWED_OPERATIONS = {"shoulder_pin", "iso_thread", "bushing"}

    def shoulder_pin(self, args):
        try:
            doc = App.activeDocument() or App.newDocument()
            obj = doc.addObject("Part::FeaturePython", "ShoulderPin")
            proxy = ShoulderPinProxy(obj)
            for k in ["shank_diameter", "shank_length", "shoulder_diameter",
                      "shoulder_position", "head_diameter", "head_height",
                      "chamfered", "material"]:
                if k in args:
                    setattr(obj, k, args[k])
            proxy.execute(obj)
            doc.recompute()
            return json.dumps({
                "ok": True,
                "details": {
                    "document": doc.Name,
                    "object": obj.Name,
                    "volume_mm3": obj.Shape.Volume,
                },
                "message": f"Shoulder pin creado: {obj.Name}",
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error: {e}"})

    def iso_thread(self, args):
        try:
            doc = App.activeDocument() or App.newDocument()
            obj = doc.addObject("Part::FeaturePython", "IsoMetricThread")
            proxy = IsoMetricThreadProxy(obj)
            for k in ["size", "length", "internal", "turns", "material"]:
                if k in args:
                    setattr(obj, k, args[k])
            proxy.execute(obj)
            doc.recompute()
            spec = ISO_METRIC_SPECS.get(obj.size, {})
            return json.dumps({
                "ok": True,
                "details": {
                    "document": doc.Name,
                    "object": obj.Name,
                    "size": obj.size,
                    "pitch_mm": spec.get("p"),
                    "volume_mm3": obj.Shape.Volume,
                },
                "message": f"Rosca ISO {obj.size} creada: {obj.Name}",
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error: {e}"})

    def bushing(self, args):
        try:
            doc = App.activeDocument() or App.newDocument()
            obj = doc.addObject("Part::FeaturePython", "Bushing")
            proxy = BushingProxy(obj)
            for k in ["outer_diameter", "inner_diameter", "length", "flanged",
                      "flange_diameter", "flange_thickness", "material"]:
                if k in args:
                    setattr(obj, k, args[k])
            proxy.execute(obj)
            doc.recompute()
            return json.dumps({
                "ok": True,
                "details": {
                    "document": doc.Name,
                    "object": obj.Name,
                    "radial_clearance_mm": float(obj.radial_clearance),
                    "volume_mm3": obj.Shape.Volume,
                },
                "message": f"Bushing creado: {obj.Name}",
            })
        except Exception as e:
            return json.dumps({"ok": False, "details": {}, "message": f"Error: {e}"})
