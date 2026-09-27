# Author: Claude (Opus 5)
# Co-Author: Brendan Fennell
"""Launch a viewer, find one, or carry on without one.

## The rule this module exists to enforce

**Building a model must not require a viewer.** A part script that raises, or
worse hangs, because nothing is listening on a port turns "regenerate this
solid" into "first go and start a GUI", which is a human interaction charged
for every headless run, every agent, every CI-ish loop.

So `show` never raises for the absence of a viewer. It reports that it found
none and returns False, and the caller carries on exporting its STEP. Viewing
is something you opt into, not a dependency you inherit.

## Ports are contended on this machine

Several agent sessions run at once and each pushes to whatever port it was
told about, silently replacing whatever scene was there. Agents have
screenshotted each other's models believing them their own. `free_port` skips
the ports already spoken for and probes the rest, so a session can take one
that is genuinely idle instead of trusting a number copied out of a document.
"""
import os
import socket
import subprocess
import sys
import time

HOST = "127.0.0.1"
PORT_RANGE = range(3939, 3970)

# Ports with a standing owner. Not a lock -- nothing enforces this -- but
# taking one of them means fighting that owner for the window.
CLAIMED = {
    3939: "Aquarium (aquarium-viewer.service)",
    3940: "Oil_Shelf (./viewer)",
    3941: "Oil_Shelf (./viewer_full)",
}


def is_listening(port, host=HOST, timeout=0.25):
    """True if something already accepts connections there."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def find_viewer(ports=PORT_RANGE, host=HOST):
    """The first port with a viewer already on it, or None."""
    for port in ports:
        if is_listening(port, host):
            return port
    return None


def free_port(ports=PORT_RANGE, host=HOST, avoid_claimed=True):
    """An idle port, skipping those with a standing owner."""
    for port in ports:
        if avoid_claimed and port in CLAIMED:
            continue
        if not is_listening(port, host):
            return port
    raise RuntimeError(f"no free port in {ports.start}..{ports.stop - 1}")


def serve(port=None, open_window=True, wait=25.0, python=None):
    """Start a viewer of our own and optionally open a window on it.

    Returns (port, url). A port already serving is returned as-is rather than
    started twice.
    """
    port = port or free_port()
    if is_listening(port):
        return port, f"http://{HOST}:{port}/"

    python = python or sys.executable
    subprocess.Popen(
        [python, "-m", "ocp_vscode", "--host", HOST, "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.time() + wait
    while time.time() < deadline:
        if is_listening(port):
            break
        time.sleep(0.25)
    else:
        raise RuntimeError(f"viewer did not come up on {port} within {wait:g}s")

    url = f"http://{HOST}:{port}/"
    if open_window:
        open_viewer_window(url)
    return port, url


def open_viewer_window(url):
    """Open a desktop window on a running viewer, if we can. Never fatal."""
    for cmd in (["omarchy", "launch", "webapp", url], ["xdg-open", url]):
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return True
        except FileNotFoundError:
            continue
    return False


def show(obj, name=None, port=None, quiet=False, **options):
    """Push `obj` to a viewer if one is there; otherwise say so and move on.

    `port` pins a specific viewer. Without it, CAD_VIEWER_PORT is honoured,
    and failing that the first port with a viewer on it is used -- which on a
    shared machine may be somebody else's. Pin the port when it matters.

    Returns True if the object was sent, False if nothing was listening. It
    does not raise for an absent viewer: see the module docstring.
    """
    port = port or os.environ.get("CAD_VIEWER_PORT")
    port = int(port) if port else find_viewer()

    if port is None or not is_listening(port):
        if not quiet:
            print("viewer       none listening -- not shown "
                  "(cadkit.viewer.serve() starts one)", file=sys.stderr)
        return False

    from ocp_vscode import set_port, show_object      # imported only if used
    set_port(port)
    show_object(obj, name=name, options=options or None, clear=True)
    if not quiet:
        print(f"viewer       shown on {port}", file=sys.stderr)
    return True


def _cli(argv=None):
    """`python -m cadkit.viewer [--port N] [--no-window]` -- start a viewer."""
    import argparse

    p = argparse.ArgumentParser(description="Start an OCP viewer on a free port.")
    p.add_argument("--port", type=int, default=None,
                   help="port to use (default: the first idle unclaimed one)")
    p.add_argument("--no-window", action="store_true", help="server only")
    p.add_argument("--status", action="store_true",
                   help="list which viewer ports are up, and who owns them")
    args = p.parse_args(argv)

    if args.status:
        for port in PORT_RANGE:
            if is_listening(port):
                print(f"{port}  up    {CLAIMED.get(port, '(unclaimed)')}")
        return 0

    port, url = serve(port=args.port, open_window=not args.no_window)
    print(f"viewer on {url}")
    print(f"export CAD_VIEWER_PORT={port}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
