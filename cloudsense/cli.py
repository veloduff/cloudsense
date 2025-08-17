#!/usr/bin/env python3
"""CloudSense CLI entry point"""

import argparse
import sys
from .app import create_app

def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(description='CloudSense - AWS Cost Dashboard')
    parser.add_argument('--host', default='127.0.0.1', help='Host to bind to (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=8080, help='Port to bind to (default: 8080)')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    
    args = parser.parse_args()

    try:
        app = create_app()
    except ImportError as e:
        print(f"Error: Missing dependencies - {e}")
        exit(1)
    except Exception as e:
        print(f"Error creating app: {e}")
        exit(1)
    
    try:
        print(f"Starting CloudSense on {args.host}:{args.port}")
        app.run(debug=args.debug, host=args.host, port=args.port)
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"Error: Port {args.port} is already in use. Try a different port with --port")
        elif "Permission denied" in str(e):
            print(f"Error: Permission denied. Try a different port or run as administrator")
        else:
            print(f"Error starting server: {e}")
        exit(1)
    except KeyboardInterrupt:
        print("\nShutting down CloudSense...")
        exit(0)
    except Exception as e:
        print(f"Error running server: {e}")
        exit(1)

if __name__ == '__main__':
    main()