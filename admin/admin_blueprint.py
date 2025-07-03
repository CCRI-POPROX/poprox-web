from os import environ as env
from uuid import uuid4

from flask import Blueprint, redirect, render_template, request, url_for
from flask_httpauth import HTTPBasicAuth
from poprox_storage.aws import DB_ENGINE
from poprox_storage.concepts.experiment import Team
from poprox_storage.repositories.accounts import DbAccountRepository
from poprox_storage.repositories.teams import DbTeamRepository
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


@admin.route("/")
@admin_auth.login_required
def show():
    error = request.args.get("error")
    with DB_ENGINE.connect() as conn:
        team_repo = DbTeamRepository(conn)
        teams = team_repo.fetch_teams()
        return render_template("admin_home.html", error=error, teams=teams)


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
                url_for("admin.edit_team", team_id=team_id, error=f"No account for email: '{email}' found ")
            )
        team_repo.insert_team_membership(team_id, account.account_id)
        conn.commit()
        return redirect(url_for("admin.edit_team", team_id=team_id))


@admin.post("/team")
@admin_auth.login_required
def new_team():
    team_name = request.form.get("team_name", "untiteled team")
    with DB_ENGINE.connect() as conn:
        team_repo = DbTeamRepository(conn)
        team = Team(team_id=uuid4(), team_name=team_name, members=[])
        team_repo.store_team(team)
        conn.commit()
        return redirect(url_for("admin.edit_team", team_id=team.team_id))
