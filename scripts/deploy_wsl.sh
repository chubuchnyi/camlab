#!/usr/bin/env bash
# camlab M0 deploy, run INSIDE WSL as root. Shipped as a file on purpose: quoting breaks at every
# hop of ssh -> cmd -> wsl -> bash, and the failure shows up as a syntax error in your own script.
set -euo pipefail
echo "== uptime (up 0 min = the WSL VM bounced and took dockerd with it)"; uptime

DST=/vol/camlab
rm -rf "$DST"; mkdir -p "$DST"
tar xzf /mnt/c/Users/user/camlab.tgz -C "$DST"
echo "== unpacked $(find "$DST" -type f | wc -l) files into $DST"

cd "$DST"
docker build -q -f docker/Dockerfile -t camlab:m0 . | tail -1

# Detached, and NOT --rm: WSL kills anything whose launching wsl.exe has exited, so the container
# has to be owned by dockerd. --restart unless-stopped so it survives a dockerd bounce too.
docker rm -f camlab >/dev/null 2>&1 || true
docker run -d --name camlab --restart unless-stopped \
  -p 0.0.0.0:8000:8000 -v /vol/camlab_runs:/runs camlab:m0 >/dev/null
sleep 5

echo "== container"; docker ps --filter name=camlab --format '{{.Status}}  {{.Ports}}'
echo "== from inside WSL"; curl -sS -o /dev/null -w 'localhost:8000/api/health -> %{http_code}\n' http://127.0.0.1:8000/api/health || true
curl -sS http://127.0.0.1:8000/api/health; echo
echo "== WSL IP (the address a Windows portproxy has to point at)"
hostname -I | awk '{print "WSL_IP="$1}'
