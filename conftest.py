"""
conftest.py (raíz)

Mockea FreeCAD y otras dependencias de FreeCAD antes de importar handlers.
Esto permite que pytest importe ValidationOpsHandler sin tener FreeCAD instalado.
"""

import sys
from unittest.mock import MagicMock

# Mockear FreeCAD y sus submódulos ANTES de que pytest intente importar handlers
sys.modules['FreeCAD'] = MagicMock()
sys.modules['FreeCADGui'] = MagicMock()
sys.modules['Part'] = MagicMock()
sys.modules['Sketcher'] = MagicMock()

# Configurar algunos atributos que los handlers esperan
import FreeCAD
FreeCAD.activeDocument = MagicMock(return_value=MagicMock())
FreeCAD.GuiUp = False
