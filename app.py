import os
from functools import wraps
from flask import Flask, jsonify, request

app = Flask(__name__)
API_KEY = os.environ.get("ADMIN_API_KEY", "")

def require_api_key(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not API_KEY:
            return jsonify({"ok": False, "error": "ADMIN_API_KEY is not configured"}), 503
        if request.headers.get("Authorization") != f"Bearer {API_KEY}":
            return jsonify({"ok": False, "error": "Unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapped

@app.get("/")
def index():
    return jsonify({"service": "Personal Bot Control API", "api_status": "online",
                    "telegram_bot_connected": False})

@app.get("/health")
def health():
    return jsonify({"ok": True, "api_status": "online"})

@app.get("/admin/status")
@require_api_key
def admin_status():
    # API process status only; no scanner control or scanner-result access.
    return jsonify({"ok": True, "api_status": "online",
                    "telegram_bot_connection": "not_configured"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
