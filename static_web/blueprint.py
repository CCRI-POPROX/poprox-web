from flask import Blueprint, send_from_directory

static_web = Blueprint("static_web", __name__, template_folder="templates")


@static_web.route("/img/<path:filename>")
def public_img(filename):
    return send_from_directory("static_web/public/img", filename)


@static_web.route("/documents/<path:filename>")
def public_documents(filename):
    return send_from_directory("static_web/public/documents", filename)


@static_web.route("/data/<path:filename>")
def public_data(filename):
    return send_from_directory("static_web/public/data", filename)


@static_web.route("/css/<path:filename>")
def public_css(filename):
    return send_from_directory("static_web/public/css", filename)


@static_web.route("/assets/<path:filename>")
def public_assets(filename):
    return send_from_directory("static_web/public/assets", filename)


@static_web.route("/about")
@static_web.route("/about/")
def about():
    return send_from_directory("static_web/_site/about/", "index.html")


@static_web.route("/contact")
@static_web.route("/contact/")
def contact():
    return send_from_directory("static_web/_site/contact/", "index.html")


@static_web.route("/experimenter")
@static_web.route("/experimenter/")
def experimenter():
    return send_from_directory("static_web/_site/experimenter/", "index.html")


@static_web.route("/newsletter")
@static_web.route("/newsletter/")
def newsletter():
    return send_from_directory("static_web/_site/newsletter/", "index.html")


@static_web.route("/people")
@static_web.route("/people/")
def people():
    return send_from_directory("static_web/_site/people/", "index.html")


@static_web.route("/")
@static_web.route("/home")
@static_web.route("/home/")
def home():
    return send_from_directory("static_web/_site/home/", "index.html")
