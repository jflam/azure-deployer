"""Static Web App Bicep builder."""
from typing import Dict, Optional
from ..models import BicepResource

class StaticSiteBuilder:
    """Builds Bicep code for Static Web Apps."""
    
    def __init__(self):
        """Initialize the builder."""
        self.api_version = "2023-01-01"  # Latest stable API version
    
    def build(self, service: Dict, manifest: Dict) -> str:
        """Build a Bicep resource snippet for Static Web App.
        
        Args:
            service: Service configuration from manifest.
            manifest: Full manifest configuration.
            
        Returns:
            str: Bicep resource definition.
        """
        region = service.get("region") or manifest.get("region")
        
        # Merge tags
        tags = {
            **(manifest.get("tags", {})),
            **(service.get("properties", {}).get("tags", {}))
        }
        
        # Build SKU object
        sku_name = service["sku"]
        sku = {
            "name": sku_name,
            "tier": sku_name
        }
        
        # Build identity block if needed
        identity = None
        if service.get("identity") == "SystemAssigned":
            identity = {
                "type": "SystemAssigned"
            }
        
        # Create resource
        resource = BicepResource(
            name=service["name"],
            type="Microsoft.Web/staticSites",
            api_version=self.api_version,
            location=region,
            sku=sku,
            identity=identity,
            properties=service.get("properties", {}),
            tags=tags
        )
        
        # Generate Bicep code
        lines = [
            f"resource {resource.name} '{resource.type}@{resource.api_version}' = {{",
            f"  name: '{resource.name}'",
            f"  location: '{resource.location}'"
        ]
        
        # Add SKU
        lines.extend([
            "  sku: {",
            f"    name: '{sku['name']}'",
            f"    tier: '{sku['tier']}'",
            "  }"
        ])
        
        # Add identity if present
        if identity:
            lines.extend([
                "  identity: {",
                f"    type: '{identity['type']}'",
                "  }"
            ])
        
        # Add properties if present
        if resource.properties:
            lines.append("  properties: {")
            for key, value in resource.properties.items():
                if isinstance(value, str):
                    lines.append(f"    {key}: '{value}'")
                else:
                    lines.append(f"    {key}: {value}")
            lines.append("  }")
        
        # Add tags if present
        if tags:
            lines.append("  tags: {")
            for key, value in tags.items():
                lines.append(f"    {key}: '{value}'")
            lines.append("  }")
        
        lines.append("}")
        
        return "\n".join(lines)