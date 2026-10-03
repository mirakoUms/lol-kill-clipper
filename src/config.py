from pathlib import Path
import math
import yaml


def number(value: object, name: str, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} must be a number')
    if not math.isfinite(value) or value < minimum:
        raise ValueError(f'{name} must be finite and >= {minimum}')
    return float(value)


def validate(config: dict) -> dict:
    if not isinstance(config, dict):
        raise ValueError('Configuration must be a YAML mapping')
    for key in ('scan_interval', 'match_threshold', 'kill_cooldown',
                'pre_kill_seconds', 'post_kill_seconds', 'merge_gap'):
        number(config.get(key), key)
    if config['scan_interval'] <= 0 or config['match_threshold'] > 1:
        raise ValueError('scan_interval must be > 0; match_threshold must be <= 1')
    if config['pre_kill_seconds'] + config['post_kill_seconds'] <= 0:
        raise ValueError('Clip duration must be greater than zero')
    windows = config.setdefault('event_windows', {})
    if not isinstance(windows, dict) or any(key not in ('kill', 'death', 'assist') for key in windows):
        raise ValueError('event_windows may contain only kill, death and assist')
    windows.setdefault('assist', dict(windows.get('kill', {'pre': config['pre_kill_seconds'], 'post': config['post_kill_seconds']})))
    for kind, window in windows.items():
        if not isinstance(window, dict) or set(window) != {'pre', 'post'}:
            raise ValueError(f'event_windows.{kind} requires pre and post')
        if number(window['pre'], f'{kind}.pre') + number(window['post'], f'{kind}.post') <= 0:
            raise ValueError(f'event_windows.{kind} duration must be > 0')
    if config.get('cut_mode') not in ('fast', 'accurate'):
        raise ValueError('cut_mode must be fast or accurate')
    roi = config.get('roi')
    if not isinstance(roi, dict):
        raise ValueError('roi must contain x1, y1, x2, y2')
    for key in ('x1', 'y1', 'x2', 'y2'):
        if number(roi.get(key), f'roi.{key}') > 1:
            raise ValueError(f'roi.{key} must be <= 1')
    if roi['x1'] >= roi['x2'] or roi['y1'] >= roi['y2']:
        raise ValueError('ROI requires x1 < x2 and y1 < y2')
    ext = config.get('video_extensions')
    if not isinstance(ext, list) or not ext or any(
            not isinstance(e, str) or not e.startswith('.') or len(e) < 2 for e in ext):
        raise ValueError('video_extensions must be a nonempty list such as [.mp4, .mkv]')
    template = config.get('template')
    if not isinstance(template, dict) or not isinstance(template.get('path'), str) or not template['path']:
        raise ValueError('template.path must be a nonempty path')
    scales = template.setdefault('scales', [1.0])
    if not isinstance(scales, list) or not scales:
        raise ValueError('template.scales must be a nonempty list')
    for scale in scales:
        if number(scale, 'template.scales') <= 0:
            raise ValueError('Template scale must be > 0')
    debug = config.setdefault('debug', {})
    if not isinstance(debug, dict):
        raise ValueError('debug must be a mapping')
    for key, default in [('max_images', 30), ('sample_images', 5)]:
        value = debug.setdefault(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f'debug.{key} must be a nonnegative integer')
    return config


def load_config(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f'Configuration not found: {path}')
    try:
        config = validate(yaml.safe_load(path.read_text(encoding='utf-8-sig')))
    except yaml.YAMLError as exc:
        raise ValueError(f'Invalid YAML: {exc}') from exc
    config['template']['path'] = str((path.resolve().parent / config['template']['path']).resolve())
    return config
