from flask import Blueprint, render_template

from util.auth import auth

exp = Blueprint("experimenter", __name__, template_folder="templates", url_prefix="/dash")


@exp.route("/")
@auth.requires_experimenter
def expt_home():
    return render_template("experimenter_home.html", experiments=auth.get_account_experiments())


@exp.route("/<experiment_id>")
@auth.requires_experiment_team
def expt_dashboard(experiment_id):
    return render_template("experiment_dashboard.html", experiment=auth.get_account_experiments()[experiment_id])
