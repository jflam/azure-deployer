"""Provider-specific quota adapters."""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
import importlib
from azure.identity import DefaultAzureCredential
from .models import QuotaInfo, ResourceQuota

class ProviderAdapter(ABC):
    """Base class for provider-specific quota adapters."""
    
    def __init__(self, subscription_id: str):
        """Initialize the adapter.
        
        Args:
            subscription_id: Azure subscription ID.
        """
        self.subscription_id = subscription_id
        self.credential = DefaultAzureCredential()
    
    @abstractmethod
    def check_quota(self, resource_type: str, region: str, capacity: Dict) -> ResourceQuota:
        """Check quotas for a specific resource type in a region.
        
        Args:
            resource_type: Azure resource type (e.g., "Microsoft.Web/staticSites").
            region: Azure region name.
            capacity: Dictionary containing unit and required capacity.
            
        Returns:
            ResourceQuota: Quota information for the resource.
        """
        pass

class ComputeProviderAdapter(ProviderAdapter):
    """Adapter for Microsoft.Compute quota checks."""
    
    def check_quota(self, resource_type: str, region: str, capacity: Dict) -> ResourceQuota:
        from azure.mgmt.compute import ComputeManagementClient
        
        client = ComputeManagementClient(self.credential, self.subscription_id)
        usages = client.usage.list(region)
        
        result = ResourceQuota(resource_type, region, {})
        
        # Map capacity units to Azure usage names
        unit_mappings = {
            "vCores": "standardDSv3Family",
            # Add other mappings
        }
        
        for usage in usages:
            # Check if this usage matches what we need
            if usage.name.value.lower() == unit_mappings.get(capacity["unit"].lower()):
                quota_info = QuotaInfo(
                    unit=capacity["unit"],
                    current_usage=usage.current_value,
                    limit=usage.limit,
                    required=capacity["required"]
                )
                result.quotas[capacity["unit"]] = quota_info
                break
        
        return result

class WebProviderAdapter(ProviderAdapter):
    """Adapter for Microsoft.Web quota checks."""
    
    def check_quota(self, resource_type: str, region: str, capacity: Dict) -> ResourceQuota:
        from azure.mgmt.web import WebSiteManagementClient
        
        client = WebSiteManagementClient(self.credential, self.subscription_id)
        usages = client.usages.list_by_location(region)
        
        result = ResourceQuota(resource_type, region, {})
        
        for usage in usages:
            if usage.name.value.lower() == capacity["unit"].lower():
                quota_info = QuotaInfo(
                    unit=capacity["unit"],
                    current_usage=usage.current_value,
                    limit=usage.limit,
                    required=capacity["required"]
                )
                result.quotas[capacity["unit"]] = quota_info
                break
        
        return result

class PostgreSQLProviderAdapter(ProviderAdapter):
    """Adapter for Microsoft.DBforPostgreSQL quota checks."""
    
    def check_quota(self, resource_type: str, region: str, capacity: Dict) -> ResourceQuota:
        from azure.mgmt.rdbms import PostgreSQLManagementClient
        
        client = PostgreSQLManagementClient(self.credential, self.subscription_id)
        usages = client.usages.list()
        
        result = ResourceQuota(resource_type, region, {})
        
        for usage in usages:
            if usage.name.value.lower() == capacity["unit"].lower():
                quota_info = QuotaInfo(
                    unit=capacity["unit"],
                    current_usage=usage.current_value,
                    limit=usage.limit,
                    required=capacity["required"]
                )
                result.quotas[capacity["unit"]] = quota_info
                break
        
        return result

class ContainerAppsProviderAdapter(ProviderAdapter):
    """Adapter for Microsoft.App quota checks."""
    
    def check_quota(self, resource_type: str, region: str, capacity: Dict) -> ResourceQuota:
        from azure.mgmt.app import AppManagementClient
        
        client = AppManagementClient(self.credential, self.subscription_id)
        usages = client.usages.list()
        
        result = ResourceQuota(resource_type, region, {})
        
        for usage in usages:
            if usage.name.value.lower() == capacity["unit"].lower():
                quota_info = QuotaInfo(
                    unit=capacity["unit"],
                    current_usage=usage.current_value,
                    limit=usage.limit,
                    required=capacity["required"]
                )
                result.quotas[capacity["unit"]] = quota_info
                break
        
        return result

class QuotaClientAdapter(ProviderAdapter):
    """Fallback adapter using Microsoft.Quota."""
    
    def check_quota(self, resource_type: str, region: str, capacity: Dict) -> ResourceQuota:
        from azure.mgmt.quota import QuotaManagementClient
        
        client = QuotaManagementClient(self.credential, self.subscription_id)
        quotas = client.quotas.list(resource_type, region)
        
        result = ResourceQuota(resource_type, region, {})
        
        for quota in quotas:
            if quota.properties.limit_name.lower() == capacity["unit"].lower():
                quota_info = QuotaInfo(
                    unit=capacity["unit"],
                    current_usage=quota.properties.current_value,
                    limit=quota.properties.limit_value,
                    required=capacity["required"]
                )
                result.quotas[capacity["unit"]] = quota_info
                break
        
        return result

class ProviderAdapterRegistry:
    """Registry of provider adapters with fallback logic."""
    
    def __init__(self, subscription_id: str):
        """Initialize the registry.
        
        Args:
            subscription_id: Azure subscription ID.
        """
        self.subscription_id = subscription_id
        self.adapters = {
            "Microsoft.Compute": ComputeProviderAdapter(subscription_id),
            "Microsoft.Web": WebProviderAdapter(subscription_id),
            "Microsoft.DBforPostgreSQL": PostgreSQLProviderAdapter(subscription_id),
            "Microsoft.App": ContainerAppsProviderAdapter(subscription_id),
            # Register other provider adapters
        }
        self.fallback = QuotaClientAdapter(subscription_id)
    
    def get_adapter(self, resource_type: str) -> ProviderAdapter:
        """Get the appropriate adapter for a resource type, with fallback.
        
        Args:
            resource_type: Azure resource type (e.g., "Microsoft.Web/staticSites").
            
        Returns:
            ProviderAdapter: The appropriate adapter for the resource type.
        """
        provider = resource_type.split('/')[0]
        return self.adapters.get(provider, self.fallback)