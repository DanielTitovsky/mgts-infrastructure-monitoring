#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/$(basename -- "${BASH_SOURCE[0]}")"
PROJECT_ROOT="$(dirname -- "$SCRIPT_PATH")"
NOTEBOOK="$PROJECT_ROOT/notebooks/dataset_workbench.py"
SECRET_FILE="/home/iter/.kiro/secrets.env"
DOTENV_LOADER="/home/iter/projects/iter-private-setup/scripts/load-dotenv.sh"
PORT="${MGTS_WORKBENCH_PORT:-8790}"
SESSION="mgts-dataset-workbench-$PORT"
URL="http://127.0.0.1:$PORT"
PID_FILE="/tmp/mgts-dataset-workbench.$PORT.pid"
if [[ -n "${XDG_RUNTIME_DIR:-}" && -d "$XDG_RUNTIME_DIR" && -w "$XDG_RUNTIME_DIR" ]]; then
  LOCK_FILE="$XDG_RUNTIME_DIR/mgts-dataset-workbench.$UID.$PORT.lock"
else
  LOCK_FILE="/tmp/mgts-dataset-workbench.$UID.$PORT.lock"
fi
umask 077

if [[ ! "$PORT" =~ ^[0-9]{1,5}$ ]] || (( PORT < 1 || PORT > 65535 )); then
  printf 'invalid MGTS_WORKBENCH_PORT\n' >&2
  exit 2
fi

read_pid() {
  [[ -r "$PID_FILE" ]] || return 1
  local value
  value="$(<"$PID_FILE")"
  [[ "$value" =~ ^[0-9]+$ ]] || return 1
  printf '%s\n' "$value"
}

owns_pid() {
  local pid="$1" command_line
  [[ -r "/proc/$pid/cmdline" ]] || return 1
  command_line="$(tr '\0' ' ' < "/proc/$pid/cmdline")"
  [[ "$command_line" == *"marimo"* && "$command_line" == *"dataset_workbench.py"* ]]
}

listener_pid() {
  ss -H -ltnp "sport = :$PORT" 2>/dev/null \
    | grep -oE 'pid=[0-9]+' \
    | head -n 1 \
    | cut -d= -f2 || true
}

http_status() {
  curl --silent --show-error --max-time 2 --output /dev/null --write-out '%{http_code}' "$URL" 2>/dev/null || true
}

app_ready() {
  local pid
  pid="$(read_pid 2>/dev/null || true)"
  [[ -n "$pid" ]] && owns_pid "$pid" && [[ "$(http_status)" =~ ^[23][0-9][0-9]$ ]]
}

serve() {
  if [[ ! -r "$SECRET_FILE" || ! -r "$DOTENV_LOADER" ]]; then
    printf 'configured local secret store or dotenv loader is unavailable\n' >&2
    return 1
  fi
  # The password is read from the canonical store, never placed in argv/logs.
  source "$DOTENV_LOADER" "$SECRET_FILE"
  if [[ -z "${MARIMO_WORKBENCH_PASSWORD:-}" ]]; then
    printf 'MARIMO_WORKBENCH_PASSWORD is missing from the canonical secret store\n' >&2
    return 1
  fi
  local password="$MARIMO_WORKBENCH_PASSWORD"
  unset MARIMO_WORKBENCH_PASSWORD
  umask 077
  printf '%s\n' "$$" > "$PID_FILE"
  exec uv run --project "$PROJECT_ROOT" --extra ui marimo run "$NOTEBOOK" \
    --host 127.0.0.1 --port "$PORT" --token-password-file - --headless \
    > >(sed --unbuffered --regexp-extended 's/(access_token=)[^&[:space:]]+/\1[REDACTED]/g') 2>&1 \
    <<<"$password"
}

start() {
  local status
  if flock --nonblock --exclusive --close --conflict-exit-code 75 "$LOCK_FILE" "$SCRIPT_PATH" start_locked; then
    return 0
  else
    status=$?
  fi
  if (( status == 75 )); then
    printf 'workbench startup is already in progress\n' >&2
  fi
  return "$status"
}

start_locked() {
  if app_ready; then
    printf 'MGTS workbench already ready: pid=%s url=%s (loopback)\n' "$(read_pid)" "$URL"
    return 0
  fi

  local listener session_list pane pid
  listener="$(listener_pid)"
  if [[ -n "$listener" ]]; then
    printf 'port %s is occupied by an unrelated or unverified process\n' "$PORT" >&2
    return 1
  fi

  session_list="$(zellij list-sessions --no-formatting 2>/dev/null || true)"
  if grep -Eq "^${SESSION}[[:space:]]" <<<"$session_list" \
    && ! grep -Fxq "$SESSION" <<<"$session_list"; then
    printf 'demo session %s exists but is exited; refusing to resurrect it automatically\n' "$SESSION" >&2
    return 1
  fi
  if ! grep -Fxq "$SESSION" <<<"$session_list"; then
    zellij attach --create-background "$SESSION" >/dev/null
  fi

  pane="$(zellij --session "$SESSION" run --name 'MGTS dataset workbench' -- bash "$SCRIPT_PATH" serve)"
  for _ in $(seq 1 90); do
    if app_ready; then
      pid="$(read_pid)"
      printf 'MGTS workbench ready: pid=%s url=%s (loopback; zellij session %s, pane %s)\n' \
        "$pid" "$URL" "$SESSION" "$pane"
      return 0
    fi
    if [[ -n "$(listener_pid)" ]]; then
      printf 'port %s became occupied before the workbench became ready\n' "$PORT" >&2
      return 1
    fi
    sleep 1
  done
  printf 'workbench did not become ready within 90 seconds; inspect zellij session %s\n' "$SESSION" >&2
  return 1
}

status() {
  if app_ready; then
    printf 'MGTS workbench ready: pid=%s url=%s (loopback; zellij session %s)\n' \
      "$(read_pid)" "$URL" "$SESSION"
    return 0
  fi
  printf 'MGTS workbench is not ready on port %s\n' "$PORT"
  return 1
}

stop() {
  local pid listener
  pid="$(read_pid 2>/dev/null || true)"
  if [[ -z "$pid" ]] || ! owns_pid "$pid"; then
    printf 'no verified MGTS workbench process is recorded\n' >&2
    return 1
  fi
  listener="$(listener_pid)"
  if [[ -n "$listener" ]] && ! owns_pid "$listener"; then
    printf 'port %s is now owned by an unverified process; refusing to stop it\n' "$PORT" >&2
    return 1
  fi
  if [[ -n "$listener" && "$listener" != "$pid" ]]; then
    kill -TERM "$listener"
  fi
  kill -TERM "$pid"
  for _ in $(seq 1 15); do
    if ! kill -0 "$pid" 2>/dev/null && { [[ -z "$listener" ]] || ! kill -0 "$listener" 2>/dev/null; }; then
      rm -f -- "$PID_FILE"
      printf 'MGTS workbench stopped (pid=%s)\n' "$pid"
      return 0
    fi
    sleep 1
  done
  printf 'workbench process %s did not stop; leaving its PID record for recovery\n' "$pid" >&2
  return 1
}

case "${1:-}" in
  start) start ;;
  start_locked) start_locked ;;
  status) status ;;
  stop) stop ;;
  serve) serve ;;
  *) printf 'usage: %s {start|status|stop}\n' "$0" >&2; exit 2 ;;
esac
