import json

import markdown
from flask import Blueprint, render_template, send_from_directory

static_web = Blueprint("static_web", __name__, template_folder="templates")


@static_web.route("/img/<path:filename>")
def public_img(filename):
    return send_from_directory("static_web/public/img", filename)


@static_web.route("/documents/<path:filename>")
def public_documents(filename):
    return send_from_directory("static_web/public/documents", filename)


@static_web.route("/css/<path:filename>")
def public_css(filename):
    return send_from_directory("static_web/public/css", filename)


@static_web.route("/assets/<path:filename>")
def public_assets(filename):
    return send_from_directory("static_web/public/assets", filename)


@static_web.route("/about")
@static_web.route("/about/")
def about():
    page_content = open("static_web/data/about.md").read()
    content = markdown.markdown(page_content)
    return render_template("markdown_page.html", content=content)


@static_web.route("/contact")
@static_web.route("/contact/")
def contact():
    page_content = open("static_web/data/support.md").read()
    content = markdown.markdown(page_content)
    return render_template("markdown_page.html", content=content)


@static_web.route("/experimenter")
@static_web.route("/experimenter/")
def experimenter():
    page_content = open("static_web/data/researcher.md").read()
    content = markdown.markdown(page_content)
    return render_template("markdown_page.html", content=content)


@static_web.route("/newsletter")
@static_web.route("/newsletter/")
def newsletter():
    page_content = open("static_web/data/subscriber.md").read()
    content = markdown.markdown(page_content)
    return render_template("markdown_page.html", content=content)


@static_web.route("/people")
@static_web.route("/people/")
def people():
    team_info = open("static_web/data/teamInfo.json").read()
    team_info = json.loads(team_info)
    return render_template("people.html", teamInfo=team_info)


@static_web.route("/")
@static_web.route("/home")
@static_web.route("/home/")
def home():
    return render_template("static_home.html")
