#!/usr/bin/env bash
# Find a Python 3.9+ and run tutor.py with it.
#
# Hooks call this rather than `python` directly because the right name differs
# by machine: `py` on Windows (where `python3` is often a Microsoft Store stub
# that only prints an install hint), `python3` on macOS and Linux. The choice
# is cached in the plugin's data folder so later hooks skip the search.

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cache="${CLAUDE_PLUGIN_DATA:+$CLAUDE_PLUGIN_DATA/python-path}"

works() { "$@" -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; }

if [ -n "$cache" ] && [ -f "$cache" ]; then
  read -r -a py < "$cache"
  works "${py[@]}" || py=()
fi

if [ -z "${py[*]}" ]; then
  for candidate in "py -3" python3 python; do
    read -r -a try <<< "$candidate"
    if command -v "${try[0]}" >/dev/null 2>&1 && works "${try[@]}"; then
      py=("${try[@]}")
      break
    fi
  done
  if [ -n "${py[*]}" ] && [ -n "$cache" ]; then
    mkdir -p "$(dirname "$cache")" 2>/dev/null && printf '%s\n' "${py[*]}" > "$cache" 2>/dev/null
  fi
fi

if [ -z "${py[*]}" ]; then
  # No Python. Where tutor mode is on, the guard must not silently allow edits.
  if [ "$1" = "hook-pretool" ]; then
    dir="$PWD"
    while [ -n "$dir" ] && [ "$dir" != "/" ]; do
      if [ -f "$dir/.tutor/state.json" ]; then
        printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"[tutor] Python 3.9+ was not found, so the tutor guard cannot run. Install Python or turn tutor mode off."}}'
        exit 0
      fi
      dir="$(dirname "$dir")"
    done
  fi
  echo "[tutor] Python 3.9+ not found (tried py -3, python3, python)." >&2
  exit 0
fi

exec "${py[@]}" "$here/tutor.py" "$@"
