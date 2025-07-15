from os import environ as env
from uuid import uuid4

from flask import Blueprint, redirect, render_template, request, url_for
from flask_httpauth import HTTPBasicAuth
from poprox_storage.aws import DB_ENGINE
from poprox_storage.concepts.experiment import Team
from poprox_storage.repositories.accounts import DbAccountRepository
from poprox_storage.repositories.teams import DbTeamRepository
from sqlalchemy.exc import IntegrityError, InternalError
from werkzeug.security import check_password_hash, generate_password_hash

admin = Blueprint("admin", __name__, template_folder="templates", url_prefix="/admin")
admin_auth = HTTPBasicAuth()

users = {
    "admin": generate_password_hash(env.get("POPROX_WEB_ADMIN_PASS", "admin")),
}


@admin_auth.verify_password
def verify_password(username, password):
    if username in users and check_password_hash(users.get(username), password):
        return username


@admin.get("/")
@admin_auth.login_required
def show():
    error = request.args.get("error")
    return render_template("admin_home.html", error=error)


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
        team_repo.insert_team_membership(team_id, account.account_id)
        conn.commit()
        return redirect(url_for("admin.team_details", team_id=team_id))


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
            accounts = account_repo.fetch_accounts(request.args["account_id]"])
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
