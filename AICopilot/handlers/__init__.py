# FreeCAD MCP Handlers
# Modular operation handlers for the socket server

from .base import BaseHandler
from .primitives import PrimitivesHandler
from .boolean_ops import BooleanOpsHandler
from .transforms import TransformsHandler
from .sketch_ops import SketchOpsHandler
from .partdesign_ops import PartDesignOpsHandler
from .part_ops import PartOpsHandler
from .cam_ops import CAMOpsHandler
from .cam_tools import CAMToolsHandler
from .cam_tool_controllers import CAMToolControllersHandler
from .draft_ops import DraftOpsHandler
from .view_ops import ViewOpsHandler
from .document_ops import DocumentOpsHandler
from .measurement_ops import MeasurementOpsHandler
from .spreadsheet_ops import SpreadsheetOpsHandler
from .mesh_ops import MeshOpsHandler
from .spatial_ops import SpatialOpsHandler
from .inspector_ops import InspectorOpsHandler
from .macro_ops import MacroOpsHandler
from .introspection_ops import IntrospectionOpsHandler
from .sketch_builder_ops import SketchBuilderOpsHandler
from .verification_ops import VerificationOpsHandler
from .fixture_ops import FixtureOpsHandler
from .compliant_ops import CompliantOpsHandler
from .tendon_routing_ops import TendonRoutingHandler
from .contact_pressure_ops import ContactPressureOpsHandler
from .growth_socket_ops import GrowthSocketOpsHandler
from .quick_connect_ops import QuickConnectOpsHandler
from .fitting_history_ops import FittingHistoryOpsHandler
from .lightweight_ops import LightweightOpsHandler
from .organic_ops import OrganicOpsHandler
from .four_bar_knee_ops import FourBarKneeHandler

__all__ = [
    'BaseHandler',
    'PrimitivesHandler',
    'BooleanOpsHandler',
    'TransformsHandler',
    'SketchOpsHandler',
    'PartDesignOpsHandler',
    'PartOpsHandler',
    'CAMOpsHandler',
    'CAMToolsHandler',
    'CAMToolControllersHandler',
    'DraftOpsHandler',
    'ViewOpsHandler',
    'DocumentOpsHandler',
    'MeasurementOpsHandler',
    'SpreadsheetOpsHandler',
    'MeshOpsHandler',
    'SpatialOpsHandler',
    'InspectorOpsHandler',
    'MacroOpsHandler',
    'IntrospectionOpsHandler',
    'SketchBuilderOpsHandler',
    'VerificationOpsHandler',
    'FixtureOpsHandler',
    'CompliantOpsHandler',
    'TendonRoutingHandler',
    'ContactPressureOpsHandler',
    'GrowthSocketOpsHandler',
    'QuickConnectOpsHandler',
    'FittingHistoryOpsHandler',
    'LightweightOpsHandler',
]
