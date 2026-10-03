from pathlib import Path
import hashlib
import logging
import time
from src.cache import fingerprint, cache_path, read_cache, save_cache
from src.clipper import check_ffmpeg, merge_clips, cut_clips, combine_clips
from src.config import load_config
from src.detector import load_templates, detect
from src.utils import setup_logging, write_json, timestamp
from src.events import import_events
from src.video import open_video
from src.overrides import load_overrides


def run(args) -> int:
    source = args.input.resolve()
    if not source.exists():
        raise ValueError(f'Input not found: {source}')
    root = source if source.is_dir() else source.parent
    setup_logging(root / 'logs')
    config = load_config(args.config)
    if getattr(args, 'cut_mode', None):
        config['cut_mode'] = args.cut_mode
    override_file = getattr(args, 'event_overrides', None)
    if override_file and source.is_dir():
        raise ValueError('--event-overrides requires one video; event numbers are specific to that video')
    overrides = load_overrides(override_file)
    event_file = getattr(args, 'events', None)
    if event_file and source.is_dir():
        raise ValueError('--events requires one video, not a folder; each match has its own event file')
    templates = None if event_file else load_templates(config['template'])
    executable = None if args.detect_only else check_ffmpeg()
    extensions = {e.lower() for e in config['video_extensions']}
    videos = sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in extensions) if source.is_dir() else [source]
    if not videos or any(v.suffix.lower() not in extensions for v in videos):
        raise ValueError('No supported videos found; check video_extensions in config.yaml')
    results: dict = {}
    failures = 0
    start = time.monotonic()
    stems: dict[str, int] = {}
    for video in videos:
        stems[video.stem.casefold()] = stems.get(video.stem.casefold(), 0) + 1
    for video in videos:
        started = time.monotonic()
        logging.info('Processing %s', video.name)
        name = video.stem
        if stems[name.casefold()] > 1:
            name += '_' + hashlib.sha256(video.name.encode('utf-8')).hexdigest()[:8]
        try:
            cached = None
            if event_file:
                cap, info = open_video(video)
                cap.release()
                duration = info.duration
                events = import_events(event_file, getattr(args, 'time_offset', 0), duration)
                logging.info('Imported client timeline events. Template scanning skipped.')
            else:
                key = fingerprint(video, config)
                cache = cache_path(root / 'cache', video)
                cached = None if args.force or args.debug else read_cache(cache, key)
            if not event_file and cached is not None:
                logging.info('Detection cache found. Skipping detection.')
                events, duration = cached
            elif not event_file:
                events, duration = detect(video, config, templates, root / 'debug' / name if args.debug else None)
                save_cache(cache, key, events, duration)
            logging.info('%s %s events.', 'Imported' if event_file else 'Detected', len(events))
            for i, event in enumerate(events, 1):
                if event_file:
                    logging.info('%s. %s %s (game %s)', i, timestamp(event['time']), event['kind'], timestamp(event['game_time']))
                else:
                    logging.info('%s. %s confidence=%.3f', i, timestamp(event['time']), event['confidence'])
            clips = merge_clips(events, duration, config['pre_kill_seconds'], config['post_kill_seconds'], config['merge_gap'],
                                config['event_windows'], overrides)
            for index, clip in enumerate(clips, 1):
                logging.info('Clip %s: %s to %s (events %s)', index, timestamp(clip['start']), timestamp(clip['end']),
                             ', '.join(str(i+1) for i in clip['event_indices']))
            exported = [] if args.detect_only else cut_clips(video, root / 'clips' / name, clips, config['cut_mode'], executable)
            combined = None
            if exported and getattr(args, 'combine', False):
                combined_path = root / 'clips' / name / 'all_events.mp4'
                combine_clips(exported, combined_path, executable)
                combined = combined_path.relative_to(root).as_posix()
            kills = [{**event, 'clip': None} for event in events]
            for clip in exported:
                for index in clip['event_indices']:
                    kills[index]['clip'] = Path(clip['path']).relative_to(root).as_posix()
            results[video.name] = {'status': 'ok', 'duration': duration, 'kills': kills,
                                  'clips': [{**clip, 'path': Path(clip['path']).relative_to(root).as_posix()} for clip in exported],
                                  'planned_clips': clips, 'detection_cached': cached is not None, 'combined': combined}
            logging.info('Generated %s clips. %s event(s) merged. Processing time: %s',
                         len(exported), len(events)-len(clips), timestamp(time.monotonic()-started))
        except Exception as exc:
            failures += 1
            logging.error('Processing %s FAILED: %s', video.name, exc)
            logging.debug('Failure details for %s', video.name, exc_info=True)
            results[video.name] = {'status': 'failed', 'error': str(exc)}
        write_json(root / 'results.json', results)
    logging.info('%s videos processed successfully; %s video(s) failed. Total time: %s',
                 len(videos)-failures, failures, timestamp(time.monotonic()-start))
    return 1 if failures else 0
