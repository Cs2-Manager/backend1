from flask import Blueprint, jsonify, request
from app.security import jwt_required
from app.services import tactical_service as service

tactics_bp = Blueprint('tactics', __name__, url_prefix='/api/teams/<int:team_id>')


@tactics_bp.get('/map-resources')
@jwt_required()
def resources(user, team_id):
    from app.services.map_statistics_service import resources
    return jsonify(resources=resources(user, team_id))


@tactics_bp.get('/maps/<int:map_id>/statistics')
@jwt_required()
def statistics(user, team_id, map_id):
    from app.services.map_statistics_service import statistics
    return jsonify(statistics(user, team_id, map_id))


@tactics_bp.get('/strategies')
@jwt_required()
def listing(user, team_id):
    return jsonify(strategies=service.listing(user, team_id, request.args))


@tactics_bp.post('/strategies')
@jwt_required()
def create(user, team_id):
    return jsonify(strategy=service.save(user, team_id, request.get_json(silent=True) or {})), 201


@tactics_bp.get('/strategies/<int:sid>')
@jwt_required()
def detail(user, team_id, sid):
    return jsonify(strategy=service.payload(user, service.get(user, team_id, sid)))


@tactics_bp.put('/strategies/<int:sid>')
@jwt_required()
def update(user, team_id, sid):
    return jsonify(strategy=service.save(user, team_id, request.get_json(silent=True) or {}, sid))


@tactics_bp.delete('/strategies/<int:sid>')
@jwt_required()
def delete(user, team_id, sid):
    service.delete(user, team_id, sid, (request.get_json(silent=True) or {}).get('version'))
    return '', 204


@tactics_bp.post('/strategies/<int:sid>/duplicate')
@jwt_required()
def duplicate(user, team_id, sid):
    return jsonify(strategy=service.duplicate(user, team_id, sid)), 201


@tactics_bp.get('/strategies/<int:sid>/revisions')
@jwt_required()
def revisions(user, team_id, sid):
    return jsonify(revisions=service.revisions(user, team_id, sid))


@tactics_bp.post('/strategies/<int:sid>/restore/<int:version>')
@jwt_required()
def restore(user, team_id, sid, version):
    return jsonify(strategy=service.restore(user, team_id, sid, version, (request.get_json(silent=True) or {}).get('version')))


@tactics_bp.route('/maps/<int:map_id>/preparation', methods=['GET', 'PUT'])
@jwt_required()
def preparation(user, team_id, map_id):
    data = (request.get_json(silent=True) or {}) if request.method == 'PUT' else None
    return jsonify(preparation=service.preparation(user, team_id, map_id, data))
