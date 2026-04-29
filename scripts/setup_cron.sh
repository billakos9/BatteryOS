#!/bin/bash
# Setup cron job for daily DAM inference at 9:00 AM Europe/Athens

REPO_ROOT="/home/dimit/BatteryOS"
PYTHON="$REPO_ROOT/.venv/bin/python"
SCRIPT="$REPO_ROOT/pipelines/daily_inference.py"
LOG_DIR="$REPO_ROOT/logs"

mkdir -p "$LOG_DIR"

echo "Setting up cron job for daily inference..."
echo "  Repo    : $REPO_ROOT"
echo "  Python  : $PYTHON"
echo "  Script  : $SCRIPT"
echo "  Log dir : $LOG_DIR"
echo ""

# Add cron entry (runs at 9:00 AM daily)
CRON_JOB="0 9 * * * cd $REPO_ROOT && $PYTHON $SCRIPT >> $LOG_DIR/daily_inference.log 2>&1"

# Check if already exists
if crontab -l 2>/dev/null | grep -q "$SCRIPT"; then
    echo "Cron job already exists. Removing old entry..."
    crontab -l | grep -v "$SCRIPT" | crontab -
fi

# Add new entry
(crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -

echo "Cron job installed:"
echo "  $CRON_JOB"
echo ""
echo "Current crontab:"
crontab -l
echo ""
echo "To verify it's working, wait until 9:00 AM or run manually:"
echo "  cd $REPO_ROOT && source .venv/bin/activate && python pipelines/daily_inference.py"
