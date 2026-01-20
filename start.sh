#!/bin/bash
# Start script for Render deployment
# This ensures uvicorn is used with correct ASGI worker

echo "🚀 Starting FastAPI application with uvicorn..."
echo "Port: $PORT"
echo "Workers: 2"

# Use uvicorn directly (ASGI server for FastAPI)
exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-10000} --workers 2 --log-level info
