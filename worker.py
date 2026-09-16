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
                        "rate_limited": True,
                        "error": "Too Many Requests",
                        "message": "Maximum 15 requests per 30 seconds allowed. Please wait a moment.",
                        "retry_after": 10
                    }),
                    status=429,
                    headers={"content-type": "application/json", "retry-after": "10"}
                )
            html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Rate Notice - Anvaya Vistara</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f8fafc; color: #0f172a; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }
    .card { background: #fff; padding: 32px 24px; border-radius: 16px; box-shadow: 0 10px 30px rgba(0,0,0,0.08); max-width: 420px; width: 100%; text-align: center; border-top: 4px solid #f59e0b; }
    .icon { font-size: 40px; margin-bottom: 12px; }
    h2 { font-size: 20px; margin: 0 0 8px; }
    p { color: #64748b; font-size: 14px; line-height: 1.5; margin: 0 0 20px; }
    .btn { background: #0284c7; color: #fff; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 600; cursor: pointer; text-decoration: none; display: inline-block; font-size: 14px; }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">⏳</div>
    <h2>Please Wait a Moment</h2>
    <p>Too many requests were received in a short period (Limit: 15 requests per 30s). Please slow down and refresh.</p>
    <button class="btn" onclick="window.location.reload()">Refresh Page</button>
  </div>
</body>
</html>"""
            return Response(html, status=200, headers={"content-type": "text/html; charset=utf-8"})
