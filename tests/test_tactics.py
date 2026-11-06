from copy import deepcopy
import pytest
from app.extensions import db
from app.models import User, Team, TeamMember, Map, TeamLineup, TeamLineupPlayer
from app.security import generate_token


@pytest.fixture()
def tactical(app):
    users = [User(username=f'tactical-{i}', email=f'tactical-{i}@example.com', password_hash='unused', is_admin=i == 7) for i in range(8)]
    db.session.add_all(users)
    db.session.flush()
    team = Team(name='Tactical team', visibility='PUBLIC')
    other = Team(name='Other team', visibility='PRIVATE')
    map_obj = Map(name='Mirage', image_url='https://example.com/radar.png')
    db.session.add_all([team, other, map_obj]); db.session.flush()
    for i in range(6):
        db.session.add(TeamMember(team_id=team.id, user_id=users[i].id, role='CAPTAIN' if i == 0 else 'COACH' if i == 5 else 'PLAYER'))
    db.session.add(TeamMember(team_id=other.id, user_id=users[6].id, role='CAPTAIN'))
    lineup = TeamLineup(team_id=team.id, name='Mirage Main', map_id=map_obj.id, status='ACTIVE')
    db.session.add(lineup); db.session.flush()
    for i in range(5):
        db.session.add(TeamLineupPlayer(lineup_id=lineup.id, user_id=users[i].id, role='IGL' if i == 0 else 'RIFLER', is_starter=True))
    db.session.commit()
    return {'team': team.id, 'other': other.id, 'map': map_obj.id, 'lineup': lineup.id,
            'users': [u.id for u in users], 'headers': [{'Authorization': f'Bearer {generate_token(u)}'} for u in users]}


def strategy_data(t):
    uid = t['users'][1]
    return {'map_id': t['map'], 'lineup_id': t['lineup'], 'name': 'Execute A', 'side': 'T', 'category': 'Execute',
            'document': {'schema_version': 1, 'notes': 'Team only',
                         'elements': [{'id': 'p1', 'kind': 'marker', 'marker': 'P1', 'points': [[.2, .3]], 'user_id': uid}],
                         'assignments': [{'user_id': uid, 'position': [.2, .3], 'objective': 'Site', 'responsibility': 'Entry', 'order': 1, 'grenade_ids': []}],
                         'steps': [{'title': 'Entry', 'order': 1, 'description': '', 'actions': 'Go', 'user_ids': [uid], 'element_ids': ['p1'], 'grenade_ids': []}]}}


def create(client, t):
    result = client.post(f"/api/teams/{t['team']}/strategies", headers=t['headers'][0], json=strategy_data(t))
    assert result.status_code == 201, result.json
    return result.json['strategy']


def test_strategy_roundtrip_versions_and_conflicts(client, tactical):
    t = tactical; s = create(client, t); url = f"/api/teams/{t['team']}/strategies/{s['id']}"; h = t['headers'][0]
    assert client.get(url, headers=t['headers'][1]).json['strategy']['document'] == strategy_data(t)['document']
    saved = client.put(url, headers=h, json={'version': s['version'], 'status': 'PUBLISHED'})
    assert saved.status_code == 200, saved.json
    assert saved.json['strategy']['version'] == 2
    assert client.put(url, headers=h, json={'version': 1, 'name': 'stale'}).status_code == 409
    revisions = client.get(url + '/revisions', headers=h).json['revisions']
    assert revisions[0]['snapshot']['status'] == 'DRAFT'
    restored = client.post(url + '/restore/1', headers=h, json={'version': 2})
    assert restored.status_code == 200, restored.json
    assert restored.json['strategy']['version'] == 3
    assert client.post(url + '/duplicate', headers=h).status_code == 201
    assert client.delete(url, headers=h, json={'version': 3}).status_code == 204
    assert client.get(url, headers=h).status_code == 404


@pytest.mark.parametrize('index,allowed', [(0, True), (5, True), (1, False), (6, False), (7, True)])
def test_tactical_write_matrix(client, tactical, index, allowed):
    t = tactical
    r = client.post(f"/api/teams/{t['team']}/strategies", headers=t['headers'][index], json=strategy_data(t))
    assert r.status_code == (201 if allowed else 403)


def test_private_strategy_in_public_team_and_idor(client, tactical):
    t = tactical; s = create(client, t); url = f"/api/teams/{t['team']}/strategies/{s['id']}"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=t['headers'][6]).status_code == 403
    assert client.get(f"/api/teams/{t['other']}/strategies/{s['id']}", headers=t['headers'][6]).status_code == 404
    for suffix, method in [('', 'PUT'), ('', 'DELETE'), ('/duplicate', 'POST'), ('/restore/1', 'POST')]:
        assert client.open(url + suffix, method=method, headers=t['headers'][1], json={'version': 1}).status_code == 403


@pytest.mark.parametrize('coordinates', [[-1, .5], [1.1, .5], [float('nan'), .5], [float('inf'), .5], [True, .5], [.1], 'pixels'])
def test_invalid_coordinates(client, tactical, coordinates):
    data = strategy_data(tactical); data['document']['elements'][0]['points'] = [coordinates]
    response = client.post(f"/api/teams/{tactical['team']}/strategies", headers=tactical['headers'][0], json=data)
    assert response.status_code == 400


def test_closed_schema_and_cross_team_assignments(client, tactical):
    t = tactical
    for field, value in [('schema_version', 99), ('arbitrary', {}), ('assignments', [{'user_id': t['users'][6]}])]:
        data = strategy_data(t); data['document'][field] = value
        assert client.post(f"/api/teams/{t['team']}/strategies", headers=t['headers'][0], json=data).status_code == 400
    data = strategy_data(t); data['document']['steps'][0]['element_ids'] = ['missing']
    assert client.post(f"/api/teams/{t['team']}/strategies", headers=t['headers'][0], json=data).status_code == 400


@pytest.mark.parametrize('leave', [True, False])
def test_departure_preserves_strategy_and_audits_roster(client, tactical, leave):
    t = tactical; s = create(client, t)
    if leave:
        r = client.post(f"/api/teams/{t['team']}/leave", headers=t['headers'][1])
    else:
        r = client.delete(f"/api/teams/{t['team']}/members/{t['users'][1]}", headers=t['headers'][0])
    assert r.status_code == 204
    saved = client.get(f"/api/teams/{t['team']}/strategies/{s['id']}", headers=t['headers'][0]).json['strategy']
    assert saved['needs_review'] == [t['users'][1]]
    assert saved['document'] == s['document']
    history = client.get(f"/api/teams/{t['team']}/lineups/{t['lineup']}/history", headers=t['headers'][0]).json['history']
    assert history[0]['action'] == 'MEMBER_DEPARTED'
    assert len(history[0]['before']['players']) == 5
    assert len(history[0]['after']['players']) == 4


def test_map_lineups_history_comparison_and_delete(client, tactical):
    t = tactical; h = t['headers'][0]; base = f"/api/teams/{t['team']}/lineups"
    r = client.post(base, headers=h, json={'name': 'Map draft', 'map_id': t['map'], 'notes': 'Test'})
    assert r.status_code == 201
    lid = r.json['lineup']['id']
    assert client.post(f'{base}/{lid}/activate', headers=h).status_code == 400
    assert client.post(f"{base}/{t['lineup']}/primary", headers=h).status_code == 400
    comparison = client.get(f"{base}/{t['lineup']}/compare/{lid}", headers=h)
    assert len(comparison.json['removed']) == 5
    assert client.put(f'{base}/{lid}', headers=h, json={'notes': 'Changed'}).status_code == 200
    assert client.delete(f'{base}/{lid}', headers=h).status_code == 204
    history = client.get(f'{base}/{lid}/history', headers=h).json['history']
    assert [r['action'] for r in history] == ['DELETED', 'UPDATED', 'CREATED']


def test_preparation_version_and_team_scope(client, tactical):
    t = tactical; h = t['headers'][0]; url = f"/api/teams/{t['team']}/maps/{t['map']}/preparation"
    assert client.get(url, headers=t['headers'][6]).status_code == 403
    data = {'version': 0, 'lineup_id': t['lineup'], 'notes': 'Practice', 'readiness': 'READY'}
    saved = client.put(url, headers=h, json=data)
    assert saved.status_code == 200, saved.json
    assert saved.json['preparation']['version'] == 1
    assert client.put(url, headers=h, json=data).status_code == 409
    assert client.put(url, headers=t['headers'][1], json=data).status_code == 403


def test_private_grenades_favorites_and_dashboard(client, tactical):
    t = tactical; h = t['headers'][0]
    data = {'map_id': t['map'], 'team_id': t['team'], 'visibility': 'TEAM', 'title': 'Secret smoke', 'type': 'Smoke', 'side': 'T', 'video_url': 'https://youtu.be/dQw4w9WgXcQ', 'position': [.2, .8], 'responsible_id': t['users'][1]}
    created = client.post('/api/lineups', headers=h, json=data)
    assert created.status_code == 201, created.json
    gid = created.json['lineup']['id']; url = f'/api/lineups/{gid}'
    assert client.get(url).status_code == 404
    assert client.get(url, headers=t['headers'][6]).status_code == 404
    assert client.get('/api/lineups', headers=t['headers'][6]).json['lineups'] == []
    assert client.put(url, headers=t['headers'][1], json={'title': 'no'}).status_code == 403
    assert client.put(url + '/favorite', headers=t['headers'][1]).status_code == 204
    assert client.get('/api/lineups/favorites', headers=t['headers'][1]).json['favorites'] == [gid]
    assert client.get('/api/lineups/favorites', headers=h).json['favorites'] == []
    assert client.post(url + '/duplicate', headers=h).status_code == 201
    assert client.post(url + '/duplicate', headers=t['headers'][1]).status_code == 403
    assert client.delete(url, headers=h).status_code == 200
    assert client.get('/api/lineups/favorites', headers=t['headers'][1]).json['favorites'] == []
    dashboard = client.get('/api/dashboard', headers=t['headers'][6]).json['dashboard']
    assert dashboard['summary']['lineups']['total'] == 0


def test_empty_statistics_and_resource_counts(client, tactical):
    t = tactical; create(client, t)
    data = client.get(f"/api/teams/{t['team']}/map-resources", headers=t['headers'][0]).json['resources']
    assert data[0]['strategies_count'] == 1
    stats = client.get(f"/api/teams/{t['team']}/maps/{t['map']}/statistics", headers=t['headers'][0]).json
    assert stats['team_statistics'] is None
    assert stats['faceit'] is None
    assert stats['players'] == []


def test_deleted_lineup_retains_strategy_and_history(client, tactical):
    t = tactical; s = create(client, t); h = t['headers'][0]
    assert client.delete(f"/api/teams/{t['team']}/lineups/{t['lineup']}", headers=h).status_code == 204
    result = client.get(f"/api/teams/{t['team']}/strategies/{s['id']}", headers=h)
    assert result.status_code == 200
    assert result.json['strategy']['lineup_id'] is None
    assert result.json['strategy']['needs_review'] == [t['users'][1]]
    assert result.json['strategy']['version'] == 2
    restored = client.post(f"/api/teams/{t['team']}/strategies/{s['id']}/restore/1", headers=h, json={'version': 2})
    assert restored.status_code == 200, restored.json
    assert restored.json['strategy']['status'] == 'DRAFT'
    assert restored.json['strategy']['lineup_id'] is None
    assert restored.json['strategy']['needs_review'] == [t['users'][1]]


def test_postgres_optimistic_concurrency(app, client, tactical):
    if db.engine.dialect.name != 'postgresql':
        pytest.skip('Requires real PostgreSQL for concurrent independent sessions')
    from sqlalchemy.orm import Session
    from sqlalchemy.orm.exc import StaleDataError
    from app.models.tactics import TeamStrategy
    s = create(client, tactical)
    with Session(db.engine) as first, Session(db.engine) as second:
        one = first.get(TeamStrategy, s['id'])
        two = second.get(TeamStrategy, s['id'])
        one.name = 'First editor'
        two.name = 'Stale editor'
        first.commit()
        with pytest.raises(StaleDataError):
            second.commit()
        second.rollback()
        assert second.get(TeamStrategy, s['id']).name == 'First editor'


def test_callout_extended_fields_and_duplicate_protection(client, tactical):
    t = tactical; h = t['headers'][7]; url = f"/api/maps/{t['map']}/callouts"
    data = {'zone_name': 'Window', 'zone': 'Mid', 'description': 'Elevated position', 'x_ratio': .4, 'y_ratio': .6, 'status': 'PUBLISHED'}
    response = client.post(url, headers=h, json=data)
    assert response.status_code == 201
    assert response.json['callout']['author_id'] == t['users'][7]
    assert client.post(url, headers=h, json={**data, 'zone_name': 'window'}).status_code == 409
    assert client.put(url + '/' + str(response.json['callout']['id']), headers=h, json={'image_url': 'https://127.0.0.1/private'}).status_code == 400


def test_statistics_do_not_expose_private_member_demos(client, tactical):
    from app.models.player_profile import PlayerProfile
    from app.models.matchmaking import MatchmakingMatch
    t = tactical
    profile = PlayerProfile(user_id=t['users'][1], nickname='Private demo player', visibility='PRIVATE')
    db.session.add(profile)
    db.session.add(MatchmakingMatch(user_id=t['users'][1], map_name='de_mirage', demo_status='OK', result='WIN', kills=20, deaths=10, rounds_played=20, damage=1600, headshot_kills=10))
    db.session.commit()
    url = f"/api/teams/{t['team']}/maps/{t['map']}/statistics"
    assert client.get(url, headers=t['headers'][0]).json['players'] == []
    own = client.get(url, headers=t['headers'][1]).json['players'][0]
    assert own['kd'] == 2
    assert own['adr'] == 80
    assert own['hs_percentage'] == 50


def test_recommendations_are_persistent_and_team_scoped(client, tactical):
    t = tactical; s = create(client, t); h = t['headers'][0]
    url = f"/api/teams/{t['team']}/lineups/{t['lineup']}/recommendations"
    assert client.put(url, headers=t['headers'][1], json={'strategy_ids': [s['id']]}).status_code == 403
    assert client.put(url, headers=h, json={'strategy_ids': [s['id'], s['id']]}).status_code == 400
    assert client.put(url, headers=h, json={'strategy_ids': [99999]}).status_code == 400
    assert client.put(url, headers=h, json={'strategy_ids': [s['id']]}).status_code == 200
    assert client.get(url, headers=t['headers'][1]).json['strategy_ids'] == [s['id']]
    assert client.get(url, headers=t['headers'][6]).status_code == 403
    assert client.delete(f"/api/teams/{t['team']}/strategies/{s['id']}", headers=h, json={'version': 1}).status_code == 204
    assert client.get(url, headers=h).json['strategy_ids'] == []


def test_last_member_leaving_preserves_archived_playbook(client, tactical):
    from app.models.tactics import TeamStrategy, StrategyRevision
    t = tactical; h = t['headers'][6]
    created = client.post(f"/api/teams/{t['other']}/strategies", headers=h, json={'map_id': t['map'], 'name': 'Historical solo plan'})
    assert created.status_code == 201
    sid = created.json['strategy']['id']
    assert client.post(f"/api/teams/{t['other']}/leave", headers=h).status_code == 204
    strategy = db.session.get(TeamStrategy, sid)
    assert strategy is not None
    assert strategy.status == 'ARCHIVED'
    assert strategy.team_id is None
    assert db.session.query(StrategyRevision).filter_by(strategy_id=sid).count() == 1
