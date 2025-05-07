"""Tests for manifest parser."""
import pytest
from provisioner.manifest.parser import ManifestParser
from provisioner.manifest.schema import Manifest

def test_valid_manifest(tmp_path):
    """Test parsing a valid manifest."""
    # Test with a minimal valid manifest
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
    
    manifest = ManifestParser.load(str(manifest_path))
    assert isinstance(manifest, Manifest)
    assert manifest.metadata.name == "test"
    assert manifest.resource_group.name == "test-rg"
    assert manifest.region == "eastus"
    assert len(manifest.services) == 1
    assert manifest.services[0].name == "test-site"

def test_invalid_manifest(tmp_path):
    """Test parsing an invalid manifest."""
    # Test with an invalid manifest (missing required fields)
    yaml_content = """
    metadata:
      name: test
    """
    manifest_path = tmp_path / "test_manifest.yaml"
    manifest_path.write_text(yaml_content)
    
    with pytest.raises(Exception):
        ManifestParser.load(str(manifest_path))

def test_nonexistent_file():
    """Test loading a nonexistent file."""
    with pytest.raises(FileNotFoundError):
        ManifestParser.load("nonexistent.yaml")