from flask import Flask

from .config import Config
from .errors import register_error_handlers
from .blueprints.api.routes import api_bp
from .blueprints.web.routes import web_bp


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config)

    register_error_handlers(app)
    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    return app
