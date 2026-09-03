#!/usr/bin/env bash
# Reports the four Ollama launch environment variables (research D-17).
#
# Honest limitation: this reads the login session's environment via `launchctl getenv`, which is
# what a *relaunched* Ollama inherits — it cannot inspect an already-running Ollama process. Set
# any missing variable, then quit and relaunch Ollama from the menu bar for it to take effect.
set -euo pipefail

echo "Ollama environment (login session — not the running Ollama process):"
echo

any_unset=0

check_var() {
  local var="$1" expected="$2"
  local value
  value="$(launchctl getenv "$var" 2>/dev/null || true)"
  if [ -z "$value" ]; then
    echo "  UNSET: $var (expected $expected)"
    echo "    fix: launchctl setenv $var $expected"
    any_unset=1
  else
    echo "  SET:   $var=$value"
  fi
}

check_var OLLAMA_NUM_PARALLEL 1
check_var OLLAMA_MAX_LOADED_MODELS 2
check_var OLLAMA_KEEP_ALIVE 30m
check_var OLLAMA_FLASH_ATTENTION 1

echo
if [ "$any_unset" -eq 1 ]; then
  echo "After setting any variable above, quit Ollama from the menu bar and relaunch it —"
  echo "it reads these only at launch."
  exit 1
fi
echo "All four are set for the next Ollama launch."
