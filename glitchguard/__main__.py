import errno
import sys
import threading
import webbrowser

from . import config, poller, server


def main():
    cfg = config.load()
    engine = poller.Poller()

    port = cfg["port"]
    httpd = None
    for candidate in range(port, port + 20):
        try:
            httpd = server.serve(engine, candidate)
            port = candidate
            break
        except OSError as exc:
            if exc.errno not in (errno.EADDRINUSE, 10048):
                raise
    if httpd is None:
        print("Could not bind a local port in 8765-8785.", file=sys.stderr)
        return 1

    engine.start()
    url = f"http://127.0.0.1:{port}/?t={server.TOKEN}"
    print("GlitchGuard is running.")
    print(f"  {url}")
    print("Close this window to stop.")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
