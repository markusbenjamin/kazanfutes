#!/usr/bin/env bash
# service_manager.sh — start / stop kazanfutes services and timers
#
# 1. make it executable:
#      chmod +x /media/pi/program_stick/kazanfutes/services/service_manager.sh
# 2. symlink:
#      sudo ln -s /media/pi/program_stick/kazanfutes/services/service_manager.sh /usr/local/bin/service_manager
#
# usage:
#   sudo service_manager start          # start everything
#   sudo service_manager stop           # graceful stop
#   sudo service_manager stop now       # fast stop + SIGKILL fallback
#   sudo service_manager report         # one-line status for each unit
#
# list of units: /media/pi/program_stick/kazanfutes/services/services_and_timers.list
# one unit per line, no blanks

LIST=/media/pi/program_stick/kazanfutes/services/services_and_timers.list
TARGET=/etc/systemd/system/kazanfutes.target
WANTS=/etc/systemd/system/kazanfutes.target.wants
MOUNT=media-pi-program_stick.mount

RED=$'\e[31m'
GREEN=$'\e[32m'
RESET=$'\e[0m'

#------------------------------------------------------------
# ensure target exists
if [ ! -f "$TARGET" ]; then
cat >"$TARGET" <<EOF
[Unit]
Description=kazanfutes services and timers
Requires=$MOUNT
After=$MOUNT
EOF
fi

# rebuild wants links
mkdir -p "$WANTS"
rm -f "$WANTS"/*
while read -r unit; do
  [ -z "$unit" ] && continue
  ln -sf "../$unit" "$WANTS/$unit"
done < "$LIST"

systemctl daemon-reload
#------------------------------------------------------------
stop_units() {
    while read -r unit; do
        [ -z "$unit" ] && continue
        systemctl stop "$unit"
    done < "$LIST"
}

kill_units() {
    while read -r unit; do
        [ -z "$unit" ] && continue
        systemctl kill --signal=SIGKILL "$unit"
    done < "$LIST"
}

report_stop() {
    local ok=true
    while read -r unit; do
        [ -z "$unit" ] && continue
        if systemctl is-active --quiet "$unit"; then
            printf '%s%s still running%s\n' "$GREEN" "$unit" "$RESET"
            ok=false
        else
            printf '%s%s stopped%s\n' "$RED" "$unit" "$RESET"
        fi
    done < "$LIST"
    if $ok; then
        printf '%sall units stopped%s\n' "$RED" "$RESET"
    else
        printf '%ssome units still active%s\n' "$GREEN" "$RESET"
    fi
}

report_units() {
    while read -r unit; do
        [ -z "$unit" ] && continue
        state=$(systemctl is-active "$unit")
        color=$RED; [[ $state == "active" || $state == "waiting" ]] && color=$GREEN
        if [[ $unit == *.timer ]]; then
            last=$(systemctl show -p LastTriggerUSec --value "$unit")
            next=$(systemctl show -p NextElapseUSec  --value "$unit")
            printf '%s%-35s | %-8s | last: %s | next: %s%s\n' "$color" "$unit" "$state" "${last:--}" "${next:--}" "$RESET"
        else
            start=$(systemctl show -p ExecMainStartTimestamp --value "$unit")
            exit=$(systemctl show -p ExecMainExitTimestamp  --value "$unit")
            printf '%s%-35s | %-8s | started: %s | exit: %s%s\n' "$color" "$unit" "$state" "${start:--}" "${exit:--}" "$RESET"
        fi
    done < "$LIST"
}

case "$1" in
  start)
        systemctl start kazanfutes.target
        ;;
  stop)
        stop_units
        [ "$2" = "now" ] && kill_units
        report_stop
        ;;
  report)
        report_units
        ;;
  *)
        echo "usage: $0 start | stop [now] | report" >&2
        exit 1
        ;;
esac