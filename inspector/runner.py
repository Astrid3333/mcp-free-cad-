"""Reglas de DRC (Design Rule Check) geométricas y runner.

Todas las reglas son screening de primer paso sobre geometría real
(Part.Shape de FreeCAD) — no reemplazan FEA ni criterio de fabricación.
"""

import math

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


def rule_wall_thickness_offset(obj, params: dict) -> Optional[Finding]:
    """WARNING si el offset hacia adentro por min_wall_mm/2 falla o produce
    geometria invalida/vacia -- señal de que hay una pared mas fina que el
    limite en alguna zona LOCAL de la pieza.

    A diferencia de rule_degenerate_bbox (que solo mira la dimension minima
    global del bounding box), esto detecta paredes finas en cualquier parte
    del solido, sin importar el tamaño general de la pieza.

    LIMITACION HONESTA: makeOffsetShape puede fallar por razones que NO son
    pared fina -- geometria concava compleja, aristas muy filosas, curvatura
    alta -- asi que esto puede dar falsos positivos en piezas con geometria
    intrincada aunque las paredes sean gruesas. Es un screening de primer
    paso, no una medicion de espesor certificada; si da WARNING, conviene
    confirmar con Part → Measure en la zona señalada antes de asumir que
    hay que reforzarla.
    """
    shape = _obj_shape(obj)
    if shape is None or shape.isNull():
        return None
    if getattr(shape, "ShapeType", None) not in ("Solid", "CompSolid"):
        return None
    min_wall_mm = params.get("min_wall_mm", 0.8)
    try:
        offset = shape.makeOffsetShape(-min_wall_mm / 2.0, 1e-3, fill=False)
        offset_failed = offset is None or offset.isNull() or not offset.isValid()
    except Exception:
        offset_failed = True

    if offset_failed:
        return Finding(
            rule_id="model.wall_thickness_offset",
            severity=Severity.WARNING,
            objects=[obj.Name],
            message=(
                f"'{obj.Name}': el offset hacia adentro de {min_wall_mm / 2:.3f} mm "
                "fallo o produjo geometria invalida — señal de pared mas fina que el "
                "limite en alguna zona local (proxy por offset, no medicion certificada; "
                "puede dar falso positivo en geometria concava/compleja aunque la pared "
                "sea gruesa)."
            ),
            value=min_wall_mm,
            limit=min_wall_mm,
            suggestion="Confirmar con Part → Measure en la zona señalada antes de reforzar; si la geometria es compleja, revisar si el fallo es por curvatura y no por espesor real.",
        )
    return None


_MODEL_RULES = [
    rule_shape_validity,
    rule_zero_or_negative_volume,
    rule_degenerate_bbox,
    rule_wall_thickness_offset,
]


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


def _rule_fdm_overhang(profile: Profile):
    """WARNING si hay caras con angulo de voladizo mayor al critico
    (default 45 grados desde la vertical) que probablemente necesiten
    soporte de impresion FDM.

    LIMITACION HONESTA: muestrea la normal en un solo punto (el punto
    medio del rango de parametros de cada cara) via face.normalAt(u,v).
    Para caras planas eso alcanza; para caras curvas grandes donde la
    normal varia mucho dentro de la misma cara, una sola muestra puede
    no representar toda la cara -- podria pasar por alto voladizo real
    en parte de una cara curva, o marcar una cara que en su mayoria no
    es voladizo. Sirve como screening rapido, no reemplaza la vista de
    voladizo del slicer.
    """
    critical_angle_deg = profile.params.get("critical_overhang_angle_deg", 45.0)
    # default Z=0: convencion estandar de FreeCAD/slicers (apoyar el modelo
    # en la plataforma en Z=0). NO usar el ZMin propio de cada objeto como
    # default -- eso excluiria tambien caras que flotan de verdad (un objeto
    # cuya base real esta en el aire, ej. un brazo en voladizo que arranca
    # en Z=5 sin nada debajo, tiene su propio ZMin=5 y quedaria excluido
    # igual, anulando la deteccion). Si tus piezas no arrancan en Z=0, pasar
    # build_plate_z explicito en profile.params.
    build_plate_z = profile.params.get("build_plate_z", 0.0)
    cos_critical = math.cos(math.radians(critical_angle_deg))

    def _rule(obj, params: dict) -> Optional[Finding]:
        shape = _obj_shape(obj)
        if shape is None or shape.isNull():
            return None
        if getattr(shape, "ShapeType", None) not in ("Solid", "CompSolid"):
            return None

        offending = []
        for face in shape.Faces:
            try:
                u1, u2, v1, v2 = face.ParameterRange
                normal = face.normalAt((u1 + u2) / 2.0, (v1 + v2) / 2.0)
            except Exception:
                continue
            # normal.z fuertemente negativo = cara mirando hacia abajo
            if normal.z < -cos_critical:
                bb = face.BoundBox
                if bb.ZMax <= build_plate_z + 1e-3:
                    continue  # pegada a la plataforma, no es voladizo real
                offending.append(round(bb.Center.z, 2))

        if offending:
            return Finding(
                rule_id="fdm.unsupported_overhang",
                severity=Severity.WARNING,
                objects=[obj.Name],
                message=(
                    f"'{obj.Name}': {len(offending)} cara(s) con angulo de voladizo mayor "
                    f"a {critical_angle_deg}° respecto de la vertical -- probablemente "
                    "necesiten soporte de impresion (muestreo de 1 punto por cara, ver "
                    "docstring de esta regla para la limitacion en caras curvas)."
                ),
                value=float(len(offending)),
                limit=critical_angle_deg,
                context={"face_center_z_mm": offending},
                suggestion="Reorientar la pieza, agregar chaflanes de transicion, o generar soportes en el slicer para esas zonas.",
            )
        return None

    return _rule


_PROCESS_RULE_BUILDERS = {
    "laser": _rule_laser_planarity,
    "resin": _rule_resin_min_wall,
    "cnc_3axis": _rule_cnc_manual_review,
    "fdm": _rule_fdm_overhang,
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
