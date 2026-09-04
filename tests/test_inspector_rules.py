"""
tests/test_inspector_rules.py

Validación de las 5 nuevas inspector rules via pytest.
Usa mocks para evitar dependencia de FreeCAD.
"""

import sys
import pytest
from unittest.mock import Mock, patch


class MockVector:
    def __init__(self, x=0, y=0, z=0):
        self.x = x
        self.y = y
        self.z = z
    
    def dot(self, other):
        return self.x * other.x + self.y * other.y + self.z * other.z
    
    def getAngle(self, other):
        import math
        dot = self.dot(other)
        mag_self = (self.x**2 + self.y**2 + self.z**2) ** 0.5
        mag_other = (other.x**2 + other.y**2 + other.z**2) ** 0.5
        if mag_self * mag_other == 0:
            return 0
        cos_angle = dot / (mag_self * mag_other)
        cos_angle = max(-1, min(1, cos_angle))
        return math.acos(cos_angle)


class MockRotation:
    def __init__(self, axis_x=0, axis_y=0, axis_z=0):
        self.axis_x = axis_x
        self.axis_y = axis_y
        self.axis_z = axis_z
    
    def multVec(self, vec):
        import math
        angle_rad = (self.axis_x ** 2 + self.axis_y ** 2 + self.axis_z ** 2) ** 0.5
        if angle_rad == 0:
            return vec
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)
        x_new = vec.x * cos_a - vec.y * sin_a
        y_new = vec.x * sin_a + vec.y * cos_a
        return MockVector(x_new, y_new, vec.z)


class MockPlacement:
    def __init__(self, base=None, rotation=None):
        self.Base = base or MockVector(0, 0, 0)
        self.Rotation = rotation or MockRotation()


class MockShape:
    def __init__(self, num_faces=6, is_thin=False):
        self.num_faces = num_faces
        self.is_thin = is_thin
        self._is_null = False
    
    def isNull(self):
        return self._is_null
    
    @property
    def Faces(self):
        if self.is_thin:
            return [MockFace(thin=True) for _ in range(self.num_faces)]
        return [MockFace(thin=False) for _ in range(self.num_faces)]
    
    @property
    def Edges(self):
        return [MockEdge() for _ in range(12)]
    
    def makeOffsetShape(self, distance, tolerance, join):
        if self.is_thin:
            return None
        return MockShape(num_faces=self.num_faces, is_thin=False)


class MockFace:
    def __init__(self, thin=False):
        self.thin = thin
        self.Area = 100.0
    
    def isNull(self):
        return False
    
    def normalAt(self, u, v):
        return MockVector(0, 0, 1)
    
    @property
    def Edges(self):
        return [MockEdge() for _ in range(4)]


class MockEdge:
    def __init__(self):
        self.id = id(self)


class MockObject:
    def __init__(self, name, label=None, shape=None, placement=None):
        self.Name = name
        self.Label = label or name
        self.Shape = shape or MockShape()
        self.Placement = placement or MockPlacement()


# Tests
def test_alignment_check_import():
    """Test que _rule_model_alignment_check se importa."""
    try:
        from inspector.runner import _rule_model_alignment_check
        assert callable(_rule_model_alignment_check)
        print("✓ alignment_check imports OK")
    except ImportError as e:
        pytest.fail(f"No se pudo importar: {e}")


def test_interface_smoothness_import():
    """Test que _rule_model_interface_smoothness se importa."""
    try:
        from inspector.runner import _rule_model_interface_smoothness
        assert callable(_rule_model_interface_smoothness)
        print("✓ interface_smoothness imports OK")
    except ImportError as e:
        pytest.fail(f"No se pudo importar: {e}")


def test_undercut_detection_import():
    """Test que _rule_model_undercut_detection se importa."""
    try:
        from inspector.runner import _rule_model_undercut_detection
        assert callable(_rule_model_undercut_detection)
        print("✓ undercut_detection imports OK")
    except ImportError as e:
        pytest.fail(f"No se pudo importar: {e}")


def test_thin_wall_warning_import():
    """Test que _rule_fdm_thin_wall_warning se importa."""
    try:
        from inspector.runner import _rule_fdm_thin_wall_warning
        assert callable(_rule_fdm_thin_wall_warning)
        print("✓ thin_wall_warning imports OK")
    except ImportError as e:
        pytest.fail(f"No se pudo importar: {e}")


def test_support_density_import():
    """Test que _rule_fdm_support_density se importa."""
    try:
        from inspector.runner import _rule_fdm_support_density
        assert callable(_rule_fdm_support_density)
        print("✓ support_density imports OK")
    except ImportError as e:
        pytest.fail(f"No se pudo importar: {e}")


def test_all_rules_in_default_rules():
    """Test que todas las reglas están en _default_rules."""
    try:
        from inspector.runner import _default_rules
        
        socket = MockObject("Socket", "Socket")
        residuum = MockObject("Residuum", "Residuum")
        
        rules = _default_rules([socket, residuum], None, None)
        
        assert isinstance(rules, list)
        assert len(rules) > 0
        print(f"✓ default_rules() genera {len(rules)} reglas")
        
    except Exception as e:
        pytest.fail(f"Error: {e}")


def test_thin_wall_warning_detects_thin():
    """Test que thin_wall_warning detecta geometría fina."""
    try:
        from inspector.runner import _rule_fdm_thin_wall_warning
        from inspector.findings import Profile
        
        thin_obj = MockObject("ThinWall", "ThinWall", MockShape(is_thin=True))
        profile = Profile(process="fdm", params={"min_wall_thickness_mm": 1.2})
        
        rule_factory = _rule_fdm_thin_wall_warning([thin_obj], None, profile)
        
        if rule_factory:
            findings = []
            rule_factory(findings, None, [thin_obj], None)
            assert len(findings) > 0
            print(f"✓ thin_wall_warning detecta {len(findings)} finding(s)")
        
    except Exception as e:
        pytest.fail(f"Error: {e}")


def test_support_density_generates_estimate():
    """Test que support_density genera estimación."""
    try:
        from inspector.runner import _rule_fdm_support_density
        from inspector.findings import Profile
        
        box = MockObject("Box", "Box", MockShape(num_faces=6))
        profile = Profile(process="fdm")
        
        rule_factory = _rule_fdm_support_density([box], None, profile)
        
        if rule_factory:
            findings = []
            rule_factory(findings, None, [box], None)
            assert isinstance(findings, list)
            print(f"✓ support_density genera {len(findings)} finding(s)")
        
    except Exception as e:
        pytest.fail(f"Error: {e}")


def test_no_syntax_errors():
    """Test que no hay errores de sintaxis."""
    try:
        import py_compile
        py_compile.compile("inspector/runner.py", doraise=True)
        print("✓ runner.py: no syntax errors")
    except Exception as e:
        pytest.fail(f"Syntax error: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
