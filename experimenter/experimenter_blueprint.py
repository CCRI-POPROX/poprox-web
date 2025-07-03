from flask import Blueprint, render_template

from util.auth import auth

exp = Blueprint("experimenter", __name__, template_folder="templates", url_prefix="/dash")


## EXPERIMENTER ROUTING


@exp.route("/")
@auth.requires_experimenter
def expt_home():
    return render_template(
        "experimenter_home.html", experiments=auth.get_account_experiments(), teams=auth.get_account_teams()
    )


## EXPERIMENT SPECIFIC TASKS and endpoints


@exp.route("/expt/<experiment_id>")
@auth.requires_experiment_team
def expt_dashboard(experiment_id):
    return render_template("experiment_dashboard.html", experiment=auth.get_account_experiments()[experiment_id])


## TEAM SPECIFIC TASKS and endpoints


@exp.route("/team/<team_id>")
@auth.requires_team_member
def team_dashboard(team_id):
    return render_template(
        "team_dashboard.html",
    )
