from celery import Celery, Task
from flask import Flask
from flask_socketio import SocketIO

socketio = SocketIO()


def celery_init_app(app: Flask) -> Celery:
    """Create a Celery app whose tasks run in the Flask app context."""

    class FlaskTask(Task):
        def __call__(self, *args: object, **kwargs: object) -> object:
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    celery_app.config_from_object(app.config["CELERY"])
    celery_app.set_default()  # Task modules can use Celery's @shared_task.
    app.extensions["celery"] = celery_app
    return celery_app
