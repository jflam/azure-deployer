"""YAML manifest parser."""
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Union

from .schema import Manifest

class ManifestParser:
    """Parser for YAML infrastructure manifests."""
    
    @staticmethod
    def load(file_path: str) -> Manifest:
        """Load and validate a YAML manifest file.
        
        Args:
            file_path: Path to the YAML manifest file.
            
        Returns:
            Manifest: Validated manifest object.
            
        Raises:
            FileNotFoundError: If the manifest file doesn't exist.
            ValidationError: If the manifest is invalid.
            yaml.YAMLError: If the YAML is malformed.
        """
        with open(file_path, 'r') as f:
            data = yaml.safe_load(f)
        return Manifest.model_validate(data)