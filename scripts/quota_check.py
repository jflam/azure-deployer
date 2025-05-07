#!/usr/bin/env python
"""Standalone quota checker script."""
import sys
import argparse
from provisioner.quota.checker import QuotaChecker

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Check Azure quota availability for infrastructure manifest")
    parser.add_argument("--config", "-c", default="infra.yaml", help="Path to infrastructure YAML manifest")
    parser.add_argument("--output", "-o", default="region-analysis.json", help="Output analysis file")
    parser.add_argument("--dry-run", action="store_true", help="Don't update the manifest with selected region")
    parser.add_argument("--auto-select", action="store_true", help="Automatically select a viable region")
    args = parser.parse_args()
    
    try:
        checker = QuotaChecker(args.config, dry_run=args.dry_run)
        analysis = checker.check_quotas()
        analysis.save(args.output)
        
        if not analysis.viable_regions:
            print("No viable regions found that satisfy quota requirements", file=sys.stderr)
            return 2
        
        if args.auto_select:
            selected_region = checker.select_region(analysis)
            checker.update_manifest_region(selected_region)
            print(f"Selected region: {selected_region}")
        
        return 0
    except Exception as e:
        print(f"Error checking quotas: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())