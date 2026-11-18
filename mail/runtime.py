"""Container startup, graceful shutdown, configuration reload and health checks."""

import os
import secrets
import signal
import smtplib
import socket
import subprocess
import sys
import time

from configure import ConfigurationError, STATE_DIR, configure, load_configuration


def healthcheck():
    for port in (10001, 10002):
        with socket.create_connection(("127.0.0.1", port), timeout=3):
            pass
    with smtplib.SMTP("127.0.0.1", 25, timeout=3) as smtp:
        smtp.ehlo()
        if not smtp.has_extn("starttls"):
            raise RuntimeError("STARTTLS is unavailable")
        if smtp.noop()[0] != 250:
            raise RuntimeError("SMTP health check failed")


def run():
    settings, rules = load_configuration()
    configure(settings, rules)
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    secret_file = STATE_DIR / "postsrsd.secret"
    try:
        descriptor = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if not secret_file.is_file() or not secret_file.read_text().strip():
            raise ConfigurationError("Persistent SRS secret is empty or invalid")
    else:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(secrets.token_hex(32) + "\n")
    secret_file.chmod(0o600)
    # `check` creates queue subdirectories with Postfix ownership/permissions.
    # `set-permissions` also tries to chown manpages omitted by slim images.
    subprocess.run(["postfix", "check"], check=True)

    stopping = False

    def stop(_signal, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    processes = []
    try:
        processes.append(subprocess.Popen([
            "postsrsd", "-4", "-l", "127.0.0.1", "-f", "10001", "-r", "10002",
            "-d", settings.srs_domain, "-s", str(secret_file), "-u", "postsrsd",
            "-n", "8", "-N", "8", "-t", "30",
        ], start_new_session=True))
        # A failed SRS startup must never leave an unauthenticated forwarder up.
        for _attempt in range(100):
            if processes[0].poll() is not None:
                raise RuntimeError("PostSRSd exited during startup")
            try:
                with socket.create_connection(("127.0.0.1", 10002), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("PostSRSd did not become ready")
        processes.append(subprocess.Popen(["postfix", "start-fg"], start_new_session=True))
        print(f"Forwarding {len(rules)} rule(s) for {', '.join(settings.domains)}", flush=True)
        while not stopping:
            if any(process.poll() is not None for process in processes):
                raise RuntimeError("A mail daemon exited unexpectedly")
            time.sleep(0.5)
    finally:
        print("Stopping mail forwarder; queued mail remains on disk", flush=True)
        if len(processes) > 1:
            try:
                subprocess.run(["postfix", "stop"], timeout=15, check=False)
            except subprocess.TimeoutExpired:
                pass
        for process in reversed(processes):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
    return 0


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command == "healthcheck":
        healthcheck()
    elif command == "check":
        settings, rules = load_configuration()
        print(f"Valid configuration: {len(rules)} rule(s), domains {', '.join(settings.domains)}")
    elif command == "reload":
        settings, rules = load_configuration()
        configure(settings, rules)
        subprocess.run(["postfix", "check"], check=True)
        subprocess.run(["postfix", "reload"], check=True)
    elif command == "run":
        return run()
    else:
        raise ConfigurationError(f"Unknown command: {command}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ConfigurationError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Mail forwarder error: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
