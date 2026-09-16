import os
import json
from workers import wsgi, WorkerEntrypoint, Response
from app import create_app

app = create_app('production')

class Default(WorkerEntrypoint):
    async def fetch(self, request):
        try:
            if hasattr(self.env, "HYPERDRIVE"):
                app.extensions["hyperdrive"] = self.env.HYPERDRIVE
            return await wsgi.fetch(app, request, self.env)
        except Exception as exc:
            accept = request.headers.get("accept", "") if hasattr(request, "headers") else ""
            if "application/json" in accept:
                return Response(
                    json.dumps({
                        "status": "error",
                        "error": "Oops! Something went wrong",
                        "message": "We ran into an unexpected issue. Please retry.",
                        "retry_after": 5
                    }),
                    status=500,
                    headers={"content-type": "application/json"}
                )
            html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Oops! Something went wrong - Anvaya Vistara</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f8fafc; color: #0f172a; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }
    .card { background: #fff; padding: 36px 28px; border-radius: 18px; box-shadow: 0 12px 36px rgba(0,0,0,0.08); max-width: 420px; width: 100%; text-align: center; border-top: 4px solid #0284c7; }
    .icon { font-size: 44px; margin-bottom: 14px; }
    h2 { font-size: 22px; font-weight: 700; margin: 0 0 10px; color: #0f172a; }
    p { color: #64748b; font-size: 14px; line-height: 1.5; margin: 0 0 24px; }
    .btn { background: #0284c7; color: #fff; border: none; padding: 12px 24px; border-radius: 10px; font-weight: 700; cursor: pointer; text-decoration: none; display: inline-block; font-size: 15px; transition: background 0.15s; }
    .btn:hover { background: #0369a1; }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">⚠️</div>
    <h2>Oops! Something went wrong</h2>
    <p>We encountered an unexpected problem connecting to the application. Tap below to restart.</p>
    <button class="btn" onclick="window.location.href='/'">&#128260; Restart App</button>
  </div>
</body>
</html>"""
            return Response(html, status=200, headers={"content-type": "text/html; charset=utf-8"})
