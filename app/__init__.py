from flask import Flask

from app import config
from app._version import RELEASE_BASE_URL, __version__
from app.extensions import celery_init_app, socketio


def _release_url_for(version: str) -> str | None:
    if ".dev" in version or "+" in version:
        return None
    return f"{RELEASE_BASE_URL}{version}"


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)

    app_config = config.get_app_config()
    redis_config = app_config["redis"]
    app.config["CELERY"] = {
        "broker_url": redis_config["celery_broker_url"],
        "result_backend": redis_config["celery_result_backend_url"],
        "worker_hijack_root_logger": False,
    }
    celery_init_app(app)

    app.jinja_env.globals.update(
        show_version=app_config["webapp"]["show_version"],
        app_version=__version__,
        release_url=_release_url_for(__version__),
    )

    from app.web import web_bp
    from app.api import api_bp

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    socketio.init_app(app, async_mode="gevent")

    return app
