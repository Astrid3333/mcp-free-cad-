"""
test_fit_clearance_live_standalone.py

Tests en vivo para validate_fit_clearance (Opción A).
Diseñado para correr en la consola Python de FreeCAD, donde el documento y
los shapes son reales. No requiere pytest, solo puro Python.

USO:
  1. Abrir FreeCAD con el addon AICopilot activo
  2. En la consola Python de FreeCAD:
     >>> import sys
     >>> sys.path.insert(0, "/home/astrid/mcp-free-cad-")
     >>> from tests.test_fit_clearance_live_standalone import run_all_tests
     >>> run_all_tests()

Salida: reporte con PASS/FAIL para cada caso, y cleanup automático de geometría de prueba.
"""

import json
import sys
from typing import Dict, Any, List, Optional

sys.path.insert(0, "/home/astrid/mcp-free-cad-/AICopilot")

from handlers.validation_operations import ValidationOpsHandler


class TestCase:
    """Encapsula un caso de prueba con setup, test, y cleanup."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.passed = False
        self.message = ""
        self.created_objects = []

    def cleanup(self, doc):
        """Elimina objetos de prueba creados."""
        for obj_name in self.created_objects:
            if obj_name in doc.Objects:
                doc.removeObject(obj_name)
        doc.recompute()

    def __str__(self):
        icon = "✓ PASS" if self.passed else "✗ FAIL"
        return f"{icon} | {self.name}\n        {self.description}\n        {self.message}"


def _ensure_part_module():
    """Intenta cargar Part de FreeCAD; raise si no está disponible."""
    try:
        import FreeCAD
        return FreeCAD.Part
    except ImportError:
        raise RuntimeError("FreeCAD no disponible — este test debe correr en la consola Python de FreeCAD")


def test_case_1_interference_default_warning(doc) -> TestCase:
    """Caso 1: Dos cubos que se superponen en 500 mm³ exacto. Esperado: fit_interference con severity=warning (default)."""
    test = TestCase(
        "Case 1: Interferencia 500mm³ → warning",
        "Cubos en (0,0,0) y (5,0,0), overlap=5×10×10=500mm³"
    )

    try:
        Part = _ensure_part_module()

        cube_a = doc.addObject("Part::Feature", "TestCube_1A")
        cube_a.Shape = Part.makeBox(10, 10, 10, (0, 0, 0))

        cube_b = doc.addObject("Part::Feature", "TestCube_1B")
        cube_b.Shape = Part.makeBox(10, 10, 10, (5, 0, 0))

        test.created_objects = ["TestCube_1A", "TestCube_1B"]
        doc.recompute()

        handler = ValidationOpsHandler()
        result = handler.validate_fit_clearance({
            "shape_a": "TestCube_1A",
            "shape_b": "TestCube_1B",
        })

        data = json.loads(result)
        if not data.get("ok"):
            test.message = f"Handler error: {data.get('message')}"
            return test

        details = data.get("details", {})
        interference_vol = details.get("interference_volume_mm3", 0)
        findings = details.get("findings", [])

        if not findings or findings[0].get("rule") != "fit_interference":
            test.message = f"Expected fit_interference finding, got: {findings}"
            return test

        if findings[0].get("severity") != 2:
            test.message = f"Expected severity 2 (warning), got: {findings[0].get('severity')}"
            return test

        if abs(interference_vol - 500.0) > 1.0:
            test.message = f"Expected interference ~500mm³, got: {interference_vol:.2f}"
            return test

        test.passed = True
        test.message = f"Interferencia detectada: {interference_vol:.2f} mm³, severity=warning ✓"

    except Exception as e:
        test.message = f"Exception: {e}"

    return test


def test_case_2_clearance_within_range(doc) -> TestCase:
    """Caso 2: Dos cubos con holgura de 2.0 mm, dentro de rango [1.5, 2.5]. Esperado: fit_clearance_measured con severity=info."""
    test = TestCase(
        "Case 2: Holgura 2.0mm dentro de rango [1.5, 2.5]",
        "Cubos en (0,0,0) y (12,0,0), distancia=2.0mm"
    )

    try:
        Part = _ensure_part_module()

        cube_a = doc.addObject("Part::Feature", "TestCube_2A")
        cube_a.Shape = Part.makeBox(10, 10, 10, (0, 0, 0))

        cube_b = doc.addObject("Part::Feature", "TestCube_2B")
        cube_b.Shape = Part.makeBox(10, 10, 10, (12, 0, 0))

        test.created_objects = ["TestCube_2A", "TestCube_2B"]
        doc.recompute()

        handler = ValidationOpsHandler()
        result = handler.validate_fit_clearance({
            "shape_a": "TestCube_2A",
            "shape_b": "TestCube_2B",
            "target_clearance_min_mm": 1.5,
            "target_clearance_max_mm": 2.5,
        })

        data = json.loads(result)
        if not data.get("ok"):
            test.message = f"Handler error: {data.get('message')}"
            return test

        details = data.get("details", {})
        clearance_mm = details.get("clearance_mm", -1)
        findings = details.get("findings", [])

        if not findings or findings[0].get("rule") != "fit_clearance_measured":
            test.message = f"Expected fit_clearance_measured, got: {findings}"
            return test

        if findings[0].get("severity") != 1:
            test.message = f"Expected severity 1 (info), got: {findings[0].get('severity')}"
            return test

        if abs(clearance_mm - 2.0) > 0.01:
            test.message = f"Expected clearance ~2.0mm, got: {clearance_mm:.4f}"
            return test

        test.passed = True
        test.message = f"Holgura: {clearance_mm:.4f} mm dentro de rango [1.5, 2.5] ✓"

    except Exception as e:
        test.message = f"Exception: {e}"

    return test


def test_case_3_interference_severity_override(doc) -> TestCase:
    """Caso 3: Interferencia de 500mm³, pero con severity override a 'error'. Esperado: fit_interference con severity=error (3)."""
    test = TestCase(
        "Case 3: Interferencia 500mm³ con severity='error'",
        "Override de severity: default es warning, pero pasamos 'error'"
    )

    try:
        Part = _ensure_part_module()

        cube_a = doc.addObject("Part::Feature", "TestCube_3A")
        cube_a.Shape = Part.makeBox(10, 10, 10, (0, 0, 0))

        cube_b = doc.addObject("Part::Feature", "TestCube_3B")
        cube_b.Shape = Part.makeBox(10, 10, 10, (5, 0, 0))

        test.created_objects = ["TestCube_3A", "TestCube_3B"]
        doc.recompute()

        handler = ValidationOpsHandler()
        result = handler.validate_fit_clearance({
            "shape_a": "TestCube_3A",
            "shape_b": "TestCube_3B",
            "interference_severity": "error",
        })

        data = json.loads(result)
        if not data.get("ok"):
            test.message = f"Handler error: {data.get('message')}"
            return test

        details = data.get("details", {})
        findings = details.get("findings", [])

        if not findings or findings[0].get("rule") != "fit_interference":
            test.message = f"Expected fit_interference, got: {findings}"
            return test

        if findings[0].get("severity") != 3:
            test.message = f"Expected severity 3 (error), got: {findings[0].get('severity')}"
            return test

        test.passed = True
        test.message = f"Severidad override confirmado: severity=error (3) ✓"

    except Exception as e:
        test.message = f"Exception: {e}"

    return test


def test_case_4_faces_touching_exactly(doc) -> TestCase:
    """Caso 4: Dos cubos con caras tocándose exactamente (clearance=0.0). Esperado: fit_clearance_measured con severity=info, clearance=0.0mm."""
    test = TestCase(
        "Case 4: Caras tocándose exactamente (clearance=0.0mm)",
        "Cubos en (0,0,0) y (10,0,0), se tocan pero no se superponen"
    )

    try:
        Part = _ensure_part_module()

        cube_a = doc.addObject("Part::Feature", "TestCube_4A")
        cube_a.Shape = Part.makeBox(10, 10, 10, (0, 0, 0))

        cube_b = doc.addObject("Part::Feature", "TestCube_4B")
        cube_b.Shape = Part.makeBox(10, 10, 10, (10, 0, 0))

        test.created_objects = ["TestCube_4A", "TestCube_4B"]
        doc.recompute()

        handler = ValidationOpsHandler()
        result = handler.validate_fit_clearance({
            "shape_a": "TestCube_4A",
            "shape_b": "TestCube_4B",
        })

        data = json.loads(result)
        if not data.get("ok"):
            test.message = f"Handler error: {data.get('message')}"
            return test

        details = data.get("details", {})
        interference_vol = details.get("interference_volume_mm3", 0)
        clearance_mm = details.get("clearance_mm", -1)
        findings = details.get("findings", [])

        if interference_vol > 1e-6:
            test.message = f"Expected no interference (vol~0), got: {interference_vol}"
            return test

        if abs(clearance_mm) > 0.01:
            test.message = f"Expected clearance ~0.0mm (tocándose), got: {clearance_mm:.4f}"
            return test

        if not findings or findings[0].get("rule") != "fit_clearance_measured":
            test.message = f"Expected fit_clearance_measured, got: {findings}"
            return test

        test.passed = True
        test.message = (
            f"Caras tocándose: vol=0.0mm³ (no interferencia), "
            f"clearance={clearance_mm:.4f}mm (ambiguedad conocida entre 'tocándose' y 'holgura cero') ✓"
        )

    except Exception as e:
        test.message = f"Exception: {e}"

    return test


def run_all_tests():
    """Ejecuta todos los tests, imprime reporte, limpia."""
    try:
        import FreeCAD
    except ImportError:
        print("❌ FreeCAD no importable — este script debe correr en la consola Python de FreeCAD")
        return

    doc = FreeCAD.activeDocument()
    if doc is None:
        print("❌ No hay documento activo en FreeCAD — abre un documento primero")
        return

    print("\n" + "=" * 70)
    print("  TEST SUITE: validate_fit_clearance (Opción A - Live)")
    print("=" * 70)

    tests: List[TestCase] = [
        test_case_1_interference_default_warning(doc),
        test_case_2_clearance_within_range(doc),
        test_case_3_interference_severity_override(doc),
        test_case_4_faces_touching_exactly(doc),
    ]

    print()
    for test in tests:
        print(test)
        print()
        test.cleanup(doc)

    passed_count = sum(1 for t in tests if t.passed)
    total_count = len(tests)
    status_icon = "✅" if passed_count == total_count else "⚠️" if passed_count > 0 else "❌"

    print("=" * 70)
    print(f"{status_icon} RESUMEN: {passed_count}/{total_count} tests passed")
    print("=" * 70 + "\n")

    return {
        "passed": passed_count,
        "total": total_count,
        "tests": [(t.name, t.passed) for t in tests],
    }


if __name__ == "__main__":
    print("⚠️  Este script debe importarse y ejecutarse desde la consola Python de FreeCAD")
    print("   Uso: from tests.test_fit_clearance_live_standalone import run_all_tests; run_all_tests()")
