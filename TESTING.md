# Testing Guide

## Setup rápido

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. (Opción B) Correr tests con mocks (sin FreeCAD)
pytest tests/test_validation_operations_mock.py -v

# 3. (Opción A) Correr tests live desde la consola Python de FreeCAD
#    (ver tests/README.md para detalles)
```

## Opción A: Tests Live (En Vivo)

Requiere FreeCAD abierto. Valida geometría real.

**En la consola Python de FreeCAD:**
```python
import sys
sys.path.insert(0, "/home/astrid/mcp-free-cad-")
from tests.test_fit_clearance_live_standalone import run_all_tests
result = run_all_tests()
print(result)  # {"passed": 4, "total": 4, "tests": [...]}
```

## Opción B: Tests con Mocks (Pytest)

No requiere FreeCAD. Rápido, determinista.

```bash
pytest tests/test_validation_operations_mock.py -v
```

Para más detalles, ver `tests/README.md`.
