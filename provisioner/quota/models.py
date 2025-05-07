"""Data models for quota information."""
from dataclasses import dataclass
from typing import Dict, List, Optional

@dataclass
class QuotaInfo:
    """Information about a specific quota."""
    unit: str
    current_usage: float
    limit: float
    required: float
    
    @property
    def available(self) -> float:
        """Calculate available quota."""
        return self.limit - self.current_usage
    
    @property
    def is_sufficient(self) -> bool:
        """Check if available quota is sufficient."""
        return self.available >= self.required

@dataclass
class ResourceQuota:
    """Quota information for a specific resource type in a region."""
    resource_type: str
    region: str
    quotas: Dict[str, QuotaInfo]
    
    def is_sufficient(self) -> bool:
        """Check if all quotas are sufficient."""
        return all(q.is_sufficient for q in self.quotas.values())

@dataclass
class RegionAnalysis:
    """Analysis of quota availability across regions."""
    regions: Dict[str, List[ResourceQuota]]
    viable_regions: List[str]
    
    def save(self, output_path: str) -> None:
        """Save region analysis to JSON file.
        
        Args:
            output_path: Path to write the JSON file.
        """
        import json
        # Convert to dict structure
        result = {
            "viable_regions": self.viable_regions,
            "regions": {
                region: [
                    {
                        "resource_type": quota.resource_type,
                        "quotas": {
                            unit: {
                                "current": q.current_usage,
                                "limit": q.limit,
                                "required": q.required,
                                "available": q.available,
                                "sufficient": q.is_sufficient
                            } for unit, q in quota.quotas.items()
                        }
                    } for quota in quotas
                ] for region, quotas in self.regions.items()
            }
        }
        
        with open(output_path, 'w') as f:
            json.dump(result, f, indent=2)