from webapp import create_app

app = create_app()

if __name__ == "__main__":
    # use_reloader=False: the stat reloader watches every imported module
    # under .venv/site-packages, and with .venv inside iCloud-synced Desktop,
    # background sync touches those files and triggers a restart loop.
    # Restart manually after edits until .venv lives outside iCloud sync.
    app.run(debug=True, port=8000, use_reloader=False)
