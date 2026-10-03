import argparse
from pathlib import Path


def main() -> int:
    cli = argparse.ArgumentParser(description='Select normalized LoL kill UI ROI / save a real template.')
    cli.add_argument('video', type=Path)
    cli.add_argument('--time', type=float, default=0, help='Frame time in seconds')
    cli.add_argument('--save-template', type=Path, help='Save selected pixels as template PNG')
    args = cli.parse_args()
    cap = None
    try:
        import cv2
        import math
        from src.video import open_video
        if not math.isfinite(args.time) or args.time < 0:
            raise ValueError('--time must be finite and >= 0')
        cap, info = open_video(args.video)
        if args.time >= info.duration:
            raise ValueError('--time exceeds video duration')
        cap.set(cv2.CAP_PROP_POS_MSEC, args.time * 1000)
        ok, frame = cap.read()
        if not ok:
            raise ValueError('Cannot decode selected frame')
        ratio = min(1.0, 1280 / info.width, 720 / info.height)
        display = cv2.resize(frame, (round(info.width * ratio), round(info.height * ratio)))
        x, y, w, h = cv2.selectROI('Select ROI: ENTER confirms; C cancels', display, fromCenter=False)
        if not w or not h:
            print('Selection cancelled')
            return 0
        roi = {'x1': x/display.shape[1], 'y1': y/display.shape[0],
               'x2': (x+w)/display.shape[1], 'y2': (y+h)/display.shape[0]}
        print('Selected ROI (copy into config.yaml):\nroi:')
        for key, value in roi.items():
            print(f'  {key}: {value:.6f}')
        if args.save_template:
            from src.utils import roi_pixels
            x1, y1, x2, y2 = roi_pixels(roi, info.width, info.height)
            args.save_template.parent.mkdir(parents=True, exist_ok=True)
            ok, data = cv2.imencode('.png', frame[y1:y2, x1:x2])
            if not ok:
                raise ValueError('Cannot encode template')
            data.tofile(args.save_template)
            print(f'Template saved: {args.save_template}')
        return 0
    except Exception as exc:
        print(f'Error: {exc}')
        return 1
    finally:
        if cap is not None:
            cap.release()
        try:
            import cv2
            cv2.destroyAllWindows()
        except ImportError:
            pass


if __name__ == '__main__':
    raise SystemExit(main())
