#!/usr/bin/env python
"""SDK dependency resolution helper script."""
import sys
import argparse
from provisioner.quota.resolver import SDKResolver

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Resolve Azure SDK dependencies for quota checks")
    parser.add_argument("manifest", help="Path to infrastructure YAML manifest")
    parser.add_argument("--output", "-o", default="requirements.txt", help="Output requirements file")
    args = parser.parse_args()
    
    try:
        resolver = SDKResolver(args.manifest)
        resolver.generate_requirements(args.output)
        return 0
    except Exception as e:
        print(f"Error resolving SDKs: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())