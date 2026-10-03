from pathlib import Path
import json
import logging
import math
import os


def timestamp(seconds: float) -> str:
    milliseconds = round(max(0, seconds) * 1000)
    seconds, ms = divmod(milliseconds, 1000)
    minutes, sec = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    return f'{hours:02}:{minute:02}:{sec:02}.{ms:03}'


def roi_pixels(roi: dict, width: int, height: int) -> tuple[int, int, int, int]:
    box = (int(roi['x1'] * width), int(roi['y1'] * height),
           min(width, math.ceil(roi['x2'] * width)), min(height, math.ceil(roi['y2'] * height)))
    if box[0] >= box[2] or box[1] >= box[3]:
        raise ValueError('ROI is empty at this video resolution')
    return box


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def setup_logging(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    for name, level in [('app.log', logging.DEBUG), ('error.log', logging.ERROR)]:
        handler = logging.FileHandler(root / name, encoding='utf-8')
        handler.setLevel(level)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(console)
