# Everyday export workflow

## First-time setup

Follow the installation steps in [README.md](README.md). Create local `config.yaml` and `workflow.yaml` from their example files. Set `client_dir` to the League installation directory, not the Akari directory.

After installing Python with PATH enabled, `setup.cmd` can create the environment and local configuration files for you without overwriting existing settings.

## Daily use

1. Open the League client and log in.
2. Drag your recording onto **start_clips.cmd**, or double-click the launcher and choose a file.
3. Select the matching game by date, duration, champion, and K/D/A. The list currently shows Japan time (UTC+9).
4. Enter the game clock at video time zero. For recording that starts at game time 1 minute 46 seconds, enter `01:46`.
5. Wait for export. The output folder opens automatically.

Successful settings are remembered for the same unchanged video. To choose a different match or alignment, run:

```powershell
.\.venv\Scripts\python.exe make_clips.py "my game.mp4" --reselect
```

The terminal launcher and prompts currently use Chinese. Select a match using its numbered row; input formats are numeric and the same in any language.

## Files to use for publishing

Each run saves only the final MP4 directly under `exports`, for example:

```text
2026-10-03_14-30-25_123456_Aatrox.mp4
```

The filename contains the current export date, Japan time (UTC+9) including microseconds, and the champion's English alias. Kills, deaths, and assists appear in chronological order; overlapping or nearby windows merge to avoid repeated footage. Intermediate clips are cleaned up automatically. Diagnostics stay in `cache/export_logs`.

The client supplies the English alias automatically. Older offline files may prompt once for the champion name; use `--champion Aatrox` to specify it without a prompt. The name is remembered with the recording settings.

Export retains audio and the original resolution/frame rate. It adds no watermarks, music, captions, or vertical crop, and does not upload anything automatically. Earlier exports are preserved.

## Current clip windows

Kills: 15 seconds before and 5 seconds after. Deaths: 40 seconds before and 5 seconds after. Change `event_windows` in `config.yaml` to adjust future exports. These are fixed windows; combat-start detection is not implemented.

## Recording alignment

- Recording starts at game `01:46`: enter `01:46`.
- Recording includes loading and game `00:00` appears at video `00:20`: enter `offset:20`.
- Recording starts at game `00:00`: press Enter.

This assumes one continuous recording of one match. Multiple matches or interrupted/accelerated replay recordings require separate alignment. Events outside a partial recording are explicitly reported and recorded in the manifest; events within the recording are all exported.

## Offline or scripted export

Export all three event types first, following [EVENTS_GUIDE.md](EVENTS_GUIDE.md), then:

```powershell
.\.venv\Scripts\python.exe make_clips.py "my game.mp4" --events events.json --recording-start 01:46
```

Once successful, re-export using only the video path:

```powershell
.\.venv\Scripts\python.exe make_clips.py "my game.mp4"
```

The file chooser requires Tk support. If unavailable, use drag-and-drop or a quoted path. If the client is still loading, wait for its home screen before retrying.

Assists use a 15-second lead-in and 5-second follow-up by default. Existing configurations without an assist window inherit the kill window. Old wizard caches are refreshed from the client using the saved match and time alignment; old offline files must be re-exported with `--kind all`.
