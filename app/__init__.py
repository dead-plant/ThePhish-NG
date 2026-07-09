from flask import Flask

from app.extensions import socketio


def create_app():
    app = Flask(__name__, static_folder=None)

    from app.web import web_bp
    from app.api import api_bp

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    socketio.init_app(app, async_mode="gevent")

    return app
