"""Render/Gunicorn entrypoint for the Flask backend."""

from backend.app import create_app

app = create_app()


if __name__ == "__main__":
    app.run()
