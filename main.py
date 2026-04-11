#!/usr/bin/env python3
import sys
import os
import traceback
import time

# 1. Immediate Heartbeat
print("MCP Bundle: Bootstrapping process...", file=sys.stderr)
sys.stderr.flush()

def ensure_dependencies():
    """Checks for required libraries and fails fast if missing."""
    missing = []
    for pkg in ["mcp", "proxmoxer", "pydantic", "fastapi", "uvicorn", "anyio"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
            
    if not missing:
        print("MCP Bundle: All core dependencies detected.", file=sys.stderr)
        sys.stderr.flush()
        return

    raise RuntimeError(
        "Missing runtime dependencies: "
        + ", ".join(missing)
        + ". Install dependencies during build/deploy time instead of runtime."
    )

# 2. Setup Environment
base_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(base_dir, "src")
sys.path.insert(0, src_dir)

def main():
    ensure_dependencies()
    
    try:
        print("MCP Bundle: Importing server logic...", file=sys.stderr)
        sys.stderr.flush()
        
        # This is where the absolute imports are verified
        from proxmox_mcp.server import ProxmoxMCPServer
        
        config_path = os.getenv("PROXMOX_MCP_CONFIG")
        print(f"MCP Bundle: Starting server (Config: {config_path})", file=sys.stderr)
        sys.stderr.flush()
        
        server = ProxmoxMCPServer(config_path)
        server.start()
        
    except Exception as e:
        print("\n" + "!"*60, file=sys.stderr)
        print("CRITICAL STARTUP ERROR", file=sys.stderr)
        print("!"*60, file=sys.stderr)
        
        # Print the exact error type and message first as it's the most stable
        print(f"ERROR TYPE: {type(e).__name__}", file=sys.stderr)
        print(f"ERROR MESSAGE: {str(e)}", file=sys.stderr)
        
        # Then the traceback
        traceback.print_exc(file=sys.stderr)
        print("!"*60 + "\n", file=sys.stderr)
        
        # Crucial: Sleep briefly so the Hub has time to capture the stderr buffer
        sys.stderr.flush()
        time.sleep(1)
        sys.exit(1)

if __name__ == "__main__":
    main()
