"""Expose verified individual demo records without claiming team match results."""
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from app.extensions import db
from app.models.map import Map
from app.models.user import User
from app.models.matchmaking import MatchmakingMatch
from app.models.tactics import TeamStrategy, TeamMapSetup
from app.models.lineup import Lineup
from app.permissions import can_view
from app.services.tactical_service import access
from app.services.lineup_service import visible_query
from app.services.matchmaking.stats import aggregate_matches


def statistics(user, team_id, map_id):
    team, _ = access(user, team_id)
    from app.services.map_service import get_map
    map_obj = get_map(map_id)
    users = db.session.query(User).options(selectinload(User.profile)).filter(User.id.in_([m.user_id for m in team.members])).all()
    allowed = [u for u in users if u.profile and can_view(user, u.profile.visibility, owner_id=u.id)]
    name = map_obj.name.lower().removeprefix('de_')
    matches = db.session.query(MatchmakingMatch).filter(MatchmakingMatch.user_id.in_([u.id for u in allowed]), MatchmakingMatch.demo_status == 'OK', func.lower(MatchmakingMatch.map_name).in_([name, 'de_' + name])).all()
    groups = {}
    for match in matches:
        groups.setdefault(match.user_id, []).append(match)
    return {'team_statistics': None, 'faceit': None, 'source': 'OFFICIAL_VERIFIED_DEMO',
            'scope': 'INDIVIDUAL_MEMBERS_NOT_TEAM_RESULTS',
            'players': [{'user_id': u.id, 'nickname': u.profile.nickname, **aggregate_matches(groups[u.id])} for u in allowed if u.id in groups]}


def resources(user, team_id):
    access(user, team_id)
    strategies = dict(db.session.query(TeamStrategy.map_id, func.count(TeamStrategy.id)).filter_by(team_id=team_id).group_by(TeamStrategy.map_id).all())
    grenades = dict(visible_query(user).with_entities(Lineup.map_id, func.count(Lineup.id)).filter(db.or_(Lineup.team_id == team_id, Lineup.visibility == 'PUBLIC')).group_by(Lineup.map_id).all())
    setups = {s.map_id: s.readiness for s in db.session.query(TeamMapSetup).filter_by(team_id=team_id)}
    return [{'map_id': m.id, 'strategies_count': strategies.get(m.id, 0), 'grenades_count': grenades.get(m.id, 0), 'readiness': setups.get(m.id, 'NOT_STARTED')} for m in db.session.query(Map)]
