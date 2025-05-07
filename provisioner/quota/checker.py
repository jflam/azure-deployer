"""Quota checking implementation."""
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Set, Tuple
from azure.identity import DefaultAzureCredential
from .models import RegionAnalysis, ResourceQuota
from .providers import ProviderAdapterRegistry
from ..manifest.parser import ManifestParser
from ..manifest.updater import ManifestUpdater

class QuotaChecker:
    """Implements the quota checking algorithm."""
    
    def __init__(self, manifest_path: str, dry_run: bool = False, debug: bool = False):
        """Initialize the checker.
        
        Args:
            manifest_path: Path to the YAML manifest file.
            dry_run: If True, don't update the manifest with selected region.
            debug: If True, print verbose debug information.
        """
        self.manifest_path = manifest_path
        self.manifest = ManifestParser.load(manifest_path)
        self.dry_run = dry_run
        self.debug = debug
        self.subscription_id = self.manifest.subscription or self._get_default_subscription()
        self.adapter_registry = ProviderAdapterRegistry(self.subscription_id)
    
    def _get_default_subscription(self) -> str:
        """Get the default subscription ID from Azure CLI.
        
        Returns:
            str: Azure subscription ID.
            
        Raises:
            subprocess.CalledProcessError: If Azure CLI command fails.
        """
        cmd = ["az", "account", "show", "--query", "id", "-o", "tsv"]
        
        # In debug mode, print the command
        if self.debug:
            print(f"Debug: Running command: {' '.join(cmd)}")
            
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        subscription_id = result.stdout.strip()
        
        if self.debug:
            print(f"Debug: Using subscription ID: {subscription_id}")
            
        return subscription_id
    
    def check_quotas(self) -> RegionAnalysis:
        """Check quotas for all services in the manifest.
        
        Returns:
            RegionAnalysis: Analysis of quota availability across regions.
        """
        # Get all Azure regions if needed
        all_regions = self._get_all_regions() if not self.manifest.region else [self.manifest.region]
        
        # Filter regions if allowedRegions is specified
        if self.manifest.allowed_regions:
            all_regions = [r for r in all_regions if r in self.manifest.allowed_regions]
        
        # Initialize region analysis
        region_quotas = {region: [] for region in all_regions}
        
        # Check each service
        for service in self.manifest.services:
            # Skip services with no capacity requirements
            if not service.capacity or service.skip_quota_check:
                continue
            
            # Determine which regions to check for this service
            service_regions = [service.region] if service.region else all_regions
            
            for region in service_regions:
                try:
                    adapter = self.adapter_registry.get_adapter(service.type)
                    quota_result = adapter.check_quota(
                        service.type,
                        region,
                        service.capacity.model_dump()
                    )
                    region_quotas[region].append(quota_result)
                except Exception as e:
                    if self.debug:
                        print(f"Debug: Error checking quota for {service.type} in {region}: {e}")
                    # Keep track of the error but continue
        
        # Determine viable regions (where all services have sufficient quota)
        viable_regions = []
        for region, quotas in region_quotas.items():
            if all(q.is_sufficient() for q in quotas):
                viable_regions.append(region)
        
        return RegionAnalysis(region_quotas, viable_regions)
    
    def _get_all_regions(self) -> List[str]:
        """Get all available Azure regions.
        
        Returns:
            List[str]: List of Azure region names.
            
        Raises:
            subprocess.CalledProcessError: If Azure CLI command fails.
        """
        cmd = ["az", "account", "list-locations", "--query", "[].name", "-o", "json"]
        
        # In debug mode, print the command
        if self.debug:
            print(f"Debug: Running command: {' '.join(cmd)}")
            
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        regions = json.loads(result.stdout)
        
        if self.debug:
            print(f"Debug: Found {len(regions)} available regions")
            
        return regions
    
    def select_region(self, analysis: RegionAnalysis) -> str:
        """Select a region from viable regions.
        
        Args:
            analysis: Region analysis containing viable regions.
            
        Returns:
            str: Selected region name.
            
        Raises:
            ValueError: If no viable regions are found.
        """
        if not analysis.viable_regions:
            raise ValueError("No viable regions found that satisfy quota requirements")
        
        # For now, just select the first viable region
        # Future: implement more sophisticated region selection
        return analysis.viable_regions[0]
    
    def update_manifest_region(self, region: str) -> None:
        """Update the manifest with the selected region.
        
        Args:
            region: Azure region name to set.
        """
        if not self.dry_run:
            ManifestUpdater.update_region(self.manifest_path, region)
        print(f"Selected region: {region}")