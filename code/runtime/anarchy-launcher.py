
import subprocess
import signal
import os
import time
import re
import selectors
import urllib.request
import urllib.error


# ============================================================
# CONFIGURATION
# ============================================================

TUNNEL_SCRIPT = "/mnt/Personal/Repository/Anarchy-Chess/code/runtime/start-local.sh"
APP_SCRIPT = "/mnt/Personal/Repository/Anarchy-Chess/code/runtime/run-app.sh"

APP_URL = "http://127.0.0.1:8000"

TUNNEL_TIMEOUT = 15
APP_START_TIMEOUT = 30
PROCESS_STOP_TIMEOUT = 2


# ============================================================
# PROCESS MANAGEMENT
# ============================================================

def stop_process(proc, name):
    """Stop a process group gracefully, then force-kill it."""

    if proc is None or proc.poll() is not None:
        return

    print(f"Stopping {name}...")

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGINT)

        try:
            proc.wait(timeout=PROCESS_STOP_TIMEOUT)

        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass

            try:
                proc.wait(timeout=PROCESS_STOP_TIMEOUT)
            except subprocess.TimeoutExpired:
                print(f"Warning: Could not confirm that {name} stopped.")

    except ProcessLookupError:
        pass

    except Exception as exc:
        print(f"Error stopping {name}: {exc}")

        try:
            proc.kill()
            proc.wait(timeout=PROCESS_STOP_TIMEOUT)
        except Exception:
            pass


# ============================================================
# APPLICATION READINESS CHECK
# ============================================================

def wait_for_app():
    """Wait until the application responds on localhost:8000."""

    print(f"Waiting for application at {APP_URL}...")

    deadline = time.monotonic() + APP_START_TIMEOUT

    while time.monotonic() < deadline:

        try:
            request = urllib.request.Request(
                APP_URL,
                method="GET"
            )

            with urllib.request.urlopen(
                request,
                timeout=2
            ) as response:

                print(
                    f"Application is responding "
                    f"(HTTP {response.status})."
                )
                return True

        except urllib.error.HTTPError as exc:
            # HTTP errors such as 404 still prove that an HTTP
            # server is responding on the expected port.
            print(
                f"Application is responding "
                f"(HTTP {exc.code})."
            )
            return True

        except Exception:
            time.sleep(1)

    print(
        f"\nERROR: Application did not respond at {APP_URL} "
        f"within {APP_START_TIMEOUT} seconds."
    )

    print("Check the application's configured port and startup.")

    return False


# ============================================================
# CLOUDFLARE TUNNEL
# ============================================================

def start_tunnel():
    """Start Cloudflare Tunnel and extract its public URL."""

    print("\nInitializing Cloudflare Tunnel...")

    try:
        tunnel_proc = subprocess.Popen(
            ["/bin/bash", TUNNEL_SCRIPT],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True
        )

    except Exception as exc:
        print(f"Error starting Cloudflare Tunnel: {exc}")
        return None, None

    url = None
    deadline = time.monotonic() + TUNNEL_TIMEOUT

    try:
        with selectors.DefaultSelector() as selector:

            selector.register(
                tunnel_proc.stdout,
                selectors.EVENT_READ
            )

            while time.monotonic() < deadline:

                if tunnel_proc.poll() is not None:
                    break

                remaining = deadline - time.monotonic()

                events = selector.select(
                    timeout=min(0.2, remaining)
                )

                if not events:
                    continue

                for key, _ in events:

                    line = key.fileobj.readline()

                    if not line:
                        continue

                    match = re.search(
                        r'https://[a-zA-Z0-9.-]+\.trycloudflare\.com',
                        line
                    )

                    if match:
                        url = match.group(0)
                        break

                if url:
                    break

    except Exception as exc:
        print(f"Error reading Cloudflare output: {exc}")

    if url:
        print(f"\nWebsite: {url}\n")
    else:
        print("Warning: Could not detect Cloudflare Tunnel URL.")

    return tunnel_proc, url


# ============================================================
# ANARCHY CHESS APPLICATION
# ============================================================

def start_app():
    """Start Anarchy Chess with stdout and stderr suppressed."""

    print("Starting Anarchy Chess...")

    try:
        proc = subprocess.Popen(
            ["/bin/bash", APP_SCRIPT],
            cwd=os.path.dirname(APP_SCRIPT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True
        )

        print("Application process launched.")

        return proc

    except Exception as exc:
        print(f"Error starting Anarchy Chess: {exc}")
        return None


# ============================================================
# MAIN PROGRAM
# ============================================================

def main():

    tunnel_proc = None
    app_proc = None

    try:
        while True:

            print("\nStarting Anarchy Chess...\n")

            # Start the application first.
            app_proc = start_app()

            if app_proc is None:
                print("ERROR: Failed to launch the application.")
                break

            # Verify that the application is reachable.
            if not wait_for_app():

                stop_process(app_proc, "Anarchy Chess")
                app_proc = None

                print("\n[R] Retry  [E] Exit")

                choice = input("\nEnter choice: ").strip().upper()

                if choice == "R":
                    continue

                break

            # Start the tunnel only after the application responds.
            if tunnel_proc is None or tunnel_proc.poll() is not None:
                tunnel_proc, tunnel_url = start_tunnel()

            else:
                tunnel_url = None

            if tunnel_url:
                print(f"\nWebsite: {tunnel_url}")
            elif tunnel_proc is None:
                print("WARNING: Cloudflare Tunnel failed to start.")

            print(f"Local application: {APP_URL}")
            print("\n[R] Restart  [E] Exit")

            while True:

                try:
                    choice = input("\nEnter choice: ").strip().upper()

                except EOFError:
                    print("\nInput closed. Exiting.")
                    return

                if choice == "R":

                    stop_process(app_proc, "Anarchy Chess")
                    app_proc = None

                    print("\nRestarting application...\n")
                    break

                elif choice == "E":

                    print("Exiting.")
                    return

                else:
                    print("Invalid input. Enter R or E.")

    except KeyboardInterrupt:
        print("\nInterrupted by user.")

    finally:
        stop_process(app_proc, "Anarchy Chess")
        stop_process(tunnel_proc, "Cloudflare Tunnel")

        print("Cleanup complete.")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
