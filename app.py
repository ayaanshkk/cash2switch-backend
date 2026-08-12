"""Render/Gunicorn entrypoint for the Flask backend."""

from backend.app import create_app
from backend.routes.crm_routes import get_renewal_email_logs, get_renewal_email_logs_summary

app = create_app()


@app.route("/__entrypoint-build-check", methods=["GET"])
def entrypoint_build_check():
    return {"entrypoint": "root-app.py", "email_logs_routes": True}, 200


app.add_url_rule(
    "/api/entrypoint/renewal-email-logs",
    "entrypoint_renewal_email_logs",
    get_renewal_email_logs,
    methods=["GET"],
)
app.add_url_rule(
    "/api/entrypoint/renewal-email-logs/summary",
    "entrypoint_renewal_email_logs_summary",
    get_renewal_email_logs_summary,
    methods=["GET"],
)


if __name__ == "__main__":
    app.run()
