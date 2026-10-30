from flask import Blueprint, jsonify

from app.security import jwt_required
from app.services import dashboard_service

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


@dashboard_bp.route("", methods=["GET"])
@jwt_required()
def get_dashboard(_user):
    return jsonify({"dashboard": dashboard_service.get_dashboard()}), 200
