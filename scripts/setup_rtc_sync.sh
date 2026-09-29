#!/bin/bash
###############################################################################
# Setup RTC Synchronization for Field Deployment
###############################################################################
#
# This script ensures the DS1307 RTC on the Raspberry Pi stays synchronized
# with the system clock for accurate timekeeping during field deployment
# when internet/NTP is unavailable.
#
# Usage:
#   sudo ./scripts/setup_rtc_sync.sh
#
# What it does:
#   1. Creates a systemd service to write system time to RTC hourly
#   2. Creates a systemd service to write system time to RTC at shutdown
#   3. Enables both services
#   4. Verifies RTC is working correctly
#
###############################################################################

set -e

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "Error: This script must be run as root (use sudo)"
   exit 1
fi

echo "=========================================="
echo "RTC Synchronization Setup"
echo "=========================================="
echo ""

# Check if RTC exists
if [[ ! -e /dev/rtc0 ]]; then
    echo "Error: No RTC hardware found at /dev/rtc0"
    echo "Make sure your DS1307 RTC module is properly connected"
    exit 1
fi

# Check RTC type
RTC_NAME=$(cat /sys/class/rtc/rtc0/name 2>/dev/null || echo "unknown")
echo "Detected RTC: $RTC_NAME"
echo ""

# Create systemd service for periodic RTC sync (hourly)
cat > /etc/systemd/system/hwclock-sync.service << 'EOF'
[Unit]
Description=Sync system time to hardware clock
After=time-sync.target

[Service]
Type=oneshot
ExecStart=/sbin/hwclock --systohc --utc
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Create systemd timer for hourly sync
cat > /etc/systemd/system/hwclock-sync.timer << 'EOF'
[Unit]
Description=Sync system time to hardware clock hourly

[Timer]
OnBootSec=15min
OnUnitActiveSec=1h
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Create systemd service for shutdown sync
cat > /etc/systemd/system/hwclock-save.service << 'EOF'
[Unit]
Description=Save system time to hardware clock on shutdown
DefaultDependencies=no
Before=shutdown.target

[Service]
Type=oneshot
ExecStart=/sbin/hwclock --systohc --utc
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=halt.target reboot.target shutdown.target
EOF

echo "Created systemd services:"
echo "  - hwclock-sync.service (hourly sync)"
echo "  - hwclock-sync.timer"
echo "  - hwclock-save.service (shutdown sync)"
echo ""

# Reload systemd
systemctl daemon-reload

# Enable and start the timer
systemctl enable hwclock-sync.timer
systemctl start hwclock-sync.timer

# Enable the shutdown service
systemctl enable hwclock-save.service

echo "Enabled services:"
systemctl status hwclock-sync.timer --no-pager -l || true
echo ""

# Perform initial sync
echo "Performing initial system-to-RTC sync..."
/sbin/hwclock --systohc --utc
echo ""

# Verify sync
echo "Verification:"
echo "  System time: $(date)"
echo "  RTC time:    $(hwclock --show)"
echo ""

# Check time difference
SYSTEM_EPOCH=$(date +%s)
RTC_EPOCH=$(hwclock --get --utc 2>/dev/null | date -d "$(hwclock --show)" +%s 2>/dev/null || echo "0")
DIFF=$((SYSTEM_EPOCH - RTC_EPOCH))
DIFF_ABS=${DIFF#-}

if [[ $DIFF_ABS -lt 2 ]]; then
    echo "✓ System and RTC times are synchronized (within ${DIFF_ABS}s)"
else
    echo "⚠ Warning: System and RTC differ by ${DIFF_ABS} seconds"
fi

echo ""
echo "=========================================="
echo "RTC Configuration Summary"
echo "=========================================="
echo ""
echo "Services enabled:"
echo "  - Hourly sync:    systemctl status hwclock-sync.timer"
echo "  - Shutdown sync:  systemctl status hwclock-save.service"
echo ""
echo "Manual commands:"
echo "  Sync system → RTC:  sudo hwclock --systohc --utc"
echo "  Sync RTC → system:  sudo hwclock --hctosys --utc"
echo "  View RTC time:      sudo hwclock --show"
echo ""
echo "Field Deployment:"
echo "  1. Connect to internet and let NTP sync (wait ~5 minutes)"
echo "  2. Verify time: date"
echo "  3. Sync to RTC: sudo hwclock --systohc --utc"
echo "  4. Disconnect and deploy - RTC will maintain time"
echo "  5. On boot, system will load time from RTC automatically"
echo ""
echo "✓ RTC synchronization setup complete!"
echo "=========================================="
