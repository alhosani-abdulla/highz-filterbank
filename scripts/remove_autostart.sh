#!/bin/bash
#
# Remove autostart for synchronized sweep
#

echo "========================================="
echo "Remove High-Z Filterbank Autostart"
echo "========================================="
echo ""

# Check if root crontab entry exists
if ! sudo crontab -l 2>/dev/null | grep -q "run_synchronized_sweep.sh"; then
    echo "No root crontab entry found for run_synchronized_sweep.sh"
    exit 0
fi

echo "Current root crontab entry:"
sudo crontab -l | grep "run_synchronized_sweep.sh"
echo ""

read -p "Are you sure you want to remove this entry? (y/n): " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

# Remove crontab entry from root crontab
sudo crontab -l | grep -v "run_synchronized_sweep.sh" | sudo crontab -
echo "✓ Removed root crontab entry"

echo ""
echo "Autostart disabled. The script will no longer run on boot."
echo ""
echo "To re-enable, run: ./setup_autostart.sh"
echo ""
