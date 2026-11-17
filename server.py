#!/usr/bin/env python3
"""
Simple zero-dependency HTTP server to preview the News & Intelligence feed.
Serves index.html, feed.json, and provides a trigger to re-run the collector.
"""

import http.server
import socketserver
import os
import sys

PORT = 8000
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

    def do_GET(self):
        if self.path == "/api/db":
            try:
                import sqlite3
                import json
                db_path = os.path.join(DIRECTORY, "news_platform.db")
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;")
                tables = [row[0] for row in cur.fetchall()]
                snapshot = {}
                for table in tables:
                    cur.execute(f"PRAGMA table_info({table});")
                    cols = [{"name": c[1], "type": c[2] or "ANY", "notnull": bool(c[3]), "pk": bool(c[5])} for c in cur.fetchall()]
                    cur.execute(f"SELECT * FROM {table} LIMIT 100;")
                    rows = [dict(r) for r in cur.fetchall()]
                    snapshot[table] = {"columns": cols, "rows": rows, "total_count": len(rows)}
                conn.close()

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(snapshot).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(f'{{"error": "{str(e)}"}}'.encode("utf-8"))
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/collect":
            try:
                import collector
                collector.run_collection()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status": "ok", "message": "Collection complete"}')
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(f'{{"status": "error", "message": "{str(e)}"}}'.encode("utf-8"))
        else:
            self.send_error(404)

if __name__ == "__main__":
    os.chdir(DIRECTORY)
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"[*] News Intelligence Server running at: http://localhost:{PORT}")
        print("    Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping server.")
