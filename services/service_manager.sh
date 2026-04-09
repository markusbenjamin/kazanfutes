#!/usr/bin/env bash
# service_manager.sh — start / stop kazanfutes services and timers
#
# usage:
#   sudo service_manager rebuild        # rebuild target wants from list
#   sudo service_manager sync           # alias for rebuild
#   sudo service_manager start          # start target, then report how it went
#   sudo service_manager stop           # graceful stop
#   sudo service_manager stop now       # fast stop + SIGKILL fallback
#   sudo service_manager report         # one-line status for each unit
#   sudo service_manager validate       # check whether listed units exist
#   sudo service_manager -help
#   sudo service_manager --help
#   sudo service_manager -usage
#   sudo service_manager --usage
#
# list of units: /media/pi/program_stick/kazanfutes/services/services_and_timers.list
# one unit per line, blanks and # comments ignored

set -u

LIST=/media/pi/program_stick/kazanfutes/services/services_and_timers.list
TARGET_NAME=kazanfutes.target
TARGET=/etc/systemd/system/$TARGET_NAME
WANTS=/etc/systemd/system/$TARGET_NAME.wants
MOUNT=media-pi-program_stick.mount

RED=$'\e[31m'
GREEN=$'\e[32m'
YELLOW=$'\e[33m'
RESET=$'\e[0m'

#------------------------------------------------------------
usage() {
cat <<EOF
usage:
  $0 rebuild        rebuild target wants from list
  $0 sync           alias for rebuild
  $0 start          start target, then report how it went
  $0 stop           graceful stop of listed units
  $0 stop now       fast stop + SIGKILL fallback
  $0 report         one-line status for each listed unit
  $0 validate       show whether listed units exist
  $0 -help|--help|-usage|--usage
EOF
}

die() {
    echo "$*" >&2
    exit 1
}

ensure_list_exists() {
    [ -f "$LIST" ] || die "missing unit list: $LIST"
}

unit_lines() {
    ensure_list_exists
    sed -e 's/[[:space:]]*$//' "$LIST" \
    | grep -v '^[[:space:]]*$' \
    | grep -v '^[[:space:]]*#'
}

ensure_target_exists() {
    if [ ! -f "$TARGET" ]; then
cat >"$TARGET" <<EOF
[Unit]
Description=kazanfutes services and timers
Requires=$MOUNT
After=$MOUNT
EOF
    fi
}

unit_exists() {
    local unit="$1"
    systemctl cat "$unit" >/dev/null 2>&1
}

clear_wants_dir() {
    mkdir -p "$WANTS"
    find "$WANTS" -mindepth 1 -maxdepth 1 -type l -exec rm -f {} +
}

rebuild_wants() {
    ensure_target_exists
    clear_wants_dir

    local missing=0

    while IFS= read -r unit; do
        [ -z "$unit" ] && continue

        if unit_exists "$unit"; then
            if systemctl add-wants "$TARGET_NAME" "$unit" >/dev/null 2>&1; then
                printf '%slinked%s %s\n' "$GREEN" "$RESET" "$unit"
            else
                printf '%sfailed%s %s\n' "$RED" "$RESET" "$unit"
                missing=1
            fi
        else
            printf '%smissing%s %s\n' "$YELLOW" "$RESET" "$unit"
            missing=1
        fi
    done < <(unit_lines)

    systemctl daemon-reload
    return $missing
}

stop_units() {
    while IFS= read -r unit; do
        [ -z "$unit" ] && continue
        if unit_exists "$unit"; then
            systemctl stop "$unit"
        fi
    done < <(unit_lines)
}

kill_units() {
    while IFS= read -r unit; do
        [ -z "$unit" ] && continue
        if unit_exists "$unit"; then
            systemctl kill --signal=SIGKILL "$unit" 2>/dev/null || true
        fi
    done < <(unit_lines)
}

report_stop() {
    local ok=true
    while IFS= read -r unit; do
        [ -z "$unit" ] && continue

        if ! unit_exists "$unit"; then
            printf '%s%s missing%s\n' "$YELLOW" "$unit" "$RESET"
            ok=false
            continue
        fi

        if systemctl is-active --quiet "$unit"; then
            printf '%s%s still running%s\n' "$GREEN" "$unit" "$RESET"
            ok=false
        else
            printf '%s%s stopped%s\n' "$RED" "$unit" "$RESET"
        fi
    done < <(unit_lines)

    if $ok; then
        printf '%sall units stopped%s\n' "$RED" "$RESET"
    else
        printf '%ssome units still active or missing%s\n' "$GREEN" "$RESET"
    fi
}

report_units() {
    while IFS= read -r unit; do
        [ -z "$unit" ] && continue

        if ! unit_exists "$unit"; then
            printf '%s%-35s | %-8s%s\n' "$YELLOW" "$unit" "missing" "$RESET"
            continue
        fi

        state=$(systemctl is-active "$unit" 2>/dev/null)
        load=$(systemctl show -p LoadState --value "$unit" 2>/dev/null)
        color=$RED
        [[ "$state" == "active" || "$state" == "waiting" ]] && color=$GREEN

        if [[ $unit == *.timer ]]; then
            last=$(systemctl show -p LastTriggerUSec --value "$unit")
            next=$(systemctl show -p NextElapseUSec --value "$unit")
            printf '%s%-35s | %-8s | load: %-6s | last: %s | next: %s%s\n' \
                "$color" "$unit" "$state" "$load" "${last:--}" "${next:--}" "$RESET"
        else
            start=$(systemctl show -p ExecMainStartTimestamp --value "$unit")
            exit_ts=$(systemctl show -p ExecMainExitTimestamp --value "$unit")
            printf '%s%-35s | %-8s | load: %-6s | started: %s | exit: %s%s\n' \
                "$color" "$unit" "$state" "$load" "${start:--}" "${exit_ts:--}" "$RESET"
        fi
    done < <(unit_lines)
}

validate_units() {
    local missing=0
    while IFS= read -r unit; do
        [ -z "$unit" ] && continue
        if unit_exists "$unit"; then
            printf '%sok%s %s\n' "$GREEN" "$RESET" "$unit"
        else
            printf '%smissing%s %s\n' "$YELLOW" "$RESET" "$unit"
            missing=1
        fi
    done < <(unit_lines)
    return $missing
}

start_target() {
    printf 'starting %s ...\n' "$TARGET_NAME"

    if systemctl start "$TARGET_NAME"; then
        printf '%sstart command succeeded%s for %s\n' "$GREEN" "$RESET" "$TARGET_NAME"
    else
        printf '%sstart command failed%s for %s\n' "$RED" "$RESET" "$TARGET_NAME"
    fi

    target_state=$(systemctl is-active "$TARGET_NAME" 2>/dev/null || true)
    printf 'target state: %s\n' "${target_state:--}"

    echo
    echo "unit status after start:"
    report_units
}

case "${1:-}" in
  rebuild|sync)
        rebuild_wants
        ;;
  start)
        start_target
        ;;
  stop)
        stop_units
        [ "${2:-}" = "now" ] && kill_units
        report_stop
        ;;
  report)
        report_units
        ;;
  validate)
        validate_units
        ;;
  -help|--help|-usage|--usage|help|usage)
        usage
        ;;
  *)
        usage >&2
        exit 1
        ;;
esac