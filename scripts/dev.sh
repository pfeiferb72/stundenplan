#!/usr/bin/env bash
# SPPS-Entwicklungsumgebung starten: PostgreSQL (eingebettet) + Backend-API + Frontend-Devserver
set -e
cd "$(dirname "$0")/.."
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
echo "== Backend (DB + API auf :8000) mit $PY =="
cd backend
PYTHONPATH=. "$PY" scripts/dev_server.py &
BACK_PID=$!
cd ../frontend
echo "== Frontend (Vite auf :5173, Proxy /api -> :8000) =="
npm run dev &
FRONT_PID=$!
trap "kill $BACK_PID $FRONT_PID 2>/dev/null" EXIT
wait
