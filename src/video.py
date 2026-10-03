from pathlib import Path
from dataclasses import dataclass
import math
import cv2


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    fps: float
    frames: int
    duration: float


def open_video(path: Path) -> tuple[cv2.VideoCapture, VideoInfo]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        cap.release()
        raise ValueError(f'Cannot open/decode video: {path}')
    values = [cap.get(p) for p in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT,
              cv2.CAP_PROP_FPS, cv2.CAP_PROP_FRAME_COUNT)]
    if any(not math.isfinite(v) or v <= 0 for v in values):
        cap.release()
        raise ValueError(f'Video metadata/duration unavailable: {path}')
    width, height, fps, frames = values
    return cap, VideoInfo(int(width), int(height), fps, int(frames), frames / fps)


def sampled_frames(cap: cv2.VideoCapture, info: VideoInfo, interval: float):
    """Sequential grab avoids repeated keyframe seeking; retrieve only sampled frames.

    Prefer decoder PTS for VFR files; use frame index/FPS when backend has no PTS.
    """
    target = 0.0
    index = 0
    previous_pts = -1.0
    while cap.grab():
        pts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
        time = pts if math.isfinite(pts) and pts > previous_pts else index / info.fps
        previous_pts = max(previous_pts, pts) if math.isfinite(pts) else previous_pts
        if time + 1e-7 >= target:
            ok, frame = cap.retrieve()
            if not ok or frame is None:
                raise ValueError(f'OpenCV failed to decode frame at {time:.3f}s')
            yield time, frame
            target = (math.floor(time / interval) + 1) * interval
        index += 1
    if index == 0 or index < info.frames - max(2, int(info.fps)):
        raise ValueError(f'Video ended unexpectedly: decoded {index}/{info.frames} frames')
