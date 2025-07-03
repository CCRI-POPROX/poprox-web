from os import environ as env

from flask import Blueprint, redirect, render_template, request, url_for
from flask_httpauth import HTTPBasicAuth
from poprox_storage.aws import DB_ENGINE
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
    with DB_ENGINE.connect() as conn:
        team_repo = DbTeamRepository(conn)
        teams = team_repo.fetch_teams()
        return render_template("admin_home.html", teams=teams)


@admin.route("/team/<team_id>")
@admin_auth.login_required
def edit_team(team_id):
    with DB_ENGINE.connect() as conn:
        team_repo = DbTeamRepository(conn)
        account_repo = DbAccountRepository(conn)
        team = team_repo.fetch_team_by_id(team_id)
        print(team.members)
        members = account_repo.fetch_accounts(team.members)
        print(members)
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
            return "error, who is that."
        team_repo._insert_team_membership(team_id, account.account_id)
        conn.commit()
        return redirect(url_for("admin.edit_team", team_id=team_id))
