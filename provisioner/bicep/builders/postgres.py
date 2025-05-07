"""PostgreSQL Flexible Server Bicep builder."""
from typing import Dict, Optional
from ..models import BicepResource, BicepParameter

class PostgresBuilder:
    """Builds Bicep code for PostgreSQL Flexible Servers."""
    
    def __init__(self):
        """Initialize the builder."""
        self.api_version = "2023-06-01"  # Latest stable API version
    
    def build(self, service: Dict, manifest: Dict) -> str:
        """Build a Bicep resource snippet for PostgreSQL Flexible Server.
        
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
        
        # Create admin password parameter
        admin_password_param = BicepParameter(
            name=f"{service['name']}AdminPassword",
            type="string",
            secure=True
        )
        
        # Create resource
        resource = BicepResource(
            name=service["name"],
            type="Microsoft.DBforPostgreSQL/flexibleServers",
            api_version=self.api_version,
            location=region,
            sku={
                "name": service["sku"],
                "tier": props.get("tier", "Burstable")
            },
            properties={
                "version": props.get("version", "16"),
                "storage": {
                    "storageSizeGB": props.get("storageGB", 32)
                },
                "backup": {
                    "backupRetentionDays": props.get("backup", {}).get("retentionDays", 7),
                    "geoRedundantBackup": props.get("backup", {}).get("geoRedundant", False)
                },
                "network": {
                    "delegatedSubnetResourceId": props.get("network", {}).get("delegatedSubnetResourceId", ""),
                    "privateDnsZoneArmResourceId": props.get("network", {}).get("privateDnsZoneResourceId", "")
                },
                "administratorLogin": props.get("administratorLogin", "pgadmin"),
                "administratorLoginPassword": f"@secure().{admin_password_param.name}"
            },
            tags=tags
        )
        
        # Generate Bicep code
        lines = [
            f"@secure()",
            f"param {admin_password_param.name} string",
            "",
            f"resource {resource.name} '{resource.type}@{resource.api_version}' = {{",
            f"  name: '{resource.name}'",
            f"  location: '{resource.location}'"
        ]
        
        # Add SKU
        lines.extend([
            "  sku: {",
            f"    name: '{resource.sku['name']}'",
            f"    tier: '{resource.sku['tier']}'",
            "  }"
        ])
        
        # Add properties
        lines.append("  properties: {")
        for key, value in resource.properties.items():
            if isinstance(value, dict):
                lines.append(f"    {key}: {{")
                for k, v in value.items():
                    if isinstance(v, str):
                        lines.append(f"      {k}: '{v}'")
                    else:
                        lines.append(f"      {k}: {v}")
                lines.append("    }")
            elif isinstance(value, str):
                if value.startswith("@secure()"):
                    lines.append(f"    {key}: {value}")
                else:
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