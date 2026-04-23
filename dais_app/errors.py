from flask import jsonify


class AppError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def register_error_handlers(app):
    @app.errorhandler(AppError)
    def handle_app_error(err: AppError):
        return jsonify({"detail": err.message}), err.status_code

    @app.errorhandler(Exception)
    def handle_unexpected_error(_err: Exception):
        return jsonify({"detail": "Unexpected server error."}), 500
