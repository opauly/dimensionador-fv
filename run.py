from webapp import create_app

app = create_app()

if __name__ == "__main__":
    # use_reloader=False: the stat reloader watches every imported module
    # under .venv/site-packages, and with .venv inside iCloud-synced Desktop,
    # background sync touches those files and triggers a restart loop.
    # Restart manually after edits until .venv lives outside iCloud sync.
    #
    # threaded=True: PLAN_PHASE20_PROPOSALS_JINJA.md §1.7 relies on "Flask's
    # dev server is threaded by default" to justify running AI calls (bill
    # extraction, tablero parsing) synchronously without freezing the whole
    # app for a second concurrent request/tab. That claim does NOT hold:
    # Werkzeug's own run_simple() signature defaults to threaded=False
    # (checked directly in this venv's installed werkzeug/serving.py, Phase
    # 20 Step 4) — Flask's app.run() just forwards whatever it's given, so
    # without this the dev server handles one request at a time and a slow
    # AI call WOULD hold up a concurrent second tab. Set explicitly so
    # §1.7's mitigation is actually true rather than assumed.
    app.run(debug=True, port=8000, use_reloader=False, threaded=True)
