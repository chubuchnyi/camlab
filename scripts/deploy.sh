#!/usr/bin/env bash
# Ship camlab to the GPU box, build it there, and open a tunnel to it.
#
# Run from the repo root:  bash scripts/deploy.sh
#
# Three things about that box that shape this script, all learned the hard way and all recorded in
# pitch3d's docs/local-gpu-box.md:
#
#  1. **The ssh shell is cmd.exe, not bash.** Everything real happens one level in, inside WSL, and
#     the job is shipped as a FILE — composing a command through ssh -> cmd -> wsl -> bash breaks
#     the quoting at every hop and surfaces as a syntax error in your own script.
#  2. **WSL kills background jobs when the launching wsl.exe exits.** `setsid nohup ... &` does not
#     survive. The server has to be a detached container, owned by dockerd.
#  3. **WSL's localhost forwarding does not reach this container.** Measured 2026-08-10: from
#     Windows, `127.0.0.1:8000` returns 000 while the WSL IP `:8000` returns 200. See §Access.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST=${HOST:-demorig}
LOCAL_PORT=${LOCAL_PORT:-8100}
STAGE=${STAGE:-C:/Users/user}

echo "== packing (tracked files only)"
git archive --format=tar.gz -o /tmp/camlab.tgz HEAD
echo "   $(du -h /tmp/camlab.tgz | cut -f1)"

echo "== shipping to $HOST"
scp -q /tmp/camlab.tgz "$HOST:$STAGE/camlab.tgz"
scp -q scripts/deploy_wsl.sh "$HOST:$STAGE/camlab_deploy.sh"

# Ship the tracked tree at HEAD, so what runs on the box is a commit and not a working copy.
# Uncommitted work is invisible to this on purpose.
echo "== local HEAD: $(git log --oneline -1)"
echo "== building and running inside WSL"
OUT=$(ssh "$HOST" "wsl.exe -d Ubuntu-24.04 --user root -- bash /mnt/c/Users/user/camlab_deploy.sh")
echo "$OUT"
WSL_IP=$(echo "$OUT" | sed -n 's/^WSL_IP=//p' | tr -d '\r')
[ -n "$WSL_IP" ] || { echo "!! could not read the WSL IP from the deploy output"; exit 1; }

# --- Access ------------------------------------------------------------------------------------
# An ssh tunnel, deliberately, rather than `netsh interface portproxy` + a firewall rule:
#
#   * it needs no change to the box's firewall or network configuration;
#   * it exposes nothing to the LAN — the page is reachable only by whoever already holds the ssh
#     key, over the channel that key already authenticates;
#   * the WSL IP is DYNAMIC and changes when the VM restarts, so a portproxy pinned to it is a rule
#     that silently stops working. This script re-reads the IP on every deploy instead.
#
# If you ever do want it on the LAN, that is a firewall change and it is yours to make, not this
# script's.
echo "== tunnel localhost:$LOCAL_PORT -> $WSL_IP:8000"
pkill -f "ssh -f -N -L $LOCAL_PORT:" 2>/dev/null || true
sleep 1
ssh -f -N -L "$LOCAL_PORT:$WSL_IP:8000" -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 "$HOST"
sleep 2
curl -sS -m 20 -o /dev/null -w "   /api/health -> %{http_code}\n" "http://127.0.0.1:$LOCAL_PORT/api/health"

# Prove the deploy took, rather than trusting that a build with no error changed anything. A
# container that starts, serves the viewer and runs OLD code looks identical from the outside —
# the box sat two hours stale behind a green deploy before anyone asked.
echo "== what is actually running there:"
ssh "$HOST" "wsl.exe -d Ubuntu-24.04 --user root -- docker exec camlab pip show camlab" \
  2>/dev/null | sed -n 's/^Version: /   camlab /p' || true
curl -sS -m 120 "http://127.0.0.1:$LOCAL_PORT/api/run/fan/residual/0" 2>/dev/null \
  | python3 -c "import json,sys
try:
    d = json.load(sys.stdin)
except Exception:
    print('   (no fan run on the box, or the residual route is absent)'); raise SystemExit
k = 'worst_line_px'
print(f\"   residual route: {k}={d.get(k)} — present means the current metric is live\")" || true
echo
echo "   open http://localhost:$LOCAL_PORT"
