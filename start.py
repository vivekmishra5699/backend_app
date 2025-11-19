#!/usr/bin/env python3
"""
Start script for Render deployment
Ensures uvicorn runs with proper ASGI configuration
"""
import os
import sys
import subprocess

def main():
    port = os.getenv('PORT', '10000')
    workers = os.getenv('WEB_CONCURRENCY', '2')
    
    print(f"🚀 Starting FastAPI with uvicorn...")
    print(f"   Port: {port}")
    print(f"   Workers: {workers}")
    print(f"   Host: 0.0.0.0")
    
    cmd = [
        'uvicorn',
        'app:app',
        '--host', '0.0.0.0',
        '--port', port,
        '--workers', workers,
        '--log-level', 'info'
    ]
    
    print(f"   Command: {' '.join(cmd)}")
    
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error starting server: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n👋 Server stopped by user")
        sys.exit(0)

if __name__ == '__main__':
    main()
