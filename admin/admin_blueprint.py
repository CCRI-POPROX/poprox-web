import datetime
from os import environ as env

from flask import Blueprint, jsonify, render_template
from flask_httpauth import HTTPBasicAuth
from poprox_storage.aws import SESSION
from poprox_storage.aws.cloudwatch import Cloudwatch
from poprox_storage.repositories.accounts import DbAccountRepository
from werkzeug.security import check_password_hash, generate_password_hash

from db.postgres_db import DB_ENGINE

admin = Blueprint("admin", __name__, template_folder="templates", url_prefix="/admin")
auth = HTTPBasicAuth()

users = {
    "admin": generate_password_hash(env.get("POPROX_WEB_ADMIN_PASS", "admin")),
}


@auth.verify_password
def verify_password(username, password):
    if username in users and check_password_hash(users.get(username), password):
        return username


@admin.route("/")
@auth.login_required
def show():
    return render_template("admin_home.html")


@admin.route("/api/onboarding")
@auth.login_required
def onboarding_dash():
    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(weeks=1)

    status_sequence = ["new_account", "pending_initial_preferences", "pending_onboarding_survey", "onboarding_done"]
    status_stage = ["accounts created", "consented", "filled out topics", "filled out demographics"]
    columns = [
        "date",
        "enroll page hits",
        "enroll form submission",
        "enroll email click",
    ] + status_stage

    cloudwatch = Cloudwatch(SESSION)
    metric_values = cloudwatch.get_metric_daily_count(
        "poprox-web/onboarding",
        ["enroll page hits", "enroll form submission", "enroll email click"],
        start_date,
        end_date,
    )
    metric_values = {k.date(): v for k, v in metric_values.items()}
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)

        accounts = account_repo.fetch_accounts_between(start_date, end_date)
        for account in accounts:
            account_creation_date = account.created_at.date()
            if account_creation_date not in metric_values:
                metric_values[account_creation_date] = {}
            onboarding_location = status_sequence.index(account.status)
            for i in range(onboarding_location + 1):
                stage = status_stage[i]
                metric_values[account_creation_date][stage] = metric_values[account_creation_date].get(stage, 0) + 1

        results = []
        for day, metrics in sorted(list(metric_values.items())):
            metrics["date"] = day
            for metric in columns[1:]:
                metrics[metric] = metrics.get(metric, 0)
            results.append(metrics)
        return jsonify(results)
