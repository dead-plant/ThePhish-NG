from flask import render_template

from app.web import web_bp

# The main page
@web_bp.route("/")
def index():
    return render_template("index.html")
