"""
test_validation_operations_mock.py

Tests para validate_fit_clearance usando mocks de Part.Shape (Opción B).
Pueden correr con pytest sin necesidad de FreeCAD abierto.

USO:
  pytest tests/test_validation_operations_mock.py -v
"""

import pytest
import json
import sys
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, "/home/astrid/mcp-free-cad-/AICopilot")

from handlers.validation_operations import ValidationOpsHandler


class TestValidateFitClearanceWithMocks:
    """Suite de tests para validate_fit_clearance usando mocks."""

    @pytest.fixture(autouse=True)
    def setup_mocks(self):
        """Setup: parchear get_document y get_object del handler."""
        self.handler = ValidationOpsHandler()
        self.mock_doc = Mock()
        self.mock_objects = {}

        def mock_get_document():
            return self.mock_doc

        def mock_get_object(name, doc):
            return self.mock_objects.get(name)

        self.handler.get_document = mock_get_document
        self.handler.get_object = mock_get_object

    def _create_mock_shape(self, name: str, volume: float = 1000.0, 
                          common_volume: float = 0.0, distance: float = 0.0):
        """Helper para crear un mock shape con el comportamiento esperado."""
        obj = Mock()
        obj.Name = name
        shape = Mock()
        shape.isNull = Mock(return_value=False)
        shape.Volume = volume

        def mock_common(other):
            common = Mock()
            common.isNull = Mock(return_value=common_volume <= 0)
            common.Volume = common_volume
            return common

        def mock_distToShape(other):
            return (distance,)

        shape.common = mock_common
        shape.distToShape = mock_distToShape
        obj.Shape = shape
        return obj

    def test_missing_shape_a(self):
        """Test: error si falta shape_a."""
        result = self.handler.validate_fit_clearance({"shape_b": "ShapeB"})
        data = json.loads(result)
        assert data["ok"] is False
        assert "shape_a" in data["message"].lower()

    def test_missing_shape_b(self):
        """Test: error si falta shape_b."""
        result = self.handler.validate_fit_clearance({"shape_a": "ShapeA"})
        data = json.loads(result)
        assert data["ok"] is False
        assert "shape_b" in data["message"].lower()

    def test_shape_a_not_found(self):
        """Test: error si shape_a no existe en el documento."""
        self.mock_objects = {"ShapeB": self._create_mock_shape("ShapeB")}
        result = self.handler.validate_fit_clearance({
            "shape_a": "NonExistent",
            "shape_b": "ShapeB",
        })
        data = json.loads(result)
        assert data["ok"] is False
        assert "not found" in data["message"].lower()

    def test_shape_b_not_found(self):
        """Test: error si shape_b no existe en el documento."""
        self.mock_objects = {"ShapeA": self._create_mock_shape("ShapeA")}
        result = self.handler.validate_fit_clearance({
            "shape_a": "ShapeA",
            "shape_b": "NonExistent",
        })
        data = json.loads(result)
        assert data["ok"] is False
        assert "not found" in data["message"].lower()

    def test_interference_detected_default_warning(self):
        """Test Case 1: Interferencia detectada, severity=warning (default)."""
        self.mock_objects = {
            "ShapeA": self._create_mock_shape("ShapeA", volume=1000.0, common_volume=500.0, distance=0.0),
            "ShapeB": self._create_mock_shape("ShapeB", volume=1000.0),
        }
        result = self.handler.validate_fit_clearance({
            "shape_a": "ShapeA",
            "shape_b": "ShapeB",
        })
        data = json.loads(result)
        assert data["ok"] is True

        details = data["details"]
        assert details["interference_volume_mm3"] == 500.0
        assert details["clearance_mm"] == 0.0

        findings = details["findings"]
        assert len(findings) > 0
        assert findings[0]["rule"] == "fit_interference"
        assert findings[0]["severity"] == 2  # warning
        assert "500" in str(findings[0]["value_mm3"])

    def test_interference_severity_override_error(self):
        """Test Case 3: Interferencia con severity override a 'error'."""
        self.mock_objects = {
            "ShapeA": self._create_mock_shape("ShapeA", volume=1000.0, common_volume=500.0, distance=0.0),
            "ShapeB": self._create_mock_shape("ShapeB", volume=1000.0),
        }
        result = self.handler.validate_fit_clearance({
            "shape_a": "ShapeA",
            "shape_b": "ShapeB",
            "interference_severity": "error",
        })
        data = json.loads(result)
        assert data["ok"] is True

        findings = data["details"]["findings"]
        assert findings[0]["rule"] == "fit_interference"
        assert findings[0]["severity"] == 3  # error

    def test_interference_severity_override_info(self):
        """Test: Interferencia con severity override a 'info'."""
        self.mock_objects = {
            "ShapeA": self._create_mock_shape("ShapeA", volume=1000.0, common_volume=500.0, distance=0.0),
            "ShapeB": self._create_mock_shape("ShapeB", volume=1000.0),
        }
        result = self.handler.validate_fit_clearance({
            "shape_a": "ShapeA",
            "shape_b": "ShapeB",
            "interference_severity": "info",
        })
        data = json.loads(result)
        findings = data["details"]["findings"]
        assert findings[0]["severity"] == 1  # info

    def test_clearance_within_range(self):
        """Test Case 2: Holgura dentro del rango [1.5, 2.5], debe ser info."""
        self.mock_objects = {
            "ShapeA": self._create_mock_shape("ShapeA", volume=1000.0, common_volume=0.0, distance=2.0),
            "ShapeB": self._create_mock_shape("ShapeB", volume=1000.0),
        }
        result = self.handler.validate_fit_clearance({
            "shape_a": "ShapeA",
            "shape_b": "ShapeB",
            "target_clearance_min_mm": 1.5,
            "target_clearance_max_mm": 2.5,
        })
        data = json.loads(result)
        assert data["ok"] is True

        details = data["details"]
        assert details["clearance_mm"] == 2.0
        assert details["interference_volume_mm3"] == 0.0

        findings = details["findings"]
        assert findings[0]["rule"] == "fit_clearance_measured"
        assert findings[0]["severity"] == 1  # info
        assert findings[0]["value_mm"] == 2.0

    def test_clearance_too_tight(self):
        """Test: Holgura por debajo del mínimo, debe reportar warning."""
        self.mock_objects = {
            "ShapeA": self._create_mock_shape("ShapeA", volume=1000.0, common_volume=0.0, distance=1.0),
            "ShapeB": self._create_mock_shape("ShapeB", volume=1000.0),
        }
        result = self.handler.validate_fit_clearance({
            "shape_a": "ShapeA",
            "shape_b": "ShapeB",
            "target_clearance_min_mm": 1.5,
            "target_clearance_max_mm": 2.5,
        })
        data = json.loads(result)

        findings = data["details"]["findings"]
        assert findings[0]["rule"] == "fit_clearance_too_tight"
        assert findings[0]["severity"] == 2  # warning
        assert "1.0" in str(findings[0]["value_mm"])

    def test_clearance_too_loose(self):
        """Test: Holgura por encima del máximo, debe reportar warning."""
        self.mock_objects = {
            "ShapeA": self._create_mock_shape("ShapeA", volume=1000.0, common_volume=0.0, distance=3.0),
            "ShapeB": self._create_mock_shape("ShapeB", volume=1000.0),
        }
        result = self.handler.validate_fit_clearance({
            "shape_a": "ShapeA",
            "shape_b": "ShapeB",
            "target_clearance_min_mm": 1.5,
            "target_clearance_max_mm": 2.5,
        })
        data = json.loads(result)

        findings = data["details"]["findings"]
        assert findings[0]["rule"] == "fit_clearance_too_loose"
        assert findings[0]["severity"] == 2  # warning

    def test_faces_touching_exactly_zero_clearance(self):
        """Test Case 4: Caras tocándose (clearance=0.0, no interferencia)."""
        self.mock_objects = {
            "ShapeA": self._create_mock_shape("ShapeA", volume=1000.0, common_volume=0.0, distance=0.0),
            "ShapeB": self._create_mock_shape("ShapeB", volume=1000.0),
        }
        result = self.handler.validate_fit_clearance({
            "shape_a": "ShapeA",
            "shape_b": "ShapeB",
        })
        data = json.loads(result)
        assert data["ok"] is True

        details = data["details"]
        assert details["interference_volume_mm3"] == 0.0
        assert details["clearance_mm"] == 0.0

        findings = details["findings"]
        assert findings[0]["rule"] == "fit_clearance_measured"
        assert findings[0]["severity"] == 1  # info
        assert findings[0]["value_mm"] == 0.0

    def test_clearance_without_range_just_reports_distance(self):
        """Test: Si no hay rango objetivo, solo reporta la distancia (info)."""
        self.mock_objects = {
            "ShapeA": self._create_mock_shape("ShapeA", volume=1000.0, common_volume=0.0, distance=5.5),
            "ShapeB": self._create_mock_shape("ShapeB", volume=1000.0),
        }
        result = self.handler.validate_fit_clearance({
            "shape_a": "ShapeA",
            "shape_b": "ShapeB",
        })
        data = json.loads(result)
        assert data["ok"] is True

        findings = data["details"]["findings"]
        assert findings[0]["rule"] == "fit_clearance_measured"
        assert findings[0]["value_mm"] == 5.5

    def test_large_interference_volume(self):
        """Test: Interferencia grande (>1mm³) es detectada."""
        self.mock_objects = {
            "ShapeA": self._create_mock_shape("ShapeA", volume=1000.0, common_volume=1234.5, distance=0.0),
            "ShapeB": self._create_mock_shape("ShapeB", volume=1000.0),
        }
        result = self.handler.validate_fit_clearance({
            "shape_a": "ShapeA",
            "shape_b": "ShapeB",
        })
        data = json.loads(result)

        details = data["details"]
        assert details["interference_volume_mm3"] == 1234.5
        assert data["details"]["findings"][0]["rule"] == "fit_interference"

    def test_negligible_interference_below_threshold(self):
        """Test: Interferencia muy pequeña (<1e-6) es ignorada (truncamiento numérico)."""
        self.mock_objects = {
            "ShapeA": self._create_mock_shape("ShapeA", volume=1000.0, common_volume=1e-9, distance=0.0),
            "ShapeB": self._create_mock_shape("ShapeB", volume=1000.0),
        }
        result = self.handler.validate_fit_clearance({
            "shape_a": "ShapeA",
            "shape_b": "ShapeB",
        })
        data = json.loads(result)

        findings = data["details"]["findings"]
        assert findings[0]["rule"] == "fit_clearance_measured"
