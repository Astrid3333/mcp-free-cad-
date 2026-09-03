"""
conftest.py — Fixtures compartidas para todos los tests pytest.

Define:
- ValidationOpsHandler fixture (Opción B)
- Mock shapes para tests sin FreeCAD (Opción B)
"""

import pytest
import sys
import json
from unittest.mock import Mock, MagicMock, patch

sys.path.insert(0, "/home/astrid/mcp-free-cad-/AICopilot")


@pytest.fixture
def validation_handler():
    """Devuelve un ValidationOpsHandler listo para usar."""
    from handlers.validation_operations import ValidationOpsHandler
    return ValidationOpsHandler()


class MockShape:
    """Mock de FreeCAD Part.Shape para tests sin FreeCAD."""

    def __init__(self, name: str = "MockShape", volume: float = 1000.0):
        self.name = name
        self.volume = volume
        self.isNull = Mock(return_value=False)
        self.isValid = Mock(return_value=True)
        self.ShapeType = "Solid"
        self.Edges = []
        self.Faces = []
        self.BoundBox = MockBoundBox()

    def common(self, other: "MockShape") -> "MockShape":
        """Simula boolean common() con volumen especificado."""
        return self

    def distToShape(self, other: "MockShape"):
        """Simula distToShape() devolviendo (distancia, ...)."""
        return (0.0,)


class MockBoundBox:
    """Mock de BoundBox de FreeCAD."""

    def __init__(self, x=10.0, y=10.0, z=10.0):
        self.XLength = x
        self.YLength = y
        self.ZLength = z
        self.ZMax = 10.0


class MockObject:
    """Mock de un objeto FreeCAD (Part::Feature)."""

    def __init__(self, name: str, shape: MockShape = None):
        self.Name = name
        self.Shape = shape or MockShape(name)


@pytest.fixture
def mock_shape_interference():
    """Mock de un shape que genera interferencia en common()."""
    shape = MockShape("InterferenceShape", volume=500.0)
    
    def mock_common(other):
        result = MockShape("CommonResult")
        result.volume = 500.0
        result.isNull = Mock(return_value=False)
        return result
    
    shape.common = mock_common
    return shape


@pytest.fixture
def mock_shape_clearance():
    """Mock de un shape con holgura medible."""
    shape = MockShape("ClearanceShape", volume=1000.0)
    
    def mock_common(other):
        result = MockShape("CommonResult")
        result.volume = 0.0
        result.isNull = Mock(return_value=True)
        return result
    
    def mock_distToShape(other):
        return (2.0,)  # 2mm de holgura
    
    shape.common = mock_common
    shape.distToShape = mock_distToShape
    return shape


@pytest.fixture
def mock_freecad_doc():
    """Mock de un FreeCAD.Document."""
    doc = Mock()
    doc.Objects = {}
    
    def mock_get_object(name):
        return doc.Objects.get(name)
    
    doc.getObject = mock_get_object
    return doc
