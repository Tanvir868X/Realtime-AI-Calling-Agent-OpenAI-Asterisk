#!/usr/bin/env python3
"""
Simple startup script for the Asterisk Calling Agent
"""
import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    try:
        from main import main
        import asyncio
        
        print("🚀 Starting Asterisk Calling Agent...")
        asyncio.run(main())
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Make sure all dependencies are installed: pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)
