import pytest


def test_metadata_persists_without_changing_callout_coordinates(client, admin_headers):
    created = client.post('/api/maps', headers=admin_headers, json={
        'name': 'Ancient', 'image_url': 'https://example.com/radar.png',
        'cover_url': 'https://example.com/cover.jpg', 'description': 'Ancient tactics',
    })
    assert created.status_code == 201
    map_id = created.json['map']['id']
    client.post(f'/api/maps/{map_id}/callouts', headers=admin_headers,
                json={'zone_name': 'Mid', 'x_ratio': .4, 'y_ratio': .6})
    response = client.put(f'/api/maps/{map_id}', headers=admin_headers,
                          json={'cover_url': None, 'description': 'Updated'})
    assert response.status_code == 200
    stored = client.get(f'/api/maps/{map_id}').json['map']
    assert stored['cover_url'] is None
    assert stored['description'] == 'Updated'
    assert stored['image_url'] == 'https://example.com/radar.png'
    assert stored['callouts'][0]['x_ratio'] == .4


@pytest.mark.parametrize('payload', [
    {'cover_url': 'javascript:alert(1)'},
    {'cover_url': 'https://user:password@example.com/map.png'},
    {'description': 'x' * 4001}, {'description': {'unexpected': 'object'}},
])
def test_invalid_metadata_is_rejected(client, admin_headers, payload):
    response = client.post('/api/maps', headers=admin_headers, json={
        'name': 'Nuke', 'image_url': 'https://example.com/radar.png', **payload,
    })
    assert response.status_code == 400
    assert client.get('/api/maps').json['maps'] == []


def test_library_filters_and_permissions(client, admin_headers, auth_headers):
    for name, pool in [('Mirage', True), ('Ancient', False), ('Nuke', True)]:
        response = client.post('/api/maps', headers=admin_headers, json={
            'name': name, 'image_url': 'https://example.com/map.png', 'active_pool': pool,
        })
        assert response.status_code == 201
    assert [m['name'] for m in client.get('/api/maps?pool=active&sort=name_desc').json['maps']] == ['Nuke', 'Mirage']
    assert [m['name'] for m in client.get('/api/maps?q=anc').json['maps']] == ['Ancient']
    assert client.get('/api/maps?q=%25').json['maps'] == []
    assert client.get('/api/maps?pool=invalid').status_code == 400
    assert client.get('/api/maps?sort=invalid').status_code == 400
    assert client.put('/api/maps/1', headers=auth_headers,
                      json={'description': 'unauthorized'}).status_code == 403
