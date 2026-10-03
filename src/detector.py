from pathlib import Path
import csv
import logging
import cv2
import numpy as np
from tqdm import tqdm
from src.utils import roi_pixels, timestamp
from src.video import open_video, sampled_frames


def load_templates(config: dict) -> list[np.ndarray]:
    path = Path(config['path'])
    if not path.is_file():
        raise ValueError(f'Kill template not found:\n{path}\nPlease create the template first.\nSee templates/README.md')
    template = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if template is None:
        raise ValueError(f'Cannot decode template: {path}')
    templates = []
    for scale in config['scales']:
        size = (max(1, round(template.shape[1] * scale)), max(1, round(template.shape[0] * scale)))
        resized = cv2.resize(template, size)
        if resized.std() < 1:
            raise ValueError('Template has too little contrast for normalized matching')
        templates.append(resized)
    return templates


def save_image(path: Path, image: np.ndarray) -> None:
    ok, data = cv2.imencode('.jpg', image)
    if not ok:
        raise ValueError(f'Cannot encode debug image: {path}')
    data.tofile(path)


def group_candidates(candidates: list[dict], cooldown: float, interval: float) -> list[dict]:
    """Continuous hits form one event; nearby bursts merge under cooldown.

    Compare to the end of the preceding hit window, keeping its strongest hit.
    This prevents a persistent banner creating another event every cooldown.
    """
    groups: list[dict] = []
    last_hit = -float('inf')
    for candidate in candidates:
        gap = candidate['time'] - last_hit
        if groups and (gap <= interval * 1.5 + 1e-6 or gap < cooldown):
            if candidate['confidence'] > groups[-1]['confidence']:
                groups[-1].update(candidate)
            groups[-1]['event_end'] = candidate['time']
        else:
            groups.append({**candidate, 'event_start': candidate['time'], 'event_end': candidate['time']})
        last_hit = candidate['time']
    return groups


def detect(path: Path, config: dict, templates: list[np.ndarray], debug_dir: Path | None = None) -> tuple[list[dict], float]:
    cap, info = open_video(path)
    logging.info('Video resolution: %sx%s; FPS: %.3f; Duration: %.3f', info.width, info.height, info.fps, info.duration)
    candidates: list[dict] = []
    csv_file = None
    try:
        x1, y1, x2, y2 = roi_pixels(config['roi'], info.width, info.height)
        if any(t.shape[0] > y2-y1 or t.shape[1] > x2-x1 for t in templates):
            raise ValueError('Template is larger than ROI; adjust ROI or template.scales')
        sample_count = 0
        saved = 0
        best_image = None
        best_score = -1.0
        best_time = 0.0
        last_hit = -float('inf')
        if debug_dir:
            debug_dir.mkdir(parents=True, exist_ok=True)
            csv_file = (debug_dir / 'confidence.csv').open('w', newline='', encoding='utf-8')
            writer = csv.writer(csv_file)
            writer.writerow(['seconds', 'timestamp', 'confidence'])
        with tqdm(total=info.duration, desc=f'Scanning {path.name}', unit='s') as progress:
            for time, frame in sampled_frames(cap, info, config['scan_interval']):
                gray = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
                score = max(float(cv2.minMaxLoc(cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED))[1]) for t in templates)
                logging.debug('Sample: %.3f %s confidence=%.5f', time, timestamp(time), score)
                if csv_file:
                    writer.writerow([f'{time:.3f}', timestamp(time), f'{score:.5f}'])
                progress.update(min(info.duration, time) - progress.n)
                progress.set_postfix_str(f'{timestamp(time)} / {timestamp(info.duration)}', refresh=False)
                if debug_dir and sample_count < config['debug']['sample_images'] and saved < config['debug']['max_images']:
                    save_image(debug_dir / f'sample_{sample_count:03}.jpg', gray)
                    sample_count += 1
                    saved += 1
                if score >= config['match_threshold']:
                    candidates.append({'time': time, 'timestamp': timestamp(time), 'confidence': score})
                    logging.debug('Candidate event: %.3f confidence=%.5f', time, score)
                    if debug_dir and saved < config['debug']['max_images']:
                        gap = time - last_hit
                        if best_image is not None and gap > config['scan_interval'] * 1.5 and gap >= config['kill_cooldown']:
                            save_image(debug_dir / f'detected_{saved:04}_{timestamp(best_time).replace(":", "-")}_{best_score:.2f}.jpg', best_image)
                            saved += 1
                            best_score = -1
                            best_image = None
                        if saved < config['debug']['max_images'] and score > best_score:
                            best_image, best_score, best_time = gray.copy(), score, time
                    last_hit = time
            progress.update(max(0, info.duration-progress.n))
        if debug_dir and best_image is not None and saved < config['debug']['max_images']:
            save_image(debug_dir / f'detected_{saved:04}_{timestamp(best_time).replace(":", "-")}_{best_score:.2f}.jpg', best_image)
        return group_candidates(candidates, config['kill_cooldown'], config['scan_interval']), info.duration
    finally:
        cap.release()
        if csv_file:
            csv_file.close()
