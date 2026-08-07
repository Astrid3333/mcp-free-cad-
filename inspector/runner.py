"""Reglas de DRC (Design Rule Check) geométricas y runner.

Todas las reglas son screening de primer paso sobre geometría real
(Part.Shape de FreeCAD) — no reemplazan FEA ni criterio de fabricación.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .findings import Finding, Profile, Severity


@dataclass
class DRCResult:
    findings: List[Finding] = field(default_factory=list)

    @property
    def summary(self) -> Dict[str, int]:
        counts = {"error": 0, "warning": 0, "info": 0}
        for f in self.findings:
            counts[f.severity.value] += 1
        return counts


def _obj_shape(obj):
    """Devuelve el Part.Shape de un objeto, o None si no tiene."""
    return getattr(obj, "Shape", None)


# ---------------------------------------------------------------------------
# Reglas base (siempre corren, con o sin perfil de proceso)
# ---------------------------------------------------------------------------

def rule_shape_validity(obj, params: dict) -> Optional[Finding]:
    """ERROR si la geometría de OCCT reporta el shape como inválido."""
    shape = _obj_shape(obj)
    if shape is None or shape.isNull():
        return None
    if not shape.isValid():
        return Finding(
            rule_id="model.shape_validity",
            severity=Severity.ERROR,
            objects=[obj.Name],
            message=f"'{obj.Name}' tiene un shape geométricamente inválido (OCCT isValid()=False).",
            suggestion="Correr Part → Check geometry en FreeCAD para ver el detalle del fallo.",
        )
    return None


def rule_zero_or_negative_volume(obj, params: dict) -> Optional[Finding]:
    """WARNING si un sólido tiene volumen nulo o negativo (normales invertidas / shell abierto)."""
    shape = _obj_shape(obj)
    if shape is None or shape.isNull():
        return None
    if getattr(shape, "ShapeType", None) not in ("Solid", "CompSolid"):
        return None
    vol = shape.Volume
    if vol <= 0:
        return Finding(
            rule_id="model.zero_or_negative_volume",
            severity=Severity.WARNING,
            objects=[obj.Name],
            message=f"'{obj.Name}' tiene volumen {vol:.3f} mm³ — probable shell abierto o normales invertidas.",
            value=vol,
            limit=0.0,
            suggestion="Revisar si el sólido es realmente cerrado (Part → Check geometry) antes de imprimir/fabricar.",
        )
    return None


def rule_degenerate_bbox(obj, params: dict) -> Optional[Finding]:
    """WARNING si alguna dimensión del bounding box es ~0 (geometría colapsada)."""
    shape = _obj_shape(obj)
    if shape is None or shape.isNull():
        return None
    bb = shape.BoundBox
    dims = [bb.XLength, bb.YLength, bb.ZLength]
    min_dim = min(dims)
    if min_dim < 1e-4:
        return Finding(
            rule_id="model.degenerate_bbox",
            severity=Severity.WARNING,
            objects=[obj.Name],
            message=f"'{obj.Name}' tiene una dimensión de bounding box casi nula ({min_dim:.6f} mm) — geometría posiblemente colapsada.",
            value=min_dim,
        )
    return None


_MODEL_RULES = [rule_shape_validity, rule_zero_or_negative_volume, rule_degenerate_bbox]


# ---------------------------------------------------------------------------
# Reglas por proceso de fabricación
# ---------------------------------------------------------------------------

def _rule_laser_planarity(profile: Profile):
    max_thickness_mm = profile.params.get("max_thickness_mm", 10.0)

    def _rule(obj, params: dict) -> Optional[Finding]:
        shape = _obj_shape(obj)
        if shape is None or shape.isNull():
            return None
        bb = shape.BoundBox
        thickness = min(bb.XLength, bb.YLength, bb.ZLength)
        if thickness > max_thickness_mm:
            return Finding(
                rule_id="laser.max_thickness",
                severity=Severity.WARNING,
                objects=[obj.Name],
                message=f"'{obj.Name}' tiene un espesor mínimo de {thickness:.2f} mm, por encima del límite de corte láser ({max_thickness_mm} mm).",
                value=thickness,
                limit=max_thickness_mm,
                suggestion="Verificar el material y la potencia del láser para ese espesor, o segmentar la pieza.",
            )
        return None

    return _rule


def _rule_resin_min_wall(profile: Profile):
    min_wall_mm = profile.params.get("min_wall_mm", 0.5)

    def _rule(obj, params: dict) -> Optional[Finding]:
        shape = _obj_shape(obj)
        if shape is None or shape.isNull():
            return None
        if getattr(shape, "ShapeType", None) not in ("Solid", "CompSolid"):
            return None
        bb = shape.BoundBox
        min_dim = min(bb.XLength, bb.YLength, bb.ZLength)
        if min_dim < min_wall_mm:
            return Finding(
                rule_id="resin.min_wall_proxy",
                severity=Severity.WARNING,
                objects=[obj.Name],
                message=f"'{obj.Name}': dimensión mínima del bounding box ({min_dim:.3f} mm) por debajo del espesor mínimo de pared ({min_wall_mm} mm). Proxy geométrico, no mide espesor de pared real localmente.",
                value=min_dim,
                limit=min_wall_mm,
                suggestion="Revisar espesores de pared reales con una herramienta de medición de sección, este chequeo es solo un proxy por bounding box global.",
            )
        return None

    return _rule


def _rule_cnc_manual_review(profile: Profile):
    def _rule(obj, params: dict) -> Optional[Finding]:
        return Finding(
            rule_id="cnc_3axis.manual_undercut_review",
            severity=Severity.INFO,
            objects=[obj.Name],
            message=f"'{obj.Name}': detección de undercuts para CNC 3 ejes no está implementada — revisar manualmente antes de generar toolpaths.",
            suggestion="Usar CAM → Simulate para validar accesibilidad de herramienta.",
        )

    return _rule


_PROCESS_RULE_BUILDERS = {
    "laser": _rule_laser_planarity,
    "resin": _rule_resin_min_wall,
    "cnc_3axis": _rule_cnc_manual_review,
}


def _default_rules(profile: Optional[Profile]) -> List:
    rules = list(_MODEL_RULES)
    if profile is not None:
        builder = _PROCESS_RULE_BUILDERS.get(profile.process)
        if builder is not None:
            rules.append(builder(profile))
    return rules


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_drc(objects, doc, profile: Optional[Profile], rules: List) -> DRCResult:
    result = DRCResult()
    for obj in objects:
        for rule in rules:
            try:
                finding = rule(obj, profile.params if profile else {})
            except Exception as e:
                finding = Finding(
                    rule_id="runner.rule_error",
                    severity=Severity.INFO,
                    objects=[getattr(obj, "Name", str(obj))],
                    message=f"La regla {getattr(rule, '__name__', str(rule))} falló al evaluar '{getattr(obj, 'Name', obj)}': {e}",
                )
            if finding is not None:
                result.findings.append(finding)
    return result
