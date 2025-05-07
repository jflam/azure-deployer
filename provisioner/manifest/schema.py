"""Pydantic models for manifest validation."""
from typing import Dict, List, Optional, Union
from pydantic import BaseModel, Field

class ServiceCapacity(BaseModel):
    """Service capacity requirements."""
    unit: str
    required: int
    environment_name: Optional[str] = None
    resource_group: Optional[str] = None

class ServiceSecret(BaseModel):
    """Service secret reference."""
    alias: str
    name: str

class Service(BaseModel):
    """Service definition."""
    name: str
    type: str
    region: Optional[str] = None
    sku: str
    capacity: Optional[ServiceCapacity] = None
    secrets: Optional[Dict[str, str]] = None
    properties: Optional[Dict[str, Union[str, int, bool, Dict]]] = None
    skip_quota_check: bool = False

class ResourceGroup(BaseModel):
    """Resource group configuration."""
    name: str
    region: Optional[str] = None

class Metadata(BaseModel):
    """Manifest metadata."""
    name: str
    description: Optional[str] = None
    version: str

class Manifest(BaseModel):
    """Root manifest schema."""
    metadata: Metadata
    subscription: Optional[str] = None
    resource_group: ResourceGroup = Field(alias='resourceGroup')
    region: str = ""
    allowed_regions: List[str] = Field(default_factory=list, alias='allowedRegions')
    deployment: Optional[Dict[str, str]] = None
    tags: Dict[str, str] = Field(default_factory=dict)
    key_vault: Optional[str] = Field(default=None, alias='keyVault')
    services: List[Service]