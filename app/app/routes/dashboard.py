from flask import Blueprint, jsonify

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


@dashboard_bp.route("", methods=["GET"])
def get_dashboard():
    return jsonify({"dashboard": {"status": "ok", "data": {}}}), 200
