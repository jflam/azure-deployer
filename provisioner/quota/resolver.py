"""SDK dependency resolution for quota checks."""
import importlib
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Provider to SDK package mapping
SDK_MAPPING = {
    "Microsoft.Web": "azure-mgmt-web",
    "Microsoft.DBforPostgreSQL": "azure-mgmt-rdbms",
    "Microsoft.App": "azure-mgmt-app",
    "Microsoft.OperationalInsights": "azure-mgmt-loganalytics",
    "Microsoft.Compute": "azure-mgmt-compute",
    "Microsoft.Network": "azure-mgmt-network",
    "Microsoft.Storage": "azure-mgmt-storage",
    "Microsoft.ContainerInstance": "azure-mgmt-containerinstance",
    "Microsoft.ContainerService": "azure-mgmt-containerservice",
    "Microsoft.Batch": "azure-mgmt-batch",
    "Microsoft.MachineLearningServices": "azure-mgmt-machinelearningservices",
    "Microsoft.Sql": "azure-mgmt-sql",
    "Microsoft.DBforMySQL": "azure-mgmt-rdbms",
}

class SDKResolver:
    """Resolves and installs required Azure SDK packages."""
    
    def __init__(self, manifest_path: str):
        """Initialize the resolver.
        
        Args:
            manifest_path: Path to the YAML manifest file.
        """
        self.manifest_path = manifest_path
        self.required_sdks = set()
    
    def analyze_manifest(self) -> Set[str]:
        """Parse the manifest and identify required SDK packages.
        
        Returns:
            Set[str]: Set of required SDK package names.
        """
        import yaml
        with open(self.manifest_path, 'r') as f:
            data = yaml.safe_load(f)
        
        for service in data.get('services', []):
            provider = service.get('type').split('/')[0]
            if provider in SDK_MAPPING:
                self.required_sdks.add(SDK_MAPPING[provider])
        
        # Always include quota client for fallback
        self.required_sdks.add("azure-mgmt-quota")
        self.required_sdks.add("azure-identity")
        
        return self.required_sdks
    
    def generate_requirements(self, output_path: str = "requirements.txt") -> None:
        """Generate a requirements.txt file with the required SDKs.
        
        Args:
            output_path: Path to write the requirements file.
        """
        sdks = self.analyze_manifest()
        
        with open(output_path, 'w') as f:
            for sdk in sorted(sdks):
                f.write(f"{sdk}\n")
        
        print(f"Generated requirements file at {output_path}")
    
    def install_required_sdks(self) -> None:
        """Install required SDKs using UV.
        
        Raises:
            subprocess.CalledProcessError: If installation fails.
        """
        self.analyze_manifest()
        cmd = ["uv", "pip", "install"] + list(self.required_sdks)
        subprocess.run(cmd, check=True)
        print(f"Installed required SDKs: {', '.join(self.required_sdks)}")
    
    @staticmethod
    def generate_quota_matrix(output_path: str = "build/quota_matrix.json") -> None:
        """Generate a comprehensive quota matrix JSON file.
        
        Args:
            output_path: Path to write the quota matrix file.
        """
        matrix = {
            "providers": {
                "Microsoft.Compute": {
                    "sdk": "azure-mgmt-compute",
                    "client_class": "ComputeManagementClient",
                    "quota_method": "usage.list",
                    "quota_units": ["vCPUs", "StandardDSv5Family"]
                },
                "Microsoft.Web": {
                    "sdk": "azure-mgmt-web",
                    "client_class": "WebSiteManagementClient",
                    "quota_method": "usages.list_by_location",
                    "quota_units": ["Cores", "AppServicePlans"]
                },
                "Microsoft.DBforPostgreSQL": {
                    "sdk": "azure-mgmt-rdbms",
                    "client_class": "PostgreSQLManagementClient",
                    "quota_method": "usages.list",
                    "quota_units": ["vCores", "Servers"]
                },
                "Microsoft.App": {
                    "sdk": "azure-mgmt-app",
                    "client_class": "AppManagementClient",
                    "quota_method": "usages.list",
                    "quota_units": ["Cores", "MemoryGB"]
                },
                "Microsoft.OperationalInsights": {
                    "sdk": "azure-mgmt-loganalytics",
                    "client_class": "LogAnalyticsManagementClient",
                    "quota_method": "usages.list",
                    "quota_units": ["DataIngestionGB"]
                },
                # Add other providers as needed
            }
        }
        
        # Ensure directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(matrix, f, indent=2)
        
        print(f"Generated quota matrix at {output_path}")