#!/usr/bin/env python3
"""
LoCoMo Test Environment Manager

Check, run, and clean the LoCoMo test environment.

Usage:
    python app.py              # Interactive menu
    python app.py status       # Check service status
    python app.py start       # Start embedding service
    python app.py stop         # Stop embedding service
    python app.py clean       # Clean environment
    python app.py test         # Test embedding service

Environment Variables:
    OPENCLAW_DIR   - OpenClaw home directory (default: auto-detected)
    AGFS_DATA_DIR  - AGFS data directory (default: auto-detected)
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Paths (auto-detected or from environment)
SCRIPT_DIR = Path(__file__).parent
OPENCLAW_DIR = Path(os.environ.get(
    "OPENCLAW_DIR",
    "/home/yuanjian/Development/memory-projects/openclaw_dir"
))
AGFS_DATA_DIR = Path(os.environ.get(
    "AGFS_DATA_DIR",
    "/home/yuanjian/Development/memory-projects/agfs_data"
))

# Containers to manage
CONTAINERS = {
    "ogmem": "ogmem_yuanjian",
    "openclaw": "openclaw_ogmem_yuanjian",
}

EMBEDDING_SERVICE_PORT = 8000


def run_cmd(cmd: list[str], capture: bool = True) -> tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            timeout=30,
        )
        return result.returncode, result.stdout or "", result.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)


def docker_ps() -> dict[str, dict]:
    """Get docker ps output as dict."""
    code, out, _ = run_cmd(["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"])
    if code != 0:
        return {}
    containers = {}
    for line in out.strip().split("\n"):
        if "\t" in line:
            name, status = line.split("\t", 1)
            containers[name] = {"status": status}
    return containers


def is_port_open(host: str, port: int) -> bool:
    """Check if a port is open."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        result = sock.connect_ex((host, port))
        return result == 0
    except Exception:
        return False
    finally:
        sock.close()


def cmd_status():
    """Show status of all services."""
    print("=" * 50)
    print("📊 LoCoMo Test Environment Status")
    print("=" * 50)

    containers = docker_ps()

    print("\n🐳 Docker Containers:")
    for key, name in CONTAINERS.items():
        info = containers.get(name, {})
        status = info.get("status", "not found")
        running = status.lower().startswith("up")
        icon = "✅" if running else "❌"
        print(f"  {icon} {key:12s} {name:30s} {status}")

    print("\n🌐 Embedding Service:")
    port_open = is_port_open("127.0.0.1", EMBEDDING_SERVICE_PORT)
    icon = "✅" if port_open else "❌"
    print(f"  {icon} 127.0.0.1:{EMBEDDING_SERVICE_PORT}")

    print()


def cmd_start():
    """Start the embedding service."""
    print(f"🚀 Starting embedding service on port {EMBEDDING_SERVICE_PORT}...")

    # Check if already running
    if is_port_open("127.0.0.1", EMBEDDING_SERVICE_PORT):
        print("✅ Embedding service already running")
        return

    # Start the service with uv run
    cmd = [
        "uv", "run",
        sys.executable,
        str(SCRIPT_DIR / "deploy_model.py"),
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=SCRIPT_DIR,
    )
    print(f"✅ Started embedding service (PID: {proc.pid})")
    print(f"   Check logs: tail -f /proc/{proc.pid}/fd/1")
    print(f"   Or run: uv run python deploy_model.py --test")


def cmd_stop():
    """Stop the embedding service."""
    print("🛑 Stopping embedding service...")

    # Find and kill the process using the port
    code, out, _ = run_cmd(["lsof", "-i", f":{EMBEDDING_SERVICE_PORT}", "-t"])
    if code == 0 and out.strip():
        pids = out.strip().split("\n")
        for pid in pids:
            run_cmd(["kill", pid])
        print(f"✅ Killed process(es) on port {EMBEDDING_SERVICE_PORT}")
    else:
        print("ℹ️  No process found on port")


def cmd_clean():
    """Clean the environment."""
    print("🧹 Cleaning LoCoMo environment...")

    containers = docker_ps()

    # Stop containers
    for key, name in CONTAINERS.items():
        if name in containers and "Up" in containers[name].get("status", ""):
            print(f"  Stopping {name}...")
            run_cmd(["docker", "stop", name])

    # Clean directories
    dirs_to_clean = [
        OPENCLAW_DIR / "agents/main/sessions",
        OPENCLAW_DIR / "agents/main/archive",
        OPENCLAW_DIR / "agents/main/agent",
        OPENCLAW_DIR / "tasks",
        OPENCLAW_DIR / "logs",
        AGFS_DATA_DIR,
        SCRIPT_DIR / "test_results/ogmem-small",
    ]

    for dir_path in dirs_to_clean:
        if dir_path.exists():
            # Use find to handle non-empty directories
            code, _, _ = run_cmd(["rm", "-rf", f"{dir_path}/."])
            print(f"  Cleaned {dir_path}")

    # Restart containers
    print("\n🔄 Starting containers...")
    for key, name in CONTAINERS.items():
        run_cmd(["docker", "start", name])
        print(f"  Started {name}")

    print("\n✅ Environment cleaned!")


def cmd_test():
    """Test the embedding service."""
    print("🧪 Testing embedding service...")

    if not is_port_open("127.0.0.1", EMBEDDING_SERVICE_PORT):
        print(f"❌ Embedding service not running on port {EMBEDDING_SERVICE_PORT}")
        print("   Run: python app.py start")
        return

    # Run the test
    cmd = [sys.executable, str(SCRIPT_DIR / "deploy_model.py"), "--test"]
    code, out, err = run_cmd(cmd)

    if code == 0:
        print("✅ Embedding service test passed!")
    else:
        print(f"❌ Test failed:\n{err}")


def cmd_shell():
    """Interactive shell."""
    print("🔌 LoCoMo Test Environment Shell")
    print("Type 'help' for commands, 'exit' to quit")
    print()

    while True:
        try:
            cmd = input("locomo> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Goodbye!")
            break

        if not cmd:
            continue

        if cmd in ("exit", "quit", "q"):
            print("👋 Goodbye!")
            break

        if cmd == "help":
            print("Commands:")
            print("  status  - Show service status")
            print("  start   - Start embedding service")
            print("  stop    - Stop embedding service")
            print("  clean   - Clean environment")
            print("  test    - Test embedding service")
            print("  exit    - Exit shell")
        elif cmd == "status":
            cmd_status()
        elif cmd == "start":
            cmd_start()
        elif cmd == "stop":
            cmd_stop()
        elif cmd == "clean":
            cmd_clean()
        elif cmd == "test":
            cmd_test()
        else:
            print(f"Unknown command: {cmd}. Type 'help' for available commands.")


def main():
    parser = argparse.ArgumentParser(
        description="LoCoMo Test Environment Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("status", help="Check service status")
    subparsers.add_parser("start", help="Start embedding service")
    subparsers.add_parser("stop", help="Stop embedding service")
    subparsers.add_parser("clean", help="Clean environment")
    subparsers.add_parser("test", help="Test embedding service")
    subparsers.add_parser("shell", help="Interactive shell")

    args = parser.parse_args()

    if args.command is None:
        cmd_shell()
    elif args.command == "status":
        cmd_status()
    elif args.command == "start":
        cmd_start()
    elif args.command == "stop":
        cmd_stop()
    elif args.command == "clean":
        cmd_clean()
    elif args.command == "test":
        cmd_test()
    elif args.command == "shell":
        cmd_shell()


if __name__ == "__main__":
    main()