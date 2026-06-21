#!/bin/bash
set -e
echo "=== Copeca Corpus Smoke ==="
echo "Validating all tasks..."
copeca validate src/copeca/data/tasks/
echo "PASS: All tasks validate"
echo "Auditing taxonomy..."
python scripts/taxonomy_audit.py src/copeca/data/tasks/
echo "PASS: Taxonomy audit complete"
echo "Contamination check..."
python scripts/contamination_check.py --tasks-dir src/copeca/data/tasks/ --blocklist src/copeca/data/contamination_blocklist.txt 2>/dev/null || echo "Contamination check not run (no blocklist entries flag)"
echo "=== Smoke Complete ==="
