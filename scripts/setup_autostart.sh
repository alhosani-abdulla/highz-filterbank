#!/bin/bash
#
# Setup script to enable automatic startup of synchronized sweep on boot
#
# This script adds a crontab entry to run the synchronized sweep script on boot
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SWEEP_SCRIPT="$SCRIPT_DIR/run_synchronized_sweep.sh"
LOG_DIR="/media/peterson/INDURANCE/Logs"

echo "========================================="
echo "High-Z Filterbank Autostart Setup"
echo "========================================="
echo ""

# Check if sweep script exists
if [ ! -f "$SWEEP_SCRIPT" ]; then
    echo "ERROR: Sweep script not found at: $SWEEP_SCRIPT"
    exit 1
fi

# Make sweep script executable
chmod +x "$SWEEP_SCRIPT"
echo "✓ Made sweep script executable"

# Create log directory
mkdir -p "$LOG_DIR"
chmod 755 "$LOG_DIR"
echo "✓ Created log directory: $LOG_DIR"

# Check if root crontab entry already exists
if sudo crontab -l 2>/dev/null | grep -q "run_synchronized_sweep.sh"; then
    echo ""
    echo "WARNING: Root crontab entry already exists!"
    echo ""
    echo "Current root crontab entries for this script:"
    sudo crontab -l | grep "run_synchronized_sweep.sh"
    echo ""
    read -p "Do you want to replace it? (y/n): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
    # Remove existing entry from root crontab
    sudo crontab -l | grep -v "run_synchronized_sweep.sh" | sudo crontab -
    echo "✓ Removed old root crontab entry"
fi

# Add new crontab entry to root crontab
(sudo crontab -l 2>/dev/null; echo "@reboot $SWEEP_SCRIPT >> $LOG_DIR/synchronized_sweep.log 2>&1") | sudo crontab -
echo "✓ Added root crontab entry"

echo ""
echo "========================================="
echo "Setup Complete!"
echo "========================================="
echo ""
echo "The synchronized sweep will now start automatically on boot (as root)."
echo ""
echo "To view the root crontab:"
echo "  sudo crontab -l"
echo ""
echo "To monitor the log file:"
echo "  tail -f $LOG_DIR/synchronized_sweep.log"
echo ""
echo "To stop the sweep:"
echo "  sudo pkill -f run_synchronized_sweep.sh"
echo ""
echo "To disable autostart:"
echo "  sudo crontab -l | grep -v run_synchronized_sweep.sh | sudo crontab -"
echo ""
echo "Reboot to test the autostart, or run manually:"
echo "  sudo $SWEEP_SCRIPT"
echo ""
