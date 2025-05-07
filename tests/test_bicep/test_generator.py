"""Tests for Bicep generator."""
import pytest
from pathlib import Path
from provisioner.bicep.generator import BicepGenerator

def test_generator(tmp_path):
    """Test Bicep file generation."""
    # Create test manifest
    yaml_content = """
    metadata:
      name: test
      version: "1.0"
    resource_group:
      name: test-rg
    region: eastus
    services:
      - name: test-site
        type: Microsoft.Web/staticSites
        sku: Free
    """
    manifest_path = tmp_path / "test_manifest.yaml"
    manifest_path.write_text(yaml_content)
    
    # Generate Bicep files
    generator = BicepGenerator(str(manifest_path), str(tmp_path))
    bicep_path, params_path = generator.generate()
    
    # Verify files were created
    assert Path(bicep_path).exists()
    assert Path(params_path).exists()
    
    # Verify Bicep content
    bicep_content = Path(bicep_path).read_text()
    assert "Microsoft.Web/staticSites" in bicep_content
    assert "test-site" in bicep_content
    
    # Verify parameters content
    params_content = Path(params_path).read_text()
    assert "parameters" in params_content