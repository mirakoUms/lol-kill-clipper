"""Per-event clip boundaries, expressed in video time, not game time."""
from pathlib import Path
import math
import yaml


def parse_time(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError('Time must be seconds or a quoted MM:SS / HH:MM:SS timestamp')
    if isinstance(value, (int, float)):
        seconds = float(value)
    elif isinstance(value, str):
        value = value.strip().replace('：', ':')
        parts = value.split(':')
        if len(parts) not in (2, 3):
            raise ValueError('Use seconds or a quoted MM:SS / HH:MM:SS timestamp')
        try:
            if any(not p.isdigit() for p in parts[:-1]):
                raise ValueError()
            numbers = [float(p) for p in parts]
            if not 0 <= numbers[-1] < 60 or (len(parts) == 3 and not 0 <= numbers[-2] < 60):
                raise ValueError()
            seconds = sum(v * 60**i for i, v in enumerate(reversed(numbers)))
        except ValueError:
            raise ValueError(f'Invalid timestamp: {value}') from None
    else:
        raise ValueError('Clip boundary must be a number or timestamp')
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError('Clip boundary must be finite and >= 0')
    return seconds


def load_overrides(path: Path | None) -> dict[int, dict[str, float]]:
    if path is None:
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8-sig'))
    except yaml.YAMLError as exc:
        raise ValueError(f'Invalid overrides YAML: {exc}') from None
    if not isinstance(data, dict) or set(data) != {'events'} or not isinstance(data['events'], dict):
        raise ValueError('Overrides file must contain an events mapping keyed by event number')
    result = {}
    for index, window in data['events'].items():
        if isinstance(index, bool) or not isinstance(index, int) or index < 1:
            raise ValueError('Override event numbers must be positive integers (1-based)')
        if not isinstance(window, dict) or not window or any(k not in ('start', 'end') for k in window):
            raise ValueError(f'Event {index}: provide start and/or end')
        result[index] = {key: parse_time(value) for key, value in window.items()}
    return result
