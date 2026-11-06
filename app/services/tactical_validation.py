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


def point(value):
    if not isinstance(value, list) or len(value) != 2:
        invalid('A point must have two normalized coordinates')
    if any(type(n) not in (int, float) or not math.isfinite(n) or not 0 <= n <= 1 for n in value):
        invalid('Coordinates must be finite numbers between 0 and 1')
    return value


def object_keys(value, keys):
    if not isinstance(value, dict) or set(value) - set(keys):
        invalid('Unknown tactical fields')


def sequence(value, limit):
    if not isinstance(value, list) or len(value) > limit:
        invalid('Invalid collection size')
    return value


def document(raw, player_ids, grenade_ids):
    object_keys(raw, ('schema_version', 'elements', 'steps', 'assignments', 'notes'))
    if type(raw.get('schema_version')) is not int or raw['schema_version'] != 1:
        invalid('Unsupported tactical schema version')
    elements = sequence(raw.get('elements', []), 300)
    ids = set()
    for item in elements:
        object_keys(item, ('id', 'kind', 'marker', 'points', 'text', 'user_id'))
        eid = text(item.get('id'), 80)
        if not eid or eid in ids:
            invalid('Element identifiers must be unique')
        ids.add(eid)
        kind = item.get('kind')
        if kind not in ('marker', 'line', 'arrow', 'path', 'area', 'text'):
            invalid('Unknown drawing kind')
        points = sequence(item.get('points'), 100)
        minimum = 3 if kind == 'area' else 1 if kind in ('marker', 'text') else 2
        if len(points) < minimum or (kind in ('marker', 'text') and len(points) != 1):
            invalid('Invalid number of points')
        for value in points:
            point(value)
        if kind == 'marker' and item.get('marker') not in MARKERS:
            invalid('Unknown marker')
        text(item.get('text', ''), 500)
        if item.get('user_id') is not None and (type(item['user_id']) is not int or item['user_id'] not in player_ids):
            invalid('Player must be a starter in the selected lineup')
    assignments = sequence(raw.get('assignments', []), 5)
    assigned = set()
    for item in assignments:
        object_keys(item, ('user_id', 'position', 'objective', 'responsibility', 'grenade_ids', 'order'))
        uid = item.get('user_id')
        if type(uid) is not int or uid not in player_ids or uid in assigned:
            invalid('Invalid or duplicate assigned starter')
        assigned.add(uid)
        point(item.get('position'))
        text(item.get('objective', ''), 500)
        text(item.get('responsibility', ''), 1000)
        _references(item.get('grenade_ids', []), grenade_ids)
        if type(item.get('order')) is not int or not 1 <= item['order'] <= 5:
            invalid('Invalid participation order')
    steps = sequence(raw.get('steps', []), 50)
    for index, step in enumerate(steps):
        object_keys(step, ('title', 'description', 'order', 'user_ids', 'actions', 'element_ids', 'grenade_ids'))
        if not text(step.get('title'), 160) or step.get('order') != index + 1:
            invalid('Steps must have a title and consecutive order')
        text(step.get('description', ''), 2000)
        text(step.get('actions', ''), 2000)
        _references(step.get('user_ids', []), player_ids)
        _references(step.get('element_ids', []), ids)
        _references(step.get('grenade_ids', []), grenade_ids)
    text(raw.get('notes', ''))
    return raw


def _references(values, allowed):
    sequence(values, 300)
    if any(not isinstance(value, (str, int)) or isinstance(value, bool) or value not in allowed for value in values):
        invalid('Invalid tactical resource reference')
