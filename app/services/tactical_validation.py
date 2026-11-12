"""Closed versioned tactical format; all geometry uses normalized coordinates."""
import math
from app.errors import ApiError

CATEGORIES = ('Default', 'Rush', 'Execute', 'Retake', 'Hold', 'Defensive Setup',
              'Aggressive Setup', 'Fake', 'Eco Strategy', 'Anti-Eco', 'Custom')
MARKERS = ('P1', 'P2', 'P3', 'P4', 'P5', 'A', 'B', 'Mid', 'Smoke', 'Flash',
           'Molotov', 'HE', 'Objective', 'Zone', 'Position')


def invalid(message):
    raise ApiError(message, status_code=400)


def text(value, maximum=4000):
    if not isinstance(value, str) or len(value) > maximum:
        invalid('Invalid text or length')
    return value.strip()


def _valid_coordinate(value):
    if type(value) not in (int, float):
        return False
    if not math.isfinite(value):
        return False
    return 0 <= value <= 1


def _all_coordinates(value):
    return all(_valid_coordinate(number) for number in value)


def point(value):
    if not isinstance(value, list) or len(value) != 2:
        invalid('A point must have two normalized coordinates')
    if not _all_coordinates(value):
        invalid('Coordinates must be finite numbers between 0 and 1')
    return value


def object_keys(value, keys):
    if not isinstance(value, dict) or set(value) - set(keys):
        invalid('Unknown tactical fields')


def sequence(value, limit):
    if not isinstance(value, list) or len(value) > limit:
        invalid('Invalid collection size')
    return value


DRAWING_KINDS = ('marker', 'line', 'arrow', 'path', 'area', 'text')
_ELEMENT_KEYS = ('id', 'kind', 'marker', 'points', 'text', 'user_id')
_ASSIGNMENT_KEYS = (
    'user_id',
    'position',
    'objective',
    'responsibility',
    'grenade_ids',
    'order',
)
_STEP_KEYS = (
    'title',
    'description',
    'order',
    'user_ids',
    'actions',
    'element_ids',
    'grenade_ids',
)


def _validate_schema(raw):
    version = raw.get('schema_version')
    if type(version) is not int or version != 1:
        invalid('Unsupported tactical schema version')


def _minimum_points(kind):
    if kind == 'area':
        return 3
    if kind in ('marker', 'text'):
        return 1
    return 2


def _valid_point_count(kind, points):
    if len(points) < _minimum_points(kind):
        return False
    return kind not in ('marker', 'text') or len(points) == 1


def _valid_marker(kind, marker):
    return kind != 'marker' or marker in MARKERS


def _valid_user_reference(user_id, player_ids):
    if user_id is None:
        return True
    return type(user_id) is int and user_id in player_ids


def _element_identity(item, ids):
    object_keys(item, _ELEMENT_KEYS)
    eid = text(item.get('id'), 80)
    if not eid or eid in ids:
        invalid('Element identifiers must be unique')
    return eid


def _element_points(item):
    kind = item.get('kind')
    if kind not in DRAWING_KINDS:
        invalid('Unknown drawing kind')
    points = sequence(item.get('points'), 100)
    if not _valid_point_count(kind, points):
        invalid('Invalid number of points')
    for value in points:
        point(value)
    return kind


def _element_extra(item, kind, player_ids):
    if not _valid_marker(kind, item.get('marker')):
        invalid('Unknown marker')
    text(item.get('text', ''), 500)
    if not _valid_user_reference(item.get('user_id'), player_ids):
        invalid('Player must be a starter in the selected lineup')


def _element(item, ids, player_ids):
    eid = _element_identity(item, ids)
    kind = _element_points(item)
    _element_extra(item, kind, player_ids)
    return eid


def _elements(raw, player_ids):
    elements = sequence(raw.get('elements', []), 300)
    ids = set()
    for item in elements:
        ids.add(_element(item, ids, player_ids))
    return ids


def _assignment_user(item, assigned, player_ids):
    uid = item.get('user_id')
    if type(uid) is not int:
        invalid('Invalid or duplicate assigned starter')
    if uid not in player_ids or uid in assigned:
        invalid('Invalid or duplicate assigned starter')
    return uid


def _assignment(item, assigned, player_ids, grenade_ids):
    object_keys(item, _ASSIGNMENT_KEYS)
    uid = _assignment_user(item, assigned, player_ids)
    point(item.get('position'))
    text(item.get('objective', ''), 500)
    text(item.get('responsibility', ''), 1000)
    _references(item.get('grenade_ids', []), grenade_ids)
    order = item.get('order')
    if type(order) is not int or not 1 <= order <= 5:
        invalid('Invalid participation order')
    assigned.add(uid)


def _assignments(raw, player_ids, grenade_ids):
    assigned = set()
    for item in sequence(raw.get('assignments', []), 5):
        _assignment(item, assigned, player_ids, grenade_ids)


def _step(step, index, player_ids, element_ids, grenade_ids):
    object_keys(step, _STEP_KEYS)
    title = text(step.get('title'), 160)
    if not title or step.get('order') != index + 1:
        invalid('Steps must have a title and consecutive order')
    text(step.get('description', ''), 2000)
    text(step.get('actions', ''), 2000)
    _references(step.get('user_ids', []), player_ids)
    _references(step.get('element_ids', []), element_ids)
    _references(step.get('grenade_ids', []), grenade_ids)


def _steps(raw, player_ids, element_ids, grenade_ids):
    steps = sequence(raw.get('steps', []), 50)
    for index, step in enumerate(steps):
        _step(step, index, player_ids, element_ids, grenade_ids)


def document(raw, player_ids, grenade_ids):
    object_keys(
        raw, ('schema_version', 'elements', 'steps', 'assignments', 'notes')
    )
    _validate_schema(raw)
    element_ids = _elements(raw, player_ids)
    _assignments(raw, player_ids, grenade_ids)
    _steps(raw, player_ids, element_ids, grenade_ids)
    text(raw.get('notes', ''))
    return raw


def _references(values, allowed):
    sequence(values, 300)
    if any(not isinstance(value, (str, int)) or isinstance(value, bool) or value not in allowed for value in values):
        invalid('Invalid tactical resource reference')
