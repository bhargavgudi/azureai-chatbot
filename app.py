from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from azure_agent import chat

app = FastAPI()


@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Azure Infrastructure Assistant</title>
    </head>
    <body>
        <h1>Azure Infrastructure Assistant</h1>
        <p>Application is running.</p>
    </body>
    </html>
    """


@app.get("/health")
def health():
    return {
        "status": "ok"
    }