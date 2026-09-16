from flask import Flask
from workers import wsgi

app = Flask(__name__)

@app.get("/")
def index():
    return {"message": "Hello from Flask"}

Default = wsgi.entrypoint(app)
