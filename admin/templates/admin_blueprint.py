from os import environ as env

from flask import Blueprint, render_template
from flask_httpauth import HTTPBasicAuth
from poprox_storage.aws import DB_ENGINE
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
    return render_template(
        "admin_edit_team.html",
    )
