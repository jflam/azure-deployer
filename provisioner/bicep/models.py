"""Shared data models for Bicep generation."""
from dataclasses import dataclass
from typing import Dict, List, Optional, Union

@dataclass
class BicepParameter:
    """Bicep parameter definition."""
    name: str
    type: str
    default_value: Optional[Union[str, int, bool, Dict, List]] = None
    secure: bool = False
    allowed_values: Optional[List[Union[str, int]]] = None

@dataclass
class BicepResource:
    """Bicep resource definition."""
    name: str
    type: str
    api_version: str
    location: str
    sku: Optional[Dict[str, str]] = None
    identity: Optional[Dict[str, str]] = None
    properties: Optional[Dict] = None
    tags: Optional[Dict[str, str]] = None
    depends_on: Optional[List[str]] = None

@dataclass
class BicepModule:
    """Bicep module definition."""
    name: str
    source: str
    parameters: Dict[str, Union[str, int, bool, Dict]]
    scope: Optional[str] = None
    depends_on: Optional[List[str]] = None