"""Container Apps Environment Bicep builder."""
from typing import Dict, Optional
from ..models import BicepResource

class ContainerEnvBuilder:
    """Builds Bicep code for Container Apps Environments."""
    
    def __init__(self):
        """Initialize the builder."""
        self.api_version = "2023-05-01"  # Latest stable API version
    
    def build(self, service: Dict, manifest: Dict) -> str:
        """Build a Bicep resource snippet for Container Apps Environment.
        
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
        
        # Get properties
        props = service.get("properties", {})
        
        # Create resource
        resource = BicepResource(
            name=service["name"],
            type="Microsoft.App/managedEnvironments",
            api_version=self.api_version,
            location=region,
            sku={
                "name": service["sku"]
            },
            properties={
                "zoneRedundant": props.get("zoneRedundant", False),
                "workloadProfiles": [
                    {
                        "name": "Consumption",
                        "workloadProfileType": "Consumption"
                    }
                ] if service["sku"] == "Consumption" else None,
                "appLogsConfiguration": {
                    "destination": "log-analytics",
                    "logAnalyticsConfiguration": {
                        "customerId": "[reference(resourceId('Microsoft.OperationalInsights/workspaces', parameters('logAnalyticsName')), '2022-10-01').customerId]",
                        "sharedKey": "[listKeys(resourceId('Microsoft.OperationalInsights/workspaces', parameters('logAnalyticsName')), '2022-10-01').primarySharedKey]"
                    }
                } if props.get("enableLogging", True) else None
            },
            tags=tags
        )
        
        # Generate Bicep code
        lines = [
            f"param logAnalyticsName string",
            "",
            f"resource {resource.name} '{resource.type}@{resource.api_version}' = {{",
            f"  name: '{resource.name}'",
            f"  location: '{resource.location}'"
        ]
        
        # Add SKU
        lines.extend([
            "  sku: {",
            f"    name: '{resource.sku['name']}'",
            "  }"
        ])
        
        # Add properties
        lines.append("  properties: {")
        for key, value in resource.properties.items():
            if value is None:
                continue
            if isinstance(value, dict):
                lines.append(f"    {key}: {{")
                for k, v in value.items():
                    if isinstance(v, str):
                        lines.append(f"      {k}: '{v}'")
                    else:
                        lines.append(f"      {k}: {v}")
                lines.append("    }")
            elif isinstance(value, list):
                lines.append(f"    {key}: [")
                for item in value:
                    if isinstance(item, dict):
                        lines.append("      {")
                        for k, v in item.items():
                            if isinstance(v, str):
                                lines.append(f"        {k}: '{v}'")
                            else:
                                lines.append(f"        {k}: {v}")
                        lines.append("      }")
                lines.append("    ]")
            elif isinstance(value, str):
                lines.append(f"    {key}: '{value}'")
            else:
                lines.append(f"    {key}: {value}")
        lines.append("  }")
        
        # Add tags
        if tags:
            lines.append("  tags: {")
            for key, value in tags.items():
                lines.append(f"    {key}: '{value}'")
            lines.append("  }")
        
        lines.append("}")
        
        return "\n".join(lines)