"""Bicep template generator."""
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from jinja2 import Environment, FileSystemLoader

from .models import BicepModule, BicepParameter, BicepResource
from .builders.static_site import StaticSiteBuilder
from .builders.postgres import PostgresBuilder
from .builders.container_env import ContainerEnvBuilder
from .builders.log_analytics import LogAnalyticsBuilder
from ..manifest.parser import ManifestParser

class BicepGenerator:
    """Generates Bicep templates from YAML manifests."""
    
    def __init__(self, manifest_path: str, output_dir: str = None, debug: bool = False):
        """Initialize the generator.
        
        Args:
            manifest_path: Path to the YAML manifest file.
            output_dir: Directory for generated Bicep files.
            debug: If True, print verbose debug information.
        """
        self.manifest_path = manifest_path
        self.manifest = ManifestParser.load(manifest_path)
        self.output_dir = output_dir or Path(manifest_path).parent
        self.debug = debug
        
        # Ensure output directory exists
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        
        # Set up Jinja2 environment
        template_dir = Path(__file__).parent / "templates"
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            trim_blocks=True,
            lstrip_blocks=True
        )
        
        # Resource builder mapping
        self.builders = {
            "Microsoft.Web/staticSites": StaticSiteBuilder(),
            "Microsoft.DBforPostgreSQL/flexibleServers": PostgresBuilder(),
            "Microsoft.App/managedEnvironments": ContainerEnvBuilder(),
            "Microsoft.OperationalInsights/workspaces": LogAnalyticsBuilder()
        }
    
    def generate(self) -> Tuple[str, str]:
        """Generate Bicep template and parameters file.
        
        Returns:
            Tuple[str, str]: Paths to the generated Bicep and parameters files.
        """
        if self.debug:
            print(f"Debug: Generating Bicep files from {self.manifest_path}")
            print(f"Debug: Output directory: {self.output_dir}")
            
        main_bicep_content = self._generate_main_bicep_file()
        resources_bicep_content = self._generate_resources_bicep_file()
        params_content = self._generate_parameters_file()
        
        # Write files
        main_bicep_path = Path(self.output_dir) / "main.bicep"
        resources_bicep_path = Path(self.output_dir) / "resources.bicep"
        params_path = Path(self.output_dir) / "main.parameters.json"
        
        main_bicep_path.write_text(main_bicep_content)
        resources_bicep_path.write_text(resources_bicep_content)
        params_path.write_text(params_content)
        
        if self.debug:
            print(f"Debug: Main Bicep file written to {main_bicep_path}")
            print(f"Debug: Resources Bicep file written to {resources_bicep_path}")
            print(f"Debug: Parameters file written to {params_path}")
            
        return str(main_bicep_path), str(params_path)
    
    def _generate_main_bicep_file(self) -> str:
        """Generate the main Bicep file content (subscription scope).
        
        Returns:
            str: Main Bicep template content.
        """
        # Collect all secure parameters needed
        secure_params = self._collect_secure_parameters()
        
        # Build template context
        # Check if manifest is a pydantic model or a dict
        if hasattr(self.manifest, "model_dump"):
            # It's a pydantic model
            manifest_dict = self.manifest.model_dump()
            context = {
                "resourceGroupName": manifest_dict.get("resource_group", {}).get("name", "default-rg"),
                "location": manifest_dict.get("region") or "[deployment().location]",  # Fall back to deployment location if not set
                "tags": manifest_dict.get("tags", {}),
                "secrets": secure_params
            }
        else:
            # It's a dict
            context = {
                "resourceGroupName": self.manifest.get("resourceGroup", {}).get("name", "default-rg"),
                "location": self.manifest.get("region") or "[deployment().location]",  # Fall back to deployment location if not set
                "tags": self.manifest.get("tags", {}),
                "secrets": secure_params
            }
        
        # Render the main template
        template = self.jinja_env.get_template("base.bicep")
        return template.render(**context)
    
    def _generate_resources_bicep_file(self) -> str:
        """Generate the resources Bicep file content (resource group scope).
        
        Returns:
            str: Resources Bicep template content.
        """
        # Generate resource snippets and track dependencies
        resources = self._generate_resources()
        
        # Build template content
        template_content = """// Resources Bicep template - ResourceGroup scope
targetScope = 'resourceGroup'

// Parameters
param location string
param tags object = {}

// Secure parameters
@secure()
param postgresAdminPassword string = ''

// Resource definitions
"""
        # Add all resources
        for resource in resources:
            template_content += resource + "\n\n"
            
        # Add outputs from the resources for reference in the main template
        template_content += """// Output resource properties for reference
"""
        
        return template_content
    
    def _generate_parameters_file(self) -> str:
        """Generate the parameters JSON file with Key Vault references.
        
        Returns:
            str: Parameters file content.
        """
        # Get parameters from manifest
        if hasattr(self.manifest, "model_dump"):
            manifest_dict = self.manifest.model_dump()
            location = manifest_dict.get("region", "")
            resource_group_name = manifest_dict.get("resource_group", {}).get("name", "default-rg")
            tags = manifest_dict.get("tags", {})
        else:
            location = self.manifest.get("region", "")
            resource_group_name = self.manifest.get("resourceGroup", {}).get("name", "default-rg")
            tags = self.manifest.get("tags", {})
        
        # Process the template
        template = self.jinja_env.get_template("parameters.json")
        return template.render(
            location=location,
            resourceGroupName=resource_group_name,
            tags=tags
        )
    
    def _collect_secure_parameters(self) -> Set[str]:
        """Collect all secure parameters that need to be declared in the Bicep file.
        
        Returns:
            Set[str]: Set of parameter names.
        """
        secure_params = set()
        
        # Get services list
        if hasattr(self.manifest, "model_dump"):
            manifest_dict = self.manifest.model_dump()
            services = manifest_dict.get("services", [])
        else:
            services = self.manifest.get("services", [])
        
        # Process each service's secrets
        for service in services:
            service_dict = service if isinstance(service, dict) else service.model_dump() if hasattr(service, "model_dump") else {}
            
            # For Postgres admin password
            if service_dict.get("type") == "Microsoft.DBforPostgreSQL/flexibleServers":
                if service_dict.get("secrets", {}).get("adminPassword"):
                    secure_params.add(f"{service_dict.get('name')}AdminPassword")
        
        return secure_params
    
    def _generate_resources(self) -> List[str]:
        """Generate Bicep code for all resources.
        
        Returns:
            List[str]: List of Bicep resource definitions.
        """
        # Determine resource ordering for dependencies
        ordered_services = self._order_services_by_dependencies()
        
        # Generate code for each resource
        resources = []
        for service in ordered_services:
            service_dict = service if isinstance(service, dict) else service.model_dump() if hasattr(service, "model_dump") else {}
            service_type = service_dict.get("type")
            
            if not service_type:
                if self.debug:
                    print(f"Debug: Skipping service without type: {service_dict.get('name', 'unknown')}")
                continue
                
            builder = self.builders.get(service_type)
            if not builder:
                if self.debug:
                    print(f"Debug: Skipping unsupported resource type: {service_type}")
                continue
            
            try:
                # Generate resource snippet
                if hasattr(self.manifest, "model_dump"):
                    manifest_dict = self.manifest.model_dump()
                else:
                    manifest_dict = self.manifest
                    
                snippet = builder.build(service_dict, manifest_dict)
                resources.append(snippet)
                
                if self.debug:
                    print(f"Debug: Generated resource for {service_dict.get('name')} ({service_type})")
            except Exception as e:
                if self.debug:
                    print(f"Debug: Error generating resource for {service_dict.get('name')}: {e}")
        
        return resources
    
    def _order_services_by_dependencies(self) -> List:
        """Order services to ensure dependencies are deployed first.
        
        Returns:
            List: Ordered list of services.
        """
        # Enhanced implementation for dependencies between resources
        # Resource types are grouped by their natural dependency order
        service_groups = {
            # Core infrastructure (lowest level)
            1: ["Microsoft.OperationalInsights/workspaces"],
            # Networking and storage
            2: ["Microsoft.Network/virtualNetworks"],
            # Database and middleware
            3: ["Microsoft.DBforPostgreSQL/flexibleServers"],
            # App hosting environments
            4: ["Microsoft.App/managedEnvironments"],
            # Applications (highest level)
            5: ["Microsoft.Web/staticSites", "Microsoft.App/containerApps"]
        }
        
        # Map for quick lookup of priority by resource type
        type_priority_map = {}
        for priority, resource_types in service_groups.items():
            for res_type in resource_types:
                type_priority_map[res_type] = priority
        
        # Get services list
        if hasattr(self.manifest, "model_dump"):
            manifest_dict = self.manifest.model_dump()
            services = manifest_dict.get("services", [])
        else:
            services = self.manifest.get("services", [])
            
        # Bucket services by priority
        prioritized_services = {}
        for service in services:
            service_dict = service if isinstance(service, dict) else service.model_dump() if hasattr(service, "model_dump") else {}
            service_type = service_dict.get("type")
            
            if not service_type:
                continue
                
            priority = type_priority_map.get(service_type, 99)  # Unknown types get lowest priority
            
            if priority not in prioritized_services:
                prioritized_services[priority] = []
            
            prioritized_services[priority].append(service_dict)
        
        # Flatten the prioritized services into a single ordered list
        ordered_services = []
        for priority in sorted(prioritized_services.keys()):
            ordered_services.extend(prioritized_services[priority])
            
        if self.debug:
            print(f"Debug: Ordered {len(ordered_services)} services for deployment")
        
        return ordered_services