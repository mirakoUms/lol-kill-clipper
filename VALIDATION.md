# Verification record

## Automated checks

Verified on Windows using Python 3.12 in the project virtual environment:

- `python -m pytest -q`: **61 passed** at the workflow release checkpoint.
- Compilation and imports for the CLI entry points and source modules.
- Help output for the template, calibration, event-fetch, and everyday-export CLIs.
- Configuration parsing and readable missing-template / missing-FFmpeg behavior.
- Random-texture synthetic video detection, peak grouping, bounded screenshots, Unicode paths, cache reuse/invalidation, and corrupt-video batch isolation.
- Separate kill/death windows, manual boundaries, interval merging, event parsing, offset handling, player identification, and loopback-only request construction.
- Wizard choices, remembered settings, preservation of previous exports, every-event independent output, and merged montage ranges.

Synthetic textures and mocked subprocess outputs are unit-test fixtures, not evidence of real LoL recognition accuracy.

## Real integration checks

A JP practice match was fetched from the local logged-in client. Its own-player kill and death timestamps matched the event display manually supplied during development. A continuous MP4 recording was aligned using its game-clock start time.

The everyday exporter produced:

- One independent kill clip, 20 seconds.
- One independent death clip, 45 seconds.
- A chronological montage, 65 seconds.

NVENC encoding succeeded. All three exported files passed a complete FFmpeg decode check, and the source audio track was retained. Both saved-event and live-client export paths completed successfully.

Personal recordings, actual match IDs, event exports, generated clips, and local paths are intentionally excluded from this repository.

## Remaining limits

- Real template-matching accuracy across LoL UI variations has not been established.
- File-picker, selectROI, and drag-and-drop desktop interaction have not been exhaustively tested manually.
- Other server regions, match types, client versions, variable-frame-rate recordings, and all codec combinations are not guaranteed by the checked practice match.
- NVENC fallback is unit-tested; hardware availability is determined by actual encoding attempts.
- Audio presence and decodability were checked, but perceptual synchronization has not been formally measured across arbitrary inputs.
- Combat-start inference, automatic chase segmentation, captions, vertical reframing, and publishing to video platforms are not implemented.

Repeat tests with `requirements-dev.txt`; see README for setup. Keep verification claims tied to these checks rather than assuming universal match-data or recognition support.

Assist regression checks cover participant IDs, role precedence, offline import, chronological independent exports, merged montage ranges, legacy window defaults, and automatic upgrade of old caches.
