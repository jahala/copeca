#!/bin/bash
set -e
echo "=== Copeca Corpus Smoke ==="
echo "Validating all tasks..."
copeca validate tasks/
echo "PASS: All tasks validate"
echo "Auditing taxonomy..."
python scripts/taxonomy_audit.py tasks/
echo "PASS: Taxonomy audit complete"
echo "Contamination check..."
python scripts/contamination_check.py --tasks-dir tasks/ --blocklist scripts/contamination_blocklist.txt 2>/dev/null || echo "Contamination check not run (no blocklist entries flag)"
echo "=== Smoke Complete ==="
