"""Errores de dominio de la API.

`ApiError` permite que la capa de servicios comunique fallas de negocio sin
conocer detalles de HTTP. El manejador registrado en la factory traduce la
excepción a una respuesta JSON uniforme.
"""


class ApiError(Exception):
    """Error controlado que se traduce a una respuesta JSON de la API."""

    def __init__(self, message, status_code=400, fields=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.fields = fields

    def to_dict(self):
        payload = {"error": self.message}
        if self.fields is not None:
            payload["fields"] = self.fields
        return payload


def register_error_handlers(app):
    """Registra los manejadores de error de la aplicación."""

    from flask import jsonify

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return jsonify(error.to_dict()), error.status_code

    @app.errorhandler(404)
    def handle_not_found(_error):
        return jsonify({"error": "Resource not found"}), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(_error):
        return jsonify({"error": "Method not allowed"}), 405

    @app.errorhandler(500)
    def handle_internal_error(_error):
        return jsonify({"error": "Internal server error"}), 500

    return app
