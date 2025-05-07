"""YAML manifest updater."""
import yaml
from pathlib import Path
from typing import Any, Dict

class ManifestUpdater:
    """Updates YAML manifest files in-place."""
    
    @staticmethod
    def update_region(file_path: str, region: str) -> None:
        """Update the region field in the YAML manifest.
        
        Args:
            file_path: Path to the YAML manifest file.
            region: Azure region name to set.
            
        Raises:
            FileNotFoundError: If the manifest file doesn't exist.
            yaml.YAMLError: If the YAML is malformed.
        """
        with open(file_path, 'r') as f:
            data = yaml.safe_load(f)
        
        # Update region
        data['region'] = region
        
        # Write back to file, preserving format
        with open(file_path, 'w') as f:
            yaml.dump(data, f, sort_keys=False)
    
    @staticmethod
    def update_field(file_path: str, field_path: str, value: Any) -> None:
        """Update any field in the YAML manifest using dot notation.
        
        Args:
            file_path: Path to the YAML manifest file.
            field_path: Dot-separated path to the field (e.g., "metadata.version").
            value: New value to set.
            
        Raises:
            FileNotFoundError: If the manifest file doesn't exist.
            KeyError: If the field path is invalid.
            yaml.YAMLError: If the YAML is malformed.
        """
        with open(file_path, 'r') as f:
            data = yaml.safe_load(f)
        
        # Navigate to the field
        parts = field_path.split('.')
        current = data
        for part in parts[:-1]:
            if part not in current:
                raise KeyError(f"Field path '{field_path}' is invalid at '{part}'")
            current = current[part]
        
        # Update the field
        if parts[-1] not in current:
            raise KeyError(f"Field path '{field_path}' is invalid at '{parts[-1]}'")
        current[parts[-1]] = value
        
        # Write back to file, preserving format
        with open(file_path, 'w') as f:
            yaml.dump(data, f, sort_keys=False)