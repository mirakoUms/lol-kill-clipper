from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
import json
import pytest
from src.events import extract_events, import_events
from src.lcu import connection, own_participant, find_lockfile, Client
from src.pipeline import run


def timeline():
    return {'frames': [{'events': [
        {'type': 'CHAMPION_KILL', 'killerId': 2, 'victimId': 3, 'timestamp': 135192},
        {'eventType': 'CHAMPION_KILL', 'killerId': 3, 'victimId': 2, 'timestamp': 202733},
        {'type': 'CHAMPION_KILL', 'killerId': 4, 'victimId': 5, 'timestamp': 210000},
        {'type': 'WARD_KILL', 'killerId': 2, 'timestamp': 220000}]}]}


def test_own_kills_and_deaths():
    kills = extract_events(timeline(), 2)
    assert len(kills) == 1 and kills[0]['game_time'] == 135.192
    assert extract_events(timeline(), 2, 'death')[0]['game_time'] == 202.733
    assert len(extract_events({'info': timeline()}, 2, 'both')) == 2
    with pytest.raises(ValueError):
        extract_events({}, 2)


def test_offset(tmp_path):
    path = tmp_path / '事件 空格.json'
    path.write_text(json.dumps({'schema': 'lol-clipper-events-v1', 'events': extract_events(timeline(), 2)}))
    imported = import_events(path, 20, 300)
    assert imported[0]['time'] == pytest.approx(155.192)
    assert imported[0]['confidence'] is None
    with pytest.raises(ValueError, match='outside'):
        import_events(path, 500, 300)
    with pytest.raises(ValueError):
        import_events(path, float('nan'), 300)
    assert import_events(path, -100, 300)[0]['time'] == pytest.approx(35.192)


@pytest.mark.parametrize('bad', [True, '135', -1, float('nan')])
def test_bad_event_time(tmp_path, bad):
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps({'schema': 'lol-clipper-events-v1', 'events': [{'kind': 'kill', 'game_time': bad}]}))
    with pytest.raises(ValueError):
        import_events(path, 0, 300)


def test_player_identification():
    detail = {'participantIdentities': [{'participantId': 2, 'player': {'puuid': 'self', 'summonerId': 7}}]}
    assert own_participant(detail, {'puuid': 'self'}) == 2
    assert own_participant(detail, {'summonerId': '7'}) == 2
    with pytest.raises(ValueError):
        own_participant(detail, {'puuid': 'other'})


def test_lockfile(tmp_path):
    path = tmp_path/'lockfile'
    path.write_text('LeagueClient:123:54321:unit-test-secret:https')
    assert find_lockfile(tmp_path) == path
    port, auth = connection(path)
    assert port == 54321 and auth
    path.write_text('malformed')
    with pytest.raises(ValueError):
        connection(path)


def test_client_get_loopback_only(tmp_path):
    path = tmp_path/'lockfile'
    path.write_text('LeagueClient:123:54321:unit-test-secret:https')
    client = Client(path)
    with pytest.raises(ValueError):
        client.get('https://external.example/credentials')
    with patch.object(client._opener, 'open') as open_mock:
        from io import BytesIO
        open_mock.return_value.__enter__.return_value = BytesIO(b'{"ok":true}')
        assert client.get('/lol-summoner/v1/current-summoner') == {'ok': True}
        req = open_mock.call_args.args[0]
        assert req.full_url.startswith('https://127.0.0.1:54321/')


def test_import_pipeline_without_template(tmp_path):
    video = tmp_path/'视频 空格.mp4'
    video.write_bytes(b'unit test placeholder')
    events = tmp_path/'events.json'
    events.write_text(json.dumps({'schema':'lol-clipper-events-v1','events':extract_events(timeline(),2)}))
    args = SimpleNamespace(input=video, config=Path(__file__).resolve().parents[1]/'config.example.yaml',
                           events=events, time_offset=20., force=False, debug=False, detect_only=True)
    with patch('src.pipeline.open_video', return_value=(SimpleNamespace(release=lambda: None),SimpleNamespace(duration=300))), \
         patch('src.pipeline.load_templates', side_effect=AssertionError('Must bypass template')):
        assert run(args) == 0
    data = json.loads((tmp_path/'results.json').read_text(encoding='utf-8'))
    assert data[video.name]['kills'][0]['time'] == pytest.approx(155.192)
    assert data[video.name]['planned_clips'][0]['start'] == pytest.approx(140.192)
