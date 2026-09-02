from flask import Blueprint, jsonify

from app.extensions import db

health_bp = Blueprint("health", __name__)


@health_bp.route("/health", methods=["GET"])
def health():
    db_status = "ok"
    status_code = 200

    try:
        db.engine.connect().close()
    except Exception:
        db_status = "error"
        status_code = 503

    return jsonify({"status": "ok", "database": db_status}), status_code
