from copy import deepcopy


def strategy_payload(item, *, member_ids=None, grenade_ids=None, can_edit=False):
    document = deepcopy(item.document)
    assigned = {a['user_id'] for a in document.get('assignments', [])}
    assigned.update(e['user_id'] for e in document.get('elements', []) if e.get('user_id'))
    for step in document.get('steps', []):
        assigned.update(step.get('user_ids', []))
    referenced_grenades = {gid for entry in document.get('assignments', []) + document.get('steps', []) for gid in entry.get('grenade_ids', [])}
    return {'id': item.id, 'team_id': item.team_id, 'map_id': item.map_id,
            'lineup_id': item.lineup_id, 'author_id': item.author_id, 'name': item.name,
            'description': item.description, 'side': item.side, 'category': item.category,
            'status': item.status, 'version': item.version, 'document': document,
            'created_at': item.created_at.isoformat(), 'updated_at': item.updated_at.isoformat(),
            'needs_review': sorted(assigned - member_ids) if member_ids is not None else [],
            'needs_resource_review': sorted(referenced_grenades - grenade_ids) if grenade_ids is not None else [],
            'permissions': {'can_edit': can_edit, 'can_delete': can_edit}}
