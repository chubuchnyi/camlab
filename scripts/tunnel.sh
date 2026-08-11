#!/usr/bin/env bash
# Keep localhost:8100 pointed at the camlab container on the GPU box, and keep the box's WSL VM
# awake so there is something to point at.
#
# TWO separate things go wrong and both present as "the backend is down".
#
#  1. **The ssh forward dies.** `deploy.sh` opens it once and nothing supervises it. The container
#     keeps running and the WSL IP does not change. Diagnosis: `ss -ltn | grep 8100` shows nothing.
#
#  2. **The WSL VM shuts itself down when nothing is attached to it**, taking dockerd and every
#     container with it. Then each probe wakes it, it answers, and it sleeps again — so the box
#     looks alive from a shell and dead from a browser. Diagnosis: `uptime -p` inside WSL reads a
#     few minutes when it should read days, and every container says "Up 1 second".
#     Worse, a dockerd that came back from an unclean stop can run a container whose port binding
#     is CONFIGURED and not established: `docker inspect` shows
#     `PortBindings=map[8000/tcp:[{0.0.0.0 8000}]]` while `docker port camlab` prints nothing.
#     Only recreating the container fixes that — `docker restart` does not. Run `deploy.sh`.
#
# The keeper below is the fix for (2): while a `wsl.exe` process is running, WSL keeps the distro
# up. It costs one idle ssh session and needs no change to the box's Windows configuration.
#
#   bash scripts/tunnel.sh          # check, and re-establish whatever is missing
#   bash scripts/tunnel.sh --watch  # stay up, re-establishing whenever either drops
set -uo pipefail
cd "$(dirname "$0")/.."

HOST=${HOST:-demorig}
LOCAL_PORT=${LOCAL_PORT:-8100}
KEEPER="wsl.exe -d Ubuntu-24.04 --user root -- sleep infinity"

up() { curl -sS -m 8 -o /dev/null "http://127.0.0.1:$LOCAL_PORT/api/health" 2>/dev/null; }

keeper_up() { pgrep -f "sleep infinity" >/dev/null 2>&1 && pgrep -f "ssh.*$HOST" >/dev/null 2>&1; }

keeper_start() {
  if keeper_up; then return 0; fi
  echo "   starting the WSL keeper (the VM sleeps without one, and takes dockerd with it)"
  setsid ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=1000 "$HOST" "$KEEPER" \
    >/dev/null 2>&1 < /dev/null &
  sleep 5
}

start() {
  pkill -f "ssh -f -N -L $LOCAL_PORT:" 2>/dev/null
  sleep 1
  # The WSL IP is dynamic and changes when the VM restarts, so it is read every time rather than
  # remembered. A tunnel pinned to a stale one connects and then serves nothing.
  local ip
  ip=$(ssh -o ConnectTimeout=15 "$HOST" \
       "wsl.exe -d Ubuntu-24.04 --user root -- hostname -I" 2>/dev/null \
       | tr -d '\r' | awk '{print $1}')
  if [ -z "$ip" ]; then echo "!! could not reach $HOST or read the WSL IP"; return 1; fi
  ssh -f -N -L "$LOCAL_PORT:$ip:8000" -o ExitOnForwardFailure=yes \
      -o ServerAliveInterval=30 -o ServerAliveCountMax=3 "$HOST" || return 1
  sleep 2
  up || { echo "!! tunnel opened to $ip but nothing answered — is the container running?"; return 1; }
  echo "   localhost:$LOCAL_PORT -> $ip:8000"
}

if [ "${1:-}" = "--watch" ]; then
  while true; do
    keeper_start
    if ! up; then echo "$(date +%H:%M:%S) not serving, re-establishing"; start; fi
    sleep 30
  done
fi

keeper_start
if up; then echo "   localhost:$LOCAL_PORT is already serving"; else start; fi
