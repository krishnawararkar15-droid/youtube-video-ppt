"""
SlideGrab Vercel Entrypoint: Exposes top-level 'app', 'application', and 'handler' variables.
For the interactive Streamlit UI with review grid, run:
    streamlit run streamlit_app.py
"""
import os
import re
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify

# Import the pre-configured app with catch-all routing
from api.index import app, application, handler, check_video, HTML_TEMPLATE

# Explicitly ensure catch-all route is also registered directly on app
@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def root_catch_all(path):
    if path.endswith("check"):
        return check_video()
    return render_template_string(HTML_TEMPLATE)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
