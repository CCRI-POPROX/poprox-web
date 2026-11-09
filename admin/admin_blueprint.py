from datetime import date, timedelta
from uuid import uuid4

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_httpauth import HTTPBasicAuth
from poprox_storage.aws import DB_ENGINE
from poprox_storage.concepts.experiment import Team
from poprox_storage.repositories import (
    DbAccountRepository,
    DbDailyStatsRepository,
    DbExperimentRepository,
    DbSubscriptionRepository,
    DbTeamRepository,
)
from sqlalchemy.exc import IntegrityError, InternalError
from werkzeug.security import check_password_hash, generate_password_hash

from util.config import require_secret

admin = Blueprint("admin", __name__, template_folder="templates", url_prefix="/admin")
admin_auth = HTTPBasicAuth()

users = {
    "admin": generate_password_hash(require_secret("POPROX_WEB_ADMIN_PASS", "admin")),
}


@admin_auth.verify_password
def verify_password(username, password):
    if username in users and check_password_hash(users.get(username), password):
        return username


@admin.get("/")
@admin_auth.login_required
def show():
    error = request.args.get("error")

    with DB_ENGINE.connect() as conn:
        experiment_repo = DbExperimentRepository(conn)
        today = date.today()

        active_experiments = experiment_repo.fetch_all_active_experiments(today)

    return render_template(
        "admin_home.html",
        error=error,
        active_experiments=active_experiments,
        today=today,
    )


### DATA API ###
@admin.get("/api/clicks/by_day")
@admin_auth.login_required
def get_clicks_by_day():
    # flag parameter, include as `...&include_all&...` or `...&include_all=True&...`
    include_all = request.args.get("include_all") is not None
    end_text = request.args.get("end")
    start_text = request.args.get("start")

    try:
        end = date.fromisoformat(end_text) if end_text else date.today()
        start = date.fromisoformat(start_text) if start_text else end - timedelta(days=30)
    except ValueError:
        return jsonify({"error": "start and end must be dates like 2026-09-01"}), 400
    
    if end < start:
        
        return jsonify({"error": "start must not be after end"}), 400

    with DB_ENGINE.connect() as conn:
        stats_repo = DbDailyStatsRepository(conn)
        rows = stats_repo.fetch_daily_stats(start, end, include_all)
        return jsonify([row.model_dump(mode="json") for row in rows])

### TEAM MANAGEMENT ###


@admin.get("/team")
@admin_auth.login_required
def team_manage():
    error = request.args.get("error")
    with DB_ENGINE.connect() as conn:
        team_repo = DbTeamRepository(conn)
        teams = team_repo.fetch_teams()
        return render_template("admin_team_management.html", error=error, teams=teams)


@admin.get("/team/<team_id>")
@admin_auth.login_required
def team_details(team_id):
    error = request.args.get("error")

    with DB_ENGINE.connect() as conn:
        team_repo = DbTeamRepository(conn)
        account_repo = DbAccountRepository(conn)
        team = team_repo.fetch_team_by_id(team_id)
        members = account_repo.fetch_accounts(team.members)
        return render_template("admin_edit_team.html", team=team, error=error, members=members)


@admin.post("/team/<team_id>")
@admin_auth.login_required
def edit_team_name(team_id):
    new_name = request.form.get("team_name")
    with DB_ENGINE.connect() as conn:
        team_repo = DbTeamRepository(conn)
        account_repo = DbAccountRepository(conn)

        team = team_repo.fetch_team_by_id(team_id)
        team.team_name = new_name
        team_repo.store_team(team)
        members = account_repo.fetch_accounts(team.members)

        conn.commit()
        return render_template("admin_edit_team.html", team=team, members=members)


@admin.post("/team/<team_id>/members")
@admin_auth.login_required
def add_to_team(team_id):
    email = request.form.get("email", "")
    with DB_ENGINE.connect() as conn:
        team_repo = DbTeamRepository(conn)
        account_repo = DbAccountRepository(conn)
        account = account_repo.fetch_account_by_email(email)
        if account is None:
            return redirect(
                url_for("admin.team_details", team_id=team_id, error=f"No account for email: '{email}' found ")
            )
        try:
            team_repo.insert_team_membership(team_id, account.account_id)
            conn.commit()
            return redirect(url_for("admin.team_details", team_id=team_id))
        except ValueError as e:
            return redirect(url_for("admin.team_details", team_id=team_id, error=str(e)))


@admin.post("/team")
@admin_auth.login_required
def new_team():
    team_name = request.form.get("team_name", "untitled team")
    with DB_ENGINE.connect() as conn:
        team_repo = DbTeamRepository(conn)
        team = Team(team_id=uuid4(), team_name=team_name, members=[])
        team_repo.store_team(team)
        conn.commit()
        return redirect(url_for("admin.team_details", team_id=team.team_id))


### ACCOUNT MANAGEMENT


@admin.get("/account")
@admin_auth.login_required
def account_search():
    accounts = []
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        if request.args.get("account_id"):
            accounts = account_repo.fetch_accounts(request.args["account_id"])
        elif request.args.get("account_email_query"):
            accounts = account_repo.fetch_account_by_email_query(request.args["account_email_query"])

    return render_template("admin_account_management.html", accounts=accounts)


@admin.get("/account/<account_id>")
@admin_auth.login_required
def account_detail(account_id):
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        account = account_repo.fetch_accounts([account_id])
        if len(account) == 0:
            redirect(url_for("admin.account_search", error="account not found"))
        else:
            account = account[0]

    return render_template("admin_account_detail.html", editable=["source", "subsource", "email"], account=account)


@admin.post("/account/<account_id>")
@admin_auth.login_required
def update_account_detail(account_id):
    with DB_ENGINE.connect() as conn:
        account_repo = DbAccountRepository(conn)
        account = account_repo.fetch_accounts([account_id])
        if len(account) == 0:
            redirect(url_for("admin.account_search", error="account not found"))
        else:
            account = account[0]

        if request.form.get("source"):
            account.source = request.form.get("source")
        if request.form.get("subsource"):
            account.subsource = request.form.get("subsource")
        if request.form.get("email"):
            account.email = request.form.get("email")

        try:
            account_repo.store_account(account, commit=False)
            conn.commit()
        except (IntegrityError, InternalError) as err:
            conn.rollback()
            return redirect(
                url_for("admin.account_detail", account_id=account_id, error="update not applied: " + str(err))
            )

    return render_template("admin_account_detail.html", editable=["source", "subsource", "email"], account=account)


@admin.post("/account/<account_id>/force_unsubscribe")
@admin_auth.login_required
def force_unsubscribe(account_id):
    if request.form.get("confirm"):
        try:
            with DB_ENGINE.connect() as conn:
                subscription_repo = DbSubscriptionRepository(conn)
                account_repo = DbAccountRepository(conn)

                subscription_repo.remove_subscription_for_account(account_id)
                account_repo.update_status(account_id, "admin unsubscribe")
                conn.commit()

                return redirect(url_for("admin.account_detail", account_id=account_id, error="unsubbed"))
        except (IntegrityError, InternalError) as err:
            conn.rollback()
            return redirect(
                url_for("admin.account_detail", account_id=account_id, error="update not applied: " + str(err))
            )
    else:
        return redirect(
            url_for("admin.account_detail", account_id=account_id, error="update not applied. you gotta confirm")
        )
