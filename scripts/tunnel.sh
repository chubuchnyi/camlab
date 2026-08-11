#!/usr/bin/env bash
# Keep localhost:8100 pointed at the camlab container on the GPU box.
#
# `deploy.sh` opens this tunnel once and nothing supervises it. When it dies — a dropped link, a
# laptop sleeping, a network change — the page goes blank and it reads as "the backend is down",
# which it is not: the container keeps running and the WSL IP does not change. Diagnosis is
# `ss -ltn | grep 8100`, and this script is the answer.
#
#   bash scripts/tunnel.sh          # check, and re-establish if needed
#   bash scripts/tunnel.sh --watch  # stay up, re-establishing whenever it drops
set -uo pipefail
cd "$(dirname "$0")/.."

HOST=${HOST:-demorig}
LOCAL_PORT=${LOCAL_PORT:-8100}

up() { curl -sS -m 8 -o /dev/null "http://127.0.0.1:$LOCAL_PORT/api/health" 2>/dev/null; }

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
    if ! up; then echo "$(date +%H:%M:%S) tunnel down, re-establishing"; start; fi
    sleep 30
  done
fi

if up; then echo "   localhost:$LOCAL_PORT is already serving"; else start; fi
