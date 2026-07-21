from flask import Flask

from app import config
from app.extensions import celery_init_app, socketio


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)

    redis_config = config.get_app_config()["redis"]
    app.config["CELERY"] = {
        "broker_url": redis_config["celery_broker_url"],
        "result_backend": redis_config["celery_result_backend_url"],
        "worker_hijack_root_logger": False,
    }
    celery_init_app(app)

    from app.web import web_bp
    from app.api import api_bp

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    socketio.init_app(app, async_mode="gevent")

    return app
