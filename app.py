"""
SlideGrab Vercel Entrypoint: Exposes top-level 'app' for Vercel deployment.
For the interactive Streamlit UI with review grid, run:
    streamlit run streamlit_app.py
"""
from api.index import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
