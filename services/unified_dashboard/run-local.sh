#!/bin/bash
# Local development script for unified dashboard
# Starts backend and frontend with hot reload

set -e

echo "=============================================="
echo "NBA Stats Unified Dashboard - Local Dev"
echo "=============================================="

# Check if we're in the right directory
if [ ! -f "backend/main.py" ]; then
    echo "ERROR: Must run from services/unified_dashboard directory"
    exit 1
fi

# Function to cleanup background processes
cleanup() {
    echo ""
    echo "Shutting down..."
    kill $(jobs -p) 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM

# Install backend dependencies if needed
if [ ! -d "backend/venv" ]; then
    echo "[Setup] Creating Python virtual environment..."
    python3 -m venv backend/venv
    source backend/venv/bin/activate
    pip install -r backend/requirements.txt
fi

# Install frontend dependencies if needed
if [ ! -d "frontend/node_modules" ]; then
    echo "[Setup] Installing frontend dependencies..."
    cd frontend
    npm install
    cd ..
fi

echo ""
echo "Starting services..."
echo "  - Backend:  http://localhost:8080"
echo "  - Frontend: http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Start backend
source backend/venv/bin/activate
cd backend
uvicorn main:app --reload --port 8080 &
BACKEND_PID=$!

# Start frontend
cd ../frontend
npm run dev &
FRONTEND_PID=$!

# Wait for both processes
wait $BACKEND_PID $FRONTEND_PID
