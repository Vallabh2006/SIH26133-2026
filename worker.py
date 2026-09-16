import os
from workers import wsgi, WorkerEntrypoint
from app import create_app

app = create_app('production')

class Default(WorkerEntrypoint):
    async def fetch(self, request):
        if hasattr(self.env, "HYPERDRIVE"):
            app.extensions["hyperdrive"] = self.env.HYPERDRIVE
        return await wsgi.fetch(app, request, self.env)
