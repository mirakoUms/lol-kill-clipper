"""Import game events without UI matching. All times are seconds after game start."""
import json
import math
from pathlib import Path
from src.utils import timestamp


def extract_events(timeline: dict, participant_id: int, kind: str = 'kill') -> list[dict]:
    if kind not in ('kill', 'death', 'assist', 'both', 'all'):
        raise ValueError('Event kind must be kill, death, assist, both or all')
    if not isinstance(participant_id, int) or isinstance(participant_id, bool) or participant_id <= 0:
        raise ValueError('participant_id must be a positive integer')
    body = timeline.get('info', timeline)
    frames = body.get('frames')
    if not isinstance(frames, list):
        raise ValueError('Timeline has no frames list; the client may not support this endpoint')
    result = []
    for frame in frames:
        for event in frame.get('events', []):
            if event.get('type', event.get('eventType')) != 'CHAMPION_KILL':
                continue
            role = 'kill' if event.get('killerId') == participant_id else (
                'death' if event.get('victimId') == participant_id else (
                    'assist' if participant_id in (event.get('assistingParticipantIds') or []) else None))
            if role is None or (kind == 'both' and role == 'assist') or (kind not in ('both', 'all') and role != kind):
                continue
            raw = event.get('timestamp')
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw < 0:
                raise ValueError('Invalid event timestamp in client timeline')
            seconds = raw / 1000
            result.append({'game_time': seconds, 'kind': role,
                           'killer_id': event.get('killerId'), 'victim_id': event.get('victimId')})
    return sorted(result, key=lambda event: event['game_time'])


def import_events(path: Path, offset: float, duration: float) -> list[dict]:
    if not math.isfinite(offset):
        raise ValueError('--time-offset must be finite')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or data.get('schema') != 'lol-clipper-events-v1' or not isinstance(data.get('events'), list):
        raise ValueError('Unsupported events file; use fetch_events.py to create it')
    result = []
    for item in data['events']:
        if not isinstance(item, dict) or item.get('kind') not in ('kill', 'death', 'assist'):
            raise ValueError('Invalid event entry')
        seconds = item.get('game_time')
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError('Invalid game_time in events file')
        video_time = seconds + offset
        if not 0 <= video_time < duration:
            raise ValueError(f'Event {timestamp(seconds)} maps outside the video; check --time-offset or match selection')
        result.append({**item, 'time': video_time, 'timestamp': timestamp(video_time),
                       'confidence': None, 'source': 'client_timeline'})
    return sorted(result, key=lambda event: event['time'])
