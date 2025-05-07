"""Test the environment-level quota check for Container Apps."""
import pytest
from unittest.mock import patch, MagicMock
from provisioner.quota.providers import ContainerAppsProviderAdapter
from provisioner.quota.models import QuotaInfo, ResourceQuota

class TestContainerAppsProviderAdapter:
    def test_check_quota_environment_level_cores(self):
        """Test environment-level core quota checks."""
        # Mock the ContainerAppsAPIClient
        with patch('azure.mgmt.appcontainers.ContainerAppsAPIClient') as mock_client_class:
            # Setup mock environment usage object
            mock_usage = MagicMock()
            mock_usage.name.value = "ManagedEnvironmentConsumptionCores"
            mock_usage.limit = 100
            mock_usage.current_value = 20
            
            # Setup mock client
            mock_client = mock_client_class.return_value
            mock_client.managed_environment_usages.list.return_value = [mock_usage]
            
            # Create adapter
            adapter = ContainerAppsProviderAdapter("test-subscription")
            
            # Test capacity with environment_name and resource_group
            capacity = {
                "unit": "Cores",
                "required": 30,
                "environment_name": "test-env",
                "resource_group": "test-rg"
            }
            
            # Call check_quota
            result = adapter.check_quota(
                "Microsoft.App/managedEnvironments",
                "eastus",
                capacity
            )
            
            # Verify client was called with correct parameters
            mock_client.managed_environment_usages.list.assert_called_once_with(
                resource_group_name="test-rg",
                managed_environment_name="test-env"
            )
            
            # Verify result
            assert isinstance(result, ResourceQuota)
            assert result.resource_type == "Microsoft.App/managedEnvironments"
            assert "Cores" in result.quotas
            assert result.quotas["Cores"].limit == 100
            assert result.quotas["Cores"].current_usage == 20
            assert result.quotas["Cores"].required == 30
            assert result.quotas["Cores"].is_sufficient == True

    def test_check_quota_environment_level_missing_params(self):
        """Test environment-level core quota check with missing params."""
        # Mock the ContainerAppsAPIClient
        with patch('azure.mgmt.appcontainers.ContainerAppsAPIClient') as mock_client_class:
            # Setup mock region-level usage (should fall back to this)
            mock_region_usage = MagicMock()
            mock_region_usage.name.value = "ManagedEnvironmentCount"
            mock_region_usage.limit = 15
            mock_region_usage.current_value = 2
            
            # Setup mock client
            mock_client = mock_client_class.return_value
            mock_client.usages.list.return_value = [mock_region_usage]
            
            # Create adapter
            adapter = ContainerAppsProviderAdapter("test-subscription")
            
            # Test capacity without environment_name and resource_group
            capacity = {
                "unit": "Cores",
                "required": 30
                # Missing environment_name and resource_group
            }
            
            # Call check_quota
            result = adapter.check_quota(
                "Microsoft.App/managedEnvironments",
                "eastus",
                capacity
            )
            
            # Should fall back to region-level check and use default 100 cores
            assert isinstance(result, ResourceQuota)
            assert "Cores" in result.quotas
            assert result.quotas["Cores"].limit == 100  # Default value
            assert result.quotas["Cores"].required == 30
            assert result.quotas["Cores"].is_sufficient == True
