"""Windows-native LoL kill clipper CLI."""
import argparse
from pathlib import Path


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description='Detect LoL kill UI templates and export clips.')
    cli.add_argument('input', type=Path, help='Video file or folder (nonrecursive)')
    cli.add_argument('--config', type=Path, default=Path(__file__).parent / 'config.yaml')
    cli.add_argument('--debug', action='store_true', help='Save bounded ROI images and confidence CSV')
    cli.add_argument('--detect-only', action='store_true', help='Detect without requiring FFmpeg')
    cli.add_argument('--force', action='store_true', help='Ignore detection cache')
    cli.add_argument('--events', type=Path, help='Events JSON from fetch_events.py; bypass template detection (single video only)')
    cli.add_argument('--time-offset', type=float, default=0, help='Video seconds minus game seconds; used with --events')
    cli.add_argument('--event-overrides', type=Path, help='YAML with per-event video start/end boundaries; single video only')
    cli.add_argument('--combine', action='store_true', help='Also join clips chronologically into all_events.mp4')
    cli.add_argument('--cut-mode', choices=['fast', 'accurate'], help='Override configured encoding mode')
    return cli


def main() -> int:
    args = parser().parse_args()
    try:
        from src.pipeline import run
        return run(args)
    except ModuleNotFoundError as exc:
        import logging
        logging.error('Missing Python dependency: %s. Run: python -m pip install -r requirements.txt', exc.name)
        return 1
    except (Exception, KeyboardInterrupt) as exc:
        import logging
        logging.error('%s', exc if not isinstance(exc, KeyboardInterrupt) else 'Interrupted')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
