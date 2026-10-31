#!/usr/bin/env python3
"""
scripts/run_ssh_tunnel.py
Supervisor process for BooStudy Dev Reverse SSH Tunnel.
Maintains persistent reverse port forwarding with controlled auto-reconnect.
Ensures zero orphan processes and clean shutdown upon stop signal.
"""

import argparse
import datetime
import os
import signal
import subprocess
import sys
import time

def log(msg: str, log_file=None):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{ts}] [SSH-TUNNEL] {msg}"
    print(formatted, flush=True)
    if log_file:
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(formatted + "\n")
        except Exception:
            pass

def main():
    parser = argparse.ArgumentParser(description="BooStudy Reverse SSH Tunnel Supervisor")
    parser.add_argument("--remote-host", required=True, help="IP or domain of dev-VPS")
    parser.add_argument("--remote-user", default="boostudy-tunnel", help="SSH user on dev-VPS")
    parser.add_argument("--key-path", required=True, help="Path to SSH private key")
    parser.add_argument("--remote-port", type=int, default=5055, help="Remote listening port on dev-VPS")
    parser.add_argument("--local-port", type=int, default=5050, help="Local listening port of gateway")
    parser.add_argument("--pid-file", default="instance/ssh_tunnel.pid", help="PID file path")
    parser.add_argument("--log-file", default="instance/ssh_tunnel.log", help="Log file path")
    parser.add_argument("--stop-file", default="instance/ssh_tunnel_stop.flag", help="Stop flag file path")
    args = parser.parse_args()

    stop_file = os.path.abspath(args.stop_file)
    pid_file = os.path.abspath(args.pid_file)
    log_file = os.path.abspath(args.log_file)
    key_path = os.path.abspath(os.path.expanduser(os.path.expandvars(args.key_path)))

    if os.path.exists(stop_file):
        try:
            os.remove(stop_file)
        except OSError:
            pass

    os.makedirs(os.path.dirname(pid_file), exist_ok=True)
    with open(pid_file, "w", encoding="ascii") as f:
        f.write(str(os.getpid()))

    log(f"Supervisor started (PID: {os.getpid()}). Target: {args.remote_user}@{args.remote_host}, Forward: {args.remote_port} -> 127.0.0.1:{args.local_port}", log_file)

    ssh_cmd = [
        "ssh",
        "-NT",
        "-R", f"{args.remote_port}:127.0.0.1:{args.local_port}",
        "-i", key_path,
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=3",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        f"{args.remote_user}@{args.remote_host}"
    ]

    current_proc = None

    def handle_sigterm(signum, frame):
        log("Received termination signal. Shutting down child SSH process...", log_file)
        if current_proc and current_proc.poll() is None:
            current_proc.terminate()
            try:
                current_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                current_proc.kill()
        if os.path.exists(pid_file):
            try:
                os.remove(pid_file)
            except OSError:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigterm)
    signal.signal(signal.SIGTERM, handle_sigterm)

    consecutive_fast_failures = 0
    while True:
        if os.path.exists(stop_file):
            log("Stop flag detected. Halting tunnel supervisor.", log_file)
            break

        start_time = time.time()
        log(f"Establishing SSH connection to {args.remote_host}...", log_file)
        try:
            current_proc = subprocess.Popen(
                ssh_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace"
            )

            # Monitor stdout/stderr
            for line in iter(current_proc.stdout.readline, ''):
                line_str = line.strip()
                if line_str:
                    log(f"[ssh] {line_str}", log_file)

            current_proc.wait()
            exit_code = current_proc.returncode
            duration = time.time() - start_time
            log(f"SSH process exited with code {exit_code} (ran for {duration:.1f}s)", log_file)

        except Exception as e:
            log(f"Error launching SSH process: {e}", log_file)
            duration = 0

        if os.path.exists(stop_file):
            log("Stop flag detected. Halting tunnel supervisor.", log_file)
            break

        # Anti-thrashing backoff: if process failed very quickly (< 5s)
        if duration < 5:
            consecutive_fast_failures += 1
        else:
            consecutive_fast_failures = 0

        if consecutive_fast_failures >= 5:
            backoff_sec = 30
            log(f"High failure rate detected ({consecutive_fast_failures} rapid failures). Backing off for {backoff_sec}s...", log_file)
        else:
            backoff_sec = 5
            log(f"Connection lost. Reconnecting in {backoff_sec}s...", log_file)

        # Sleep with stop flag responsiveness
        for _ in range(backoff_sec * 2):
            if os.path.exists(stop_file):
                break
            time.sleep(0.5)

    if os.path.exists(pid_file):
        try:
            os.remove(pid_file)
        except OSError:
            pass
    log("Supervisor stopped cleanly.", log_file)

if __name__ == "__main__":
    main()
