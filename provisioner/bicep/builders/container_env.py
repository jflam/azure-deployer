"""Container Apps Environment Bicep builder."""
from typing import Dict, Optional, List
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
        
        # Get properties and find log analytics workspace to use
        props = service.get("properties", {})
        log_analytics_name = None
        
        # Find log analytics workspace in services
        for svc in manifest.get("services", []):
            if svc.get("type") == "Microsoft.OperationalInsights/workspaces":
                log_analytics_name = svc.get("name")
                break
        
        # Determine if we need a dependency on the log analytics workspace
        depends_on = []
        if log_analytics_name:
            depends_on.append(log_analytics_name)
        
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
                        "customerId": f"{log_analytics_name}.properties.customerId",
                        "sharedKey": f"listKeys({log_analytics_name}.id).primarySharedKey"
                    }
                } if log_analytics_name and props.get("enableLogging", True) else None
            },
            tags=tags,
            depends_on=depends_on
        )
        
        # Generate Bicep code
        lines = []
        
        # Resource declaration
        # Use resource name without hyphens for the Bicep identifier
        safe_name = resource.name.replace('-', '_')
        lines.extend([
            f"resource {safe_name} '{resource.type}@{resource.api_version}' = {{",
            f"  name: '{resource.name}'",
            f"  location: location"
        ])
        
        # Add SKU
        lines.extend([
            "  sku: {",
            f"    name: '{resource.sku['name']}'",
            "  }"
        ])
        
        # Add properties
        lines.append("  properties: {")
        
        # Add zoneRedundant
        lines.append(f"    zoneRedundant: {str(resource.properties.get('zoneRedundant', False)).lower()}")
        
        # Add workloadProfiles if present
        workload_profiles = resource.properties.get("workloadProfiles")
        if workload_profiles:
            lines.append("    workloadProfiles: [")
            for profile in workload_profiles:
                lines.append("      {")
                for k, v in profile.items():
                    if isinstance(v, str):
                        lines.append(f"        {k}: '{v}'")
                    else:
                        lines.append(f"        {k}: {v}")
                lines.append("      }")
            lines.append("    ]")
        
        # Add app logs configuration if present
        app_logs = resource.properties.get("appLogsConfiguration")
        if app_logs:
            lines.append("    appLogsConfiguration: {")
            lines.append(f"      destination: '{app_logs['destination']}'")
            if app_logs.get("logAnalyticsConfiguration"):
                # Use safe name for log analytics reference
                log_analytics_safe_name = log_analytics_name.replace('-', '_') if log_analytics_name else 'log_analytics'
                lines.append("      logAnalyticsConfiguration: {")
                lines.append(f"        customerId: {log_analytics_safe_name}.properties.customerId")
                lines.append(f"        sharedKey: listKeys({log_analytics_safe_name}.id, {log_analytics_safe_name}.apiVersion).primarySharedKey")
                lines.append("      }")
            lines.append("    }")
        
        lines.append("  }")
        
        # Add tags
        if tags:
            lines.append("  tags: {")
            for key, value in tags.items():
                lines.append(f"    {key}: '{value}'")
            lines.append("  }")
        
        # Add dependency if needed
        if depends_on:
            lines.append("  dependsOn: [")
            for dep in depends_on:
                # Clean up dependency name by removing hyphens
                safe_dep = dep.replace('-', '_')
                lines.append(f"    {safe_dep}")
            lines.append("  ]")
        
        lines.append("}")
        
        # Add outputs for the environment ID (using safe names)
        safe_name = resource.name.replace('-', '_')
        output_id = f"{safe_name}_id"
        output_domain = f"{safe_name}_default_domain"
        lines.extend([
            "",
            f"output {output_id} string = {safe_name}.id",
            f"output {output_domain} string = {safe_name}.properties.defaultDomain"
        ])
        
        return "\n".join(lines)