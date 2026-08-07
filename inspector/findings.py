"""Tipos base del Inspector DRC: severidad, hallazgo, y perfil de proceso."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Finding:
    rule_id: str
    severity: Severity
    objects: List[str]
    message: str
    value: Optional[float] = None
    limit: Optional[float] = None
    suggestion: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Profile:
    process: str
    machine: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
