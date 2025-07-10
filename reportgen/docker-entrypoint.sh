#!/bin/bash
# reportgen/docker-entrypoint.sh
# Entry point for NBA Report Generator service

set -e

# Default environment
export PORT=${PORT:-8082}
export PYTHONPATH="/app:/app/shared"

echo "Starting NBA Report Generator service..."
echo "PORT: $PORT"
echo "PYTHONPATH: $PYTHONPATH"

# For now, start a simple Flask health service
# TODO: Replace with actual report generation logic
python3 -c "
from flask import Flask, jsonify
from datetime import datetime, timezone
import os

app = Flask(__name__)

@app.route('/', methods=['GET'])
@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'healthy',
        'service': 'reportgen',
        'version': '1.0.0',
        'timestamp': datetime.now(timezone.utc).isoformat()
    }), 200

@app.route('/generate', methods=['POST'])
def generate():
    return jsonify({
        'status': 'success',
        'message': 'Report Generator service is ready',
        'service': 'reportgen'
    }), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8082)))
"