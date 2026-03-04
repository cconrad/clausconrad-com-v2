#!/usr/bin/env python3
"""Local HTTP server with clean URL support (Netlify-style)."""

import argparse
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path


class CleanURLHandler(SimpleHTTPRequestHandler):
    """HTTP handler that resolves clean URLs like Netlify."""

    def do_GET(self):
        path = self.path.split("?")[0].split("#")[0]
        fs_path = Path(self.directory) / path.lstrip("/")

        if fs_path.is_file():
            return super().do_GET()

        if path.endswith("/"):
            index = fs_path / "index.html"
            if index.is_file():
                self.path = path + "index.html"
                return super().do_GET()
            # Fallback: try path.html (e.g., /notes/ → notes.html)
            stripped = path.rstrip("/")
            if stripped:
                html_file = Path(self.directory) / (stripped.lstrip("/") + ".html")
                if html_file.is_file():
                    self.path = stripped + ".html"
                    return super().do_GET()
            self.send_error(404)
            return

        if "." not in Path(path).name:
            html_file = fs_path.with_suffix(".html")
            if html_file.is_file():
                self.path = path + ".html"
                return super().do_GET()

            index = fs_path / "index.html"
            if index.is_file():
                self.send_response(301)
                self.send_header("Location", path + "/")
                self.end_headers()
                return

        self.send_error(404)


def main():
    parser = argparse.ArgumentParser(description="Local server with clean URL support")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    parser.add_argument("--dir", type=str, default=".", help="Directory to serve")
    args = parser.parse_args()

    directory = os.path.abspath(args.dir)
    handler = lambda *a, **kw: CleanURLHandler(*a, directory=directory, **kw)

    server = HTTPServer(("", args.port), handler)
    print(f"Serving {directory} at http://localhost:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()

