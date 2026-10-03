# LoL Kill Clipper

A small Windows-native tool that turns continuous League of Legends recordings into kill and death clips, plus a chronological montage. Python 3.11+, OpenCV, and FFmpeg; no OCR, deep-learning models, database, or cloud processing.

The recommended workflow reads match events from the logged-in League client. An optional template-matching workflow supports recordings when match data is unavailable.

## Quick start on Windows 11

1. Install Python 3.11 or later and enable **Add Python to PATH**.
2. Download or clone this repository, then open PowerShell in its directory.
   For a convenient first-time installation, double-click `setup.cmd`: it creates the virtual environment, installs dependencies including portable FFmpeg, and creates missing local configuration files. Existing settings are preserved. The manual equivalent follows.
3. Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config.example.yaml config.yaml
Copy-Item workflow.example.yaml workflow.yaml
```

Do not overwrite existing local configuration files when updating. Virtual-environment activation is optional; all examples call its Python executable directly.

4. Install FFmpeg and add its `bin` directory to PATH, then verify `ffmpeg -version`. Alternatively, install the optional portable binary:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-portable.txt
```

5. Set `client_dir` in `workflow.yaml` to your League of Legends installation directory.
6. Open the League client and log in.
7. Double-click **start_clips.cmd**, or drag a recording onto it. Select the matching game and enter the game clock shown at the beginning of the recording, such as `01:46`.

The application exports every kill/death covered by the recording and opens the output folder. See [QUICKSTART.md](QUICKSTART.md) for everyday usage.

The launcher currently uses Chinese prompts and output labels. This documentation is in English. Windows Unicode paths, including Chinese, Japanese, and spaces, are supported.

## Output

Each export creates a new directory under `exports`; earlier exports are preserved.

```text
exports/<recording>_<match>/
  001_<kill>_<game-time>.mp4
  002_<death>_<game-time>.mp4
  <all-events-montage>.mp4
  <clip-index>.csv
  events.json
  export.json
  logs/
```

Every event receives an independent clip, ordered by event time. The montage merges overlapping windows and windows separated by at most `merge_gap`, so the same fight is not replayed multiple times. Audio, source resolution, and source frame rate are retained. Outputs are local; nothing is automatically published to a video platform.

## Clip timing

Current defaults are deliberately simple:

| Event | Before | After |
|---|---:|---:|
| Kill | 15 seconds | 5 seconds |
| Death | 40 seconds | 5 seconds |

Adjust `event_windows` in `config.yaml` without changing Python. This version does **not** automatically identify combat starts. A long chase can exceed any fixed window. Optional manual boundaries are available through the advanced CLI; see [EVENTS_GUIDE.md](EVENTS_GUIDE.md).

For continuous recordings, **video time = game time + offset**. If recording starts at game time `01:46`, the offset is `-106` seconds. If game time `00:00` appears at video time `00:20`, the offset is `+20` seconds. Pauses, speed changes, missing recording sections, and multiple matches require separate alignment.

## Everyday workflow CLI

```powershell
.\.venv\Scripts\python.exe make_clips.py "D:\Recordings\my game.mp4"
.\.venv\Scripts\python.exe make_clips.py "my game.mp4" --match-id 123456789 --recording-start 01:46
.\.venv\Scripts\python.exe make_clips.py "my game.mp4" --events events.json --recording-start 01:46
.\.venv\Scripts\python.exe make_clips.py "my game.mp4" --reselect
.\.venv\Scripts\python.exe make_clips.py --help
```

Successful match/time settings are remembered per video path, size, and modification time. Re-exporting the same unchanged file can use saved event data without reconnecting to the client. `--reselect` clears this choice for the next export. Offline files must contain both event types (`selection: both`). Events outside a partial recording are reported and listed in the manifest.

## Advanced event workflow

```powershell
.\.venv\Scripts\python.exe fetch_events.py --client-dir "C:\Riot Games\League of Legends" --list
.\.venv\Scripts\python.exe fetch_events.py --client-dir "C:\Riot Games\League of Legends" --match-id 123456789 --kind both --output events.json
.\.venv\Scripts\python.exe auto_kill.py "my game.mp4" --events events.json --time-offset -106 --detect-only
.\.venv\Scripts\python.exe auto_kill.py "my game.mp4" --events events.json --time-offset -106 --cut-mode accurate --combine
```

`auto_kill.py` merges the event windows into clips; `make_clips.py` additionally preserves every individual event clip and produces a separate montage. Advanced results are written to `results.json` beside the input video. Their legacy `kills` array may include death events, distinguished by `kind`.

Local client endpoints are not a stable, officially supported third-party API. Availability varies by client version and match. A JP practice match was verified during development; this does not guarantee availability in every region. Akari is not required, and the tool does not automate its GUI. See [Riot's League Client API documentation](https://developer.riotgames.com/docs/lol#league-client-api).

## Optional template detection

Create a real screenshot template using [templates/README.md](templates/README.md), then calibrate the scan ROI:

```powershell
.\.venv\Scripts\python.exe calibrate.py "my game.mp4" --time 323 --save-template templates/kill_template.png
.\.venv\Scripts\python.exe calibrate.py "my game.mp4" --time 323
.\.venv\Scripts\python.exe auto_kill.py "my game.mp4" --detect-only --debug
.\.venv\Scripts\python.exe auto_kill.py "D:\Recordings"
```

Copy the normalized ROI from the second command into `config.yaml`. No template is distributed. Without a real template, template-mode scanning stops before reading the recording. Event-import mode does not need a template or ROI calibration.

Detection samples every 0.25 seconds by default. Sequential `grab()` avoids repeated keyframe seeking; frames are retrieved only at sample points and matching processes a grayscale ROI. Compressed video still requires decoding dependent frames. OpenCV PTS is preferred, with frame-index/FPS fallback; constant-frame-rate recordings are recommended.

Continuous matching hits form one event window; nearby windows merge under cooldown. The highest-correlation sample is retained. A persistent banner does not create another event every cooldown. Correlation is not a probability, and the UI peak may occur after the actual kill.

## Configuration

`config.example.yaml` and `workflow.example.yaml` are portable defaults. Create local copies as shown above. Local configurations, recordings, templates, event exports, logs, caches, and rendered clips are excluded from Git.

| Setting | Purpose |
|---|---|
| `scan_interval` | Template sample interval, positive seconds |
| `match_threshold` | Correlation threshold, 0–1; tune on your recordings |
| `kill_cooldown` | Group nearby template hit windows |
| `pre_kill_seconds`, `post_kill_seconds` | Fallback window for event types without a specific setting |
| `event_windows` | Independent `pre` / `post` seconds for `kill` and `death` |
| `merge_gap` | Maximum gap between windows merged in a montage |
| `cut_mode` | `fast` stream copy or `accurate` re-encoding |
| `video_extensions` | Supported top-level video extensions |
| `roi` | Normalized `x1`, `y1`, `x2`, `y2`; calibrate for your UI |
| `template.path`, `template.scales` | Template image and scale factors; path relative to the configuration |
| `debug.max_images`, `debug.sample_images` | Per-scan screenshot limits |

`workflow.yaml` controls the client path, output root, encoding mode, montage creation, and automatic folder opening. The wizard defaults to accurate H.264/AAC export with NVENC, falling back to libx264 on failure. Fast stream copy may start at a nearby keyframe. Same-name legacy CLI clips are replaced only after a new clip is successfully encoded; stale unrelated clips are not removed.

## Troubleshooting and boundaries

- Client HTTP 404 immediately after login: wait for the home screen to finish loading.
- No client lockfile: keep the League client open and check `client_dir`.
- Missing FFmpeg: install a system binary or `requirements-portable.txt`.
- Incorrect timestamps: check the selected match and recording/game-time alignment.
- File chooser unavailable: drag the recording onto the launcher or provide its quoted path on the command line.
- Template false positives: a generic kill icon does not identify the killer. Use a personal kill message, correct ROI/scale, and inspect debug images.
- Template misses: language, HUD scale, resolution, animation, and multikill messages can alter the UI. Recreate the template when needed.
- Corrupted videos fail independently in folder template-mode processing; later files continue.

Template detection caches include video path/size/mtime, detector parameters, scales, template SHA-256, and algorithm version. Clip-setting changes reuse detection results. `--force` resamples; `--debug` bypasses cache to save bounded images and stream confidence CSV. Changing file contents while deliberately preserving size and modification time requires `--force`.

## Development

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q auto_kill.py calibrate.py fetch_events.py make_clips.py src
```

Tests cover timing, ROI, configuration, event grouping, window merging, manual overrides, cache invalidation, Unicode paths, bounded screenshots, corrupted-file isolation, client event parsing, workflow choices, and separate clips versus montage ranges. See [VALIDATION.md](VALIDATION.md) for actual verification and remaining limitations.

Source modules are small and separate detection, event import, video sampling, clipping, and the wizard. No model or GPU dependency is required for detection; the NVIDIA GPU is used only when available for encoding.

LoL Kill Clipper is not endorsed by Riot Games and does not reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games and all associated properties are trademarks or registered trademarks of Riot Games, Inc.
