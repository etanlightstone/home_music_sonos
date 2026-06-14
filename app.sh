#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate
echo "Installing/updating dependencies..."
pip install -r requirements.txt -q

echo ""
echo "Starting SonosWeb at http://0.0.0.0:8000"
echo "Access from LAN at http://$(hostname -I | awk '{print $1}'):8000"
echo ""
#uvicorn main:app --host 0.0.0.0 --port 8000 --reload

mkdir ~/sonosweb-certs
cd ~/sonosweb-certs

openssl req -x509 -newkey rsa:2048 \
  -keyout key.pem \
  -out cert.pem \
  -days 3650 \
  -nodes \
  -subj "/CN=10.0.1.50"

uvicorn main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload \
  --ssl-keyfile ~/sonosweb-certs/key.pem \
  --ssl-certfile ~/sonosweb-certs/cert.pem