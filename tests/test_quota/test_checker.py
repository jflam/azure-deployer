"""Tests for quota checker."""
import pytest
from unittest.mock import patch, MagicMock
from provisioner.quota.checker import QuotaChecker
from provisioner.quota.models import QuotaInfo, ResourceQuota, RegionAnalysis

@pytest.fixture
def mock_quotas():
    """Create mock quota results."""
    return {
        "eastus": [
            ResourceQuota(
                resource_type="Microsoft.Web/staticSites",
                region="eastus",
                quotas={
                    "instances": QuotaInfo(
                        unit="instances",
                        current_usage=1,
                        limit=10,
                        required=1
                    )
                }
            )
        ],
        "westus2": [
            ResourceQuota(
                resource_type="Microsoft.Web/staticSites",
                region="westus2",
                quotas={
                    "instances": QuotaInfo(
                        unit="instances",
                        current_usage=9,
                        limit=10,
                        required=2
                    )
                }
            )
        ]
    }

@patch("provisioner.quota.checker.ProviderAdapterRegistry")
def test_quota_checker(mock_registry, mock_quotas, tmp_path):
    """Test quota checking with mock data."""
    # Create test manifest
    yaml_content = """
    metadata:
      name: test
      version: "1.0"
    resource_group:
      name: test-rg
    region: ""
    services:
      - name: test-site
        type: Microsoft.Web/staticSites
        sku: Free
        capacity:
          unit: instances
          required: 1
    """
    manifest_path = tmp_path / "test_manifest.yaml"
    manifest_path.write_text(yaml_content)
    
    # Setup mock adapter to return predefined quotas
    mock_adapter = MagicMock()
    mock_adapter.check_quota.side_effect = lambda resource_type, region, capacity: mock_quotas[region][0]
    
    mock_registry_instance = MagicMock()
    mock_registry_instance.get_adapter.return_value = mock_adapter
    mock_registry.return_value = mock_registry_instance
    
    # Create the checker
    checker = QuotaChecker(str(manifest_path), dry_run=True)
    
    # Run the check
    analysis = checker.check_quotas()
    
    # Verify results
    assert "eastus" in analysis.viable_regions
    assert "westus2" not in analysis.viable_regions