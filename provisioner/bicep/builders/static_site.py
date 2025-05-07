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
        resource_group_name = manifest.get("resourceGroup", {}).get("name")
        
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
        
        # Extract specific properties for Static Web Apps
        props = service.get("properties", {})
        properties = {}
        
        # Handle repository settings if present
        if props.get("repositoryUrl"):
            properties.update({
                "repositoryUrl": props.get("repositoryUrl"),
                "branch": props.get("branch", "main"),
                "provider": props.get("provider", "GitHub")
            })
        
        # Handle build configuration if present
        if props.get("buildProperties"):
            properties["buildProperties"] = props.get("buildProperties")
        
        # Create resource
        resource = BicepResource(
            name=service["name"],
            type="Microsoft.Web/staticSites",
            api_version=self.api_version,
            location=region,
            sku=sku,
            identity=identity,
            properties=properties,
            tags=tags
        )
        
        # Generate Bicep code
        # Use resource name without hyphens for the Bicep identifier
        safe_name = resource.name.replace('-', '_')
        lines = [
            f"resource {safe_name} '{resource.type}@{resource.api_version}' = {{",
            f"  name: '{resource.name}'",
            f"  location: location"
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
        if properties:
            lines.append("  properties: {")
            for key, value in properties.items():
                if isinstance(value, dict):
                    lines.append(f"    {key}: {{")
                    for k, v in value.items():
                        if isinstance(v, str):
                            lines.append(f"      {k}: '{v}'")
                        else:
                            lines.append(f"      {k}: {v}")
                    lines.append("    }")
                elif isinstance(value, str):
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
        
        # Add an output for the static site URL (using safe name for reference)
        safe_name = resource.name.replace('-', '_')
        output_name = f"{safe_name}_url"
        lines.extend([
            "",
            f"output {output_name} string = {safe_name}.properties.defaultHostname"
        ])
        
        return "\n".join(lines)