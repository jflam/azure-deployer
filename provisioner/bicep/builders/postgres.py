"""PostgreSQL Flexible Server Bicep builder."""
from typing import Dict, Optional
from ..models import BicepResource, BicepParameter

class PostgresBuilder:
    """Builds Bicep code for PostgreSQL Flexible Servers."""
    
    def __init__(self):
        """Initialize the builder."""
        self.api_version = "2024-08-01"  # Latest stable API version
    
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
        
        # Create admin password parameter - using a generic name to simplify
        password_param_name = "postgresAdminPassword"
        
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
        # Use a standardized resource name for the Bicep identifier
        safe_name = "postgres"
        lines = [
            f"resource {safe_name} '{resource.type}@{resource.api_version}' = {{",
            f"  name: '{resource.name}'",
            f"  location: location"
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
            elif isinstance(v, bool):
                # Ensure boolean values are lowercase for Bicep
                lines.append(f"      {k}: {str(v).lower()}")
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
        
        # Add outputs for connection string and server FQDN (using standardized names)
        safe_name = "postgres"
        output_fqdn = "postgres_fqdn"
        output_conn = "postgres_connection_string"
        lines.extend([
            "",
            f"output {output_fqdn} string = {safe_name}.properties.fullyQualifiedDomainName",
            f"@description('Connection string for PostgreSQL - Note: Contains sensitive information')",
            f"@secure()",
            f"output {output_conn} string = 'postgresql://${{{safe_name}.properties.administratorLogin}}:${{{password_param_name}}}@${{{safe_name}.properties.fullyQualifiedDomainName}}:5432/postgres?sslmode=require'"
        ])
        
        return "\n".join(lines)