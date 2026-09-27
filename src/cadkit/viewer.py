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

## Viewer ports are explicit

Several sessions can run at once and each can replace the scene on a shared
viewer. `show` therefore only uses an explicit port or CAD_VIEWER_PORT.
`free_port` chooses an unused private-range port for a disposable viewer;
long-lived services should choose and document their own port outside CadKit.
"""
import os
import json
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import fcntl

HOST = "127.0.0.1"
PORT_RANGE = range(49152, 49200)
STARTING_TTL = 30.0


def _registry_path():
    """The per-user, per-login viewer registry.

    XDG_RUNTIME_DIR is intentionally preferred: viewer reservations describe
    live processes, not configuration that should survive a reboot. A stable
    XDG state directory is the fallback for environments without it.
    """
    root = (
        os.environ.get("XDG_RUNTIME_DIR")
        or os.environ.get("XDG_STATE_HOME")
        or str(Path.home() / ".local" / "state")
    )
    return Path(root) / "cadkit" / "viewers.json"


@contextmanager
def _registry():
    """Yield the viewer map under an exclusive, atomically-written lock."""
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                viewers = data.get("viewers", {})
            except (FileNotFoundError, json.JSONDecodeError):
                viewers = {}
            yield viewers
            with tempfile.NamedTemporaryFile(
                "w", dir=path.parent, encoding="utf-8", delete=False
            ) as tmp:
                json.dump({"viewers": viewers}, tmp, indent=2, sort_keys=True)
                tmp.write("\n")
            Path(tmp.name).replace(path)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _prune(viewers):
    """Remove entries whose server disappeared or never finished starting."""
    now = time.time()
    for key, entry in list(viewers.items()):
        port = int(key)
        if is_listening(port):
            continue
        if entry.get("state") == "starting" and now - entry["updated"] < STARTING_TTL:
            continue
        del viewers[key]


def _viewer_name(name=None):
    return name or os.environ.get("CAD_VIEWER_NAME") or f"{socket.gethostname()}:{os.getpid()}"


def _reserve(port, name):
    """Atomically reserve an idle port for a viewer that is about to start."""
    with _registry() as viewers:
        _prune(viewers)
        key = str(port)
        if key in viewers or is_listening(port):
            return False
        viewers[key] = {
            "name": name,
            "pid": None,
            "state": "starting",
            "updated": time.time(),
        }
        return True


def _mark_running(port, name):
    """Record the foreground server process that now owns `port`."""
    with _registry() as viewers:
        viewers[str(port)] = {
            "name": name,
            "pid": os.getpid(),
            "state": "running",
            "updated": time.time(),
        }


def _release(port):
    """Release a registry entry after a server exits or fails to start."""
    with _registry() as viewers:
        viewers.pop(str(port), None)


def registered_viewers():
    """Live CadKit viewers as ``{port: {name, pid, state}}``."""
    with _registry() as viewers:
        _prune(viewers)
        return {int(port): entry.copy() for port, entry in viewers.items()}


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


def free_port(ports=PORT_RANGE, host=HOST):
    """An idle port in `ports`, suitable for a disposable viewer."""
    reserved = registered_viewers()
    for port in ports:
        if port not in reserved and not is_listening(port, host):
            return port
    raise RuntimeError(f"no free port in {ports.start}..{ports.stop - 1}")


def serve(port=None, name=None, open_window=True, wait=25.0, python=None):
    """Start a viewer of our own and optionally open a window on it.

    Returns (port, url). A port already serving is returned as-is rather than
    started twice.
    """
    name = _viewer_name(name)
    candidates = (port,) if port is not None else PORT_RANGE
    for candidate in candidates:
        if is_listening(candidate):
            if port is not None:
                return candidate, f"http://{HOST}:{candidate}/"
            continue
        if _reserve(candidate, name):
            port = candidate
            break
    else:
        if port is not None:
            raise RuntimeError(f"viewer port {port} is already reserved")
        raise RuntimeError(f"no free port in {PORT_RANGE.start}..{PORT_RANGE.stop - 1}")

    python = python or sys.executable
    try:
        subprocess.Popen(
            [python, "-m", "cadkit.viewer", "--server", "--host", HOST,
             "--port", str(port), "--name", name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        _release(port)
        raise
    deadline = time.time() + wait
    while time.time() < deadline:
        if is_listening(port):
            break
        time.sleep(0.25)
    else:
        _release(port)
        raise RuntimeError(f"viewer did not come up on {port} within {wait:g}s")

    url = f"http://{HOST}:{port}/"
    if open_window:
        open_viewer_window(url)
    return port, url


def open_viewer_window(url):
    """Open a running viewer in the platform browser, if possible."""
    import webbrowser

    return webbrowser.open(url)


def _server(port, name):
    """Run OCP-VSCode in the foreground with CadKit's generic UI defaults."""
    from ocp_vscode import standalone
    from ocp_vscode.__main__ import main

    # These are viewer ergonomics, not a project's model behaviour. Keeping
    # them here lets every project use the same unobtrusive starting window.
    standalone.INIT = (
        'onload="showViewer(); window.viewer.showToolsPanel(false); '
        'window.viewer.showInfoPanel(false);"'
    )
    _mark_running(port, name)
    try:
        main()
    finally:
        _release(port)


def show(obj, name=None, port=None, quiet=False, clear=True,
         reset_camera=None, options=None, **style):
    """Push `obj` to a viewer if one is there; otherwise say so and move on.

    `port` pins a specific viewer. Without it, only CAD_VIEWER_PORT is used;
    the function never searches for an arbitrary listening viewer because that
    could belong to another session. `serve()` and the command-line helper
    print the environment assignment needed by later part builds.

    Returns True if the object was sent, False if nothing was listening. It
    does not raise for an absent viewer: see the module docstring.
    """
    port = port or os.environ.get("CAD_VIEWER_PORT")
    port = int(port) if port else None

    if port is None or not is_listening(port):
        if not quiet:
            print("viewer       none listening -- not shown "
                  "(cadkit.viewer.serve() starts one)", file=sys.stderr)
        return False

    from ocp_vscode import set_port, show_object      # imported only if used
    set_port(port)
    # `options=` accepts OCP-VSCode's familiar display dictionary.  Keyword
    # styles remain convenient for new callers, and take precedence when both
    # forms are supplied.
    display_options = {**(options or {}), **style}
    kwargs = {
        "name": name,
        "options": display_options or None,
        "clear": clear,
    }
    if reset_camera is not None:
        if reset_camera == "reset":
            from ocp_vscode import Camera
            reset_camera = Camera.RESET
        kwargs["reset_camera"] = reset_camera
    show_object(obj, **kwargs)
    if not quiet:
        print(f"viewer       shown on {port}", file=sys.stderr)
    return True


def _cli(argv=None):
    """`python -m cadkit.viewer [--port N] [--no-window]` -- start a viewer."""
    import argparse

    p = argparse.ArgumentParser(description="Start an OCP viewer on a free port.")
    p.add_argument("--port", type=int, default=None,
                   help="port to use (default: the first idle private-range port)")
    p.add_argument("--name", default=None,
                   help="label recorded for this viewer (default: CAD_VIEWER_NAME)")
    p.add_argument("--no-window", action="store_true", help="server only")
    p.add_argument("--status", action="store_true",
                   help="list which viewer ports are up, and who owns them")
    args = p.parse_args(argv)

    if args.status:
        for port, entry in sorted(registered_viewers().items()):
            print(f"{port}  {entry['state']:8s}  {entry['name']}  pid={entry['pid']}")
        return 0

    port, url = serve(port=args.port, name=args.name, open_window=not args.no_window)
    print(f"viewer on {url}")
    print(f"export CAD_VIEWER_PORT={port}")
    return 0


if __name__ == "__main__":
    if "--server" in sys.argv:
        server = __import__("argparse").ArgumentParser(add_help=False)
        server.add_argument("--server", action="store_true")
        server.add_argument("--host", default=HOST)
        server.add_argument("--port", type=int, required=True)
        server.add_argument("--name", default=None)
        args = server.parse_args()
        sys.argv = [sys.argv[0], "--host", args.host, "--port", str(args.port)]
        _server(args.port, _viewer_name(args.name))
    else:
        raise SystemExit(_cli())
