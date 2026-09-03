# Test Suite para mcp-free-cad-

## Estructura

## Opción A: Tests Live

**Archivo:** `test_fit_clearance_live_standalone.py`

Requiere FreeCAD abierto.

**En la consola Python de FreeCAD:**
```python
import sys
sys.path.insert(0, "/home/astrid/mcp-free-cad-")
from tests.test_fit_clearance_live_standalone import run_all_tests
run_all_tests()
```

**Casos:**
1. Interferencia 500mm³ → warning
2. Holgura 2.0mm en rango [1.5, 2.5] → info
3. Interferencia con severity override → error
4. Caras tocándose (clearance=0.0) → info

## Opción B: Tests con Mocks (Pytest)

**Archivo:** `test_validation_operations_mock.py`

No requiere FreeCAD.

```bash
pytest tests/test_validation_operations_mock.py -v
```

**14 tests:** cubre casos 1-4 + error handling + edge cases.

Ver TESTING.md para más detalles.
