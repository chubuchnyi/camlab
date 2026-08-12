# camlab M0 — the viewer and the pure-numpy core. No CUDA yet, on purpose.
#
# M0's job is to retire the deployment risk (does a container on the box reach a browser at all,
# spec §7.2), not to run models. Nothing here needs a GPU: the core is numpy, and the pitch the
# viewer draws is generated from the Laws of the Game, not detected.
#
# M1 brings PnLCalib, and with it this base line becomes
# `FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime` and `.[cv]` grows the torch stack. Keeping
# that out of M0 is the difference between a 180 MB image that builds in a minute and a 9 GB one.
FROM python:3.12-slim

# libGL/libglib are opencv-python-headless's runtime deps. Installed now rather than at M1 so the
# `[cv]` extra can be turned on without another apt round-trip on a link that resets often.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY calib/ ./calib/
# The solve stages, which the server runs as subprocesses. Without them the viewer's solve button
# fails with "can't open file '/app/scripts/solve_carry.py'" — the image had the library and not
# the thing that drives it.
COPY scripts/ ./scripts/
# `[cv]`, not bare: camlab's ground truth is the paint in the frame, and finding it is a cv2
# pipeline. Without the extra the image starts, serves the viewer, and returns 500 from
# /api/residual — the one endpoint that answers "is this camera right?".
RUN pip install --no-cache-dir -e ".[cv]"

# Runs are a mounted volume, never baked: rebuilding the image must not throw away measurements.
VOLUME ["/runs"]
ENV CAMLAB_RUNS=/runs

EXPOSE 8000
# 0.0.0.0, not 127.0.0.1: inside a container the loopback is the container's own, and the port
# publish would reach nothing.
CMD ["uvicorn", "camlab.server.app:app", "--host", "0.0.0.0", "--port", "8000"]
