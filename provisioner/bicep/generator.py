"""Bicep template generator."""
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
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
            
        bicep_content = self._generate_bicep_file()
        params_content = self._generate_parameters_file()
        
        # Write files
        bicep_path = Path(self.output_dir) / "main.bicep"
        params_path = Path(self.output_dir) / "main.parameters.json"
        
        bicep_path.write_text(bicep_content)
        params_path.write_text(params_content)
        
        if self.debug:
            print(f"Debug: Bicep file written to {bicep_path}")
            print(f"Debug: Parameters file written to {params_path}")
            
        return str(bicep_path), str(params_path)
    
    def _generate_bicep_file(self) -> str:
        """Generate the main Bicep file content.
        
        Returns:
            str: Bicep template content.
        """
        # Collect secure parameters needed
        used_secrets = self._collect_used_secrets()
        
        # Generate resource snippets and track dependencies
        resources = self._generate_resources()
        
        # Render the full template
        template = self.jinja_env.get_template("base.bicep")
        return template.render(
            manifest=self.manifest,
            resources=resources,
            secrets=used_secrets
        )
    
    def _generate_parameters_file(self) -> str:
        """Generate the parameters JSON file with Key Vault references.
        
        Returns:
            str: Parameters file content.
        """
        template = self.jinja_env.get_template("parameters.json")
        
        # Collect secrets used in the template
        used_secrets = self._collect_used_secrets()
        
        # Build parameters object
        parameters = {}
        
        # Add secrets as Key Vault references
        for secret_param in used_secrets:
            secret_name = self.manifest.secrets.get(secret_param)
            if secret_name:
                parameters[secret_param] = {
                    "reference": {
                        "keyVault": {
                            "id": self.manifest.key_vault
                        },
                        "secretName": secret_name
                    }
                }
        
        return template.render(parameters=parameters)
    
    def _collect_used_secrets(self) -> List[str]:
        """Collect all secret names that are used in the manifest.
        
        Returns:
            List[str]: List of secret names.
        """
        used_secrets = []
        
        for service in self.manifest.services:
            if service.secrets:
                for secret_name in service.secrets.values():
                    used_secrets.append(secret_name)
        
        return used_secrets
    
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
            builder = self.builders.get(service.type)
            if not builder:
                raise ValueError(f"Unsupported resource type: {service.type}")
            
            # Generate resource snippet
            snippet = builder.build(service.model_dump(), self.manifest.model_dump())
            resources.append(snippet)
        
        return resources
    
    def _order_services_by_dependencies(self) -> List:
        """Order services to ensure dependencies are deployed first.
        
        Returns:
            List: Ordered list of services.
        """
        # Simple implementation - this would need enhancement for complex dependencies
        # Put Log Analytics workspaces first since Container Environments may depend on them
        
        ordered = []
        log_analytics = []
        container_envs = []
        others = []
        
        for service in self.manifest.services:
            if service.type == "Microsoft.OperationalInsights/workspaces":
                log_analytics.append(service)
            elif service.type == "Microsoft.App/managedEnvironments":
                container_envs.append(service)
            else:
                others.append(service)
        
        return log_analytics + container_envs + others