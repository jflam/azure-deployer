"""Log Analytics Workspace Bicep builder."""
from typing import Dict, Optional
from ..models import BicepResource

class LogAnalyticsBuilder:
    """Builds Bicep code for Log Analytics Workspaces."""
    
    def __init__(self):
        """Initialize the builder."""
        self.api_version = "2022-10-01"  # Latest stable API version
    
    def build(self, service: Dict, manifest: Dict) -> str:
        """Build a Bicep resource snippet for Log Analytics Workspace.
        
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
            type="Microsoft.OperationalInsights/workspaces",
            api_version=self.api_version,
            location=region,
            sku={
                "name": service["sku"]
            },
            properties={
                "retentionInDays": props.get("retentionDays", 30),
                "features": {
                    "enableLogAccessUsingOnlyResourcePermissions": props.get("features", {}).get("enableResourcePermissions", True)
                },
                "publicNetworkAccessForIngestion": props.get("publicNetworkAccess", "Enabled"),
                "publicNetworkAccessForQuery": props.get("publicNetworkAccess", "Enabled")
            },
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
            f"    name: '{resource.sku['name']}'",
            "  }"
        ])
        
        # Add properties
        lines.append("  properties: {")
        
        # Add retention days
        lines.append(f"    retentionInDays: {resource.properties.get('retentionInDays', 30)}")
        
        # Add features
        features = resource.properties.get("features", {})
        if features:
            lines.append("    features: {")
            for k, v in features.items():
                lines.append(f"      {k}: {str(v).lower()}")
            lines.append("    }")
        
        # Add network access settings
        lines.append(f"    publicNetworkAccessForIngestion: '{resource.properties.get('publicNetworkAccessForIngestion', 'Enabled')}'")
        lines.append(f"    publicNetworkAccessForQuery: '{resource.properties.get('publicNetworkAccessForQuery', 'Enabled')}'")
        
        lines.append("  }")
        
        # Add tags
        if tags:
            lines.append("  tags: {")
            for key, value in tags.items():
                lines.append(f"    {key}: '{value}'")
            lines.append("  }")
        
        lines.append("}")
        
        # Add outputs for workspace ID and primary key (needed by other services)
        safe_name = resource.name.replace('-', '_')
        output_id = f"{safe_name}_id"
        output_customer_id = f"{safe_name}_customer_id"
        output_key = f"{safe_name}_primary_key"
        lines.extend([
            "",
            f"output {output_id} string = {safe_name}.id",
            f"output {output_customer_id} string = {safe_name}.properties.customerId",
            f"@description('Primary shared key for Log Analytics - Note: Contains sensitive information')",
            f"@secure()",
            f"output {output_key} string = listKeys({safe_name}.id, {safe_name}.apiVersion).primarySharedKey"
        ])
        
        return "\n".join(lines)