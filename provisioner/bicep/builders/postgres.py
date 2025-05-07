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
        
        # Get properties and secrets
        props = service.get("properties", {})
        secrets = service.get("secrets", {})
        
        # Create admin password parameter
        password_param_name = f"{service['name']}AdminPassword"
        
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
                "administratorLoginPassword": f"{password_param_name}"
            },
            tags=tags
        )
        
        # Generate Bicep code
        lines = [
            # Removed secure param declaration since it's declared at the top level
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
        
        # Add version
        lines.append(f"    version: '{resource.properties['version']}'")
        
        # Add storage
        storage = resource.properties.get("storage", {})
        lines.append("    storage: {")
        for k, v in storage.items():
            if isinstance(v, str):
                lines.append(f"      {k}: '{v}'")
            else:
                lines.append(f"      {k}: {v}")
        lines.append("    }")
        
        # Add backup
        backup = resource.properties.get("backup", {})
        lines.append("    backup: {")
        for k, v in backup.items():
            if isinstance(v, str):
                lines.append(f"      {k}: '{v}'")
            else:
                lines.append(f"      {k}: {v}")
        lines.append("    }")
        
        # Add network if delegatedSubnetResourceId is not empty
        network = resource.properties.get("network", {})
        if network.get("delegatedSubnetResourceId"):
            lines.append("    network: {")
            for k, v in network.items():
                if v:  # Only add non-empty values
                    if isinstance(v, str):
                        lines.append(f"      {k}: '{v}'")
                    else:
                        lines.append(f"      {k}: {v}")
            lines.append("    }")
        
        # Add admin login
        lines.append(f"    administratorLogin: '{resource.properties['administratorLogin']}'")
        
        # Add admin password
        lines.append(f"    administratorLoginPassword: {password_param_name}")
        
        lines.append("  }")
        
        # Add tags
        if tags:
            lines.append("  tags: {")
            for key, value in tags.items():
                lines.append(f"    {key}: '{value}'")
            lines.append("  }")
        
        lines.append("}")
        
        # Add outputs for connection string and server FQDN
        lines.extend([
            "",
            f"output {resource.name}Fqdn string = {resource.name}.properties.fullyQualifiedDomainName",
            f"output {resource.name}ConnectionString string = 'postgresql://${{{resource.name}.properties.administratorLogin}}:${{passwordToEscape}}@${{{resource.name}.properties.fullyQualifiedDomainName}}:5432/postgres?sslmode=require'"
        ])
        
        return "\n".join(lines)