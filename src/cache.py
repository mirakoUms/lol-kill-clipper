from pathlib import Path
import hashlib
import json
import logging
import math
from src.utils import write_json

VERSION = 1


def fingerprint(video: Path, config: dict) -> dict:
    stat = video.stat()
    return {'version': VERSION, 'video': str(video.resolve()), 'size': stat.st_size,
            'mtime_ns': stat.st_mtime_ns,
            'detection': {key: config[key] for key in ('scan_interval', 'match_threshold', 'kill_cooldown', 'roi')},
            'scales': config['template']['scales'],
            'template_hash': hashlib.sha256(Path(config['template']['path']).read_bytes()).hexdigest()}


def cache_path(root: Path, video: Path) -> Path:
    digest = hashlib.sha256(str(video.resolve()).encode('utf-8')).hexdigest()[:12]
    return root / f'{video.stem}_{digest}.json'


def read_cache(path: Path, key: dict) -> tuple[list[dict], float] | None:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if data['fingerprint'] != key:
            return None
        duration = data['duration']
        events = data['events']
        if not isinstance(duration, (float, int)) or not math.isfinite(duration) or duration <= 0 or not isinstance(events, list):
            return None
        for event in events:
            if not isinstance(event, dict):
                return None
            for field in ('time', 'confidence', 'event_start', 'event_end'):
                if not isinstance(event.get(field), (int, float)) or not math.isfinite(event[field]):
                    return None
            if not 0 <= event['time'] <= duration or not 0 <= event['confidence'] <= 1:
                return None
        return events, float(duration)
    except (OSError, ValueError, KeyError, TypeError):
        logging.debug('Detection cache missing, invalid or unreadable: %s', path)
        return None


def save_cache(path: Path, key: dict, events: list[dict], duration: float) -> None:
    write_json(path, {'fingerprint': key, 'duration': duration, 'events': events})
