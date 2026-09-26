#!/usr/bin/env bash
# WorkFlowOS: one command to run everything (Mac/Linux).
set -e
cd "$(dirname "$0")/backend"
python3 -m pip install -q -r requirements.txt
python3 -m playwright install chromium >/dev/null 2>&1 || true
if [ ! -f ../frontend/dist/index.html ]; then
  echo "Building the web app (needs Node 18+)..."
  (cd ../frontend && npm install && npm run build)
fi
echo ""
echo "  WorkFlowOS is running:  http://localhost:8765"
echo "  Real observation: python3 agent/wfos_agent.py   (in another terminal)"
echo ""
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8765
