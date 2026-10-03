# Create a real personal-kill template

This directory intentionally contains no `kill_template.png`. UI language, game version, HUD scaling, resolution, and recording method affect matching. A made-up template would not validate detection.

1. Open your own recording and find a frame where **you** have killed an enemy and the personal kill notification is stable and clear.
2. Choose a UI fragment specific to your own kill, such as the personal "You have slain an enemy" message. The global kill feed contains other players' kills; a generic sword icon, enemy portrait, or kill word cannot establish that you were the killer.
3. Crop a small, distinctive, stable text/icon region. Avoid changing enemy names, portraits, battle backgrounds, flashes, and large animated areas. Too small a template can match unrelated UI; too large a template can include unstable content. Tune using real samples.
4. Use original recording pixels rather than a resized player screenshot or compressed chat image. The template must fit inside the scan ROI.
5. Save a PNG using the calibration tool:

```powershell
.\.venv\Scripts\python.exe calibrate.py "my game.mp4" --time 323 --save-template templates/kill_template.png
```

Drag over the **template fragment**, then press Enter. This saves corresponding original-frame pixels, even if the display preview is resized.

6. Run calibration again without `--save-template`; select a **larger scan ROI** containing all likely notification positions, then copy its normalized coordinates to `config.yaml`:

```powershell
.\.venv\Scripts\python.exe calibrate.py "my game.mp4" --time 323
```

7. Run detection without clipping:

```powershell
.\.venv\Scripts\python.exe auto_kill.py "my game.mp4" --detect-only --debug
```

Inspect `sample_*.jpg` for ROI placement, `detected_*.jpg` for genuine own-player kills, and `confidence.csv` for the separation between true and false matches. Sample images come from the beginning of the recording and need not contain kills. Screenshots are bounded per scan; old images may remain after repeated scans.

8. `match_threshold: 0.82` is a starting value, not a universal optimum. Check ROI and scale before lowering it for missed detections. Improve template distinctiveness before raising it for false positives. Correlation is **not** a probability. Verify multiple positive and negative moments manually.

Normalized ROI coordinates do not scale the template itself. For a 1080p template used in a 1440p recording with equivalent HUD scaling, try `template.scales: [1.0, 1.333333]`, or create a new screenshot. Different HUD scaling can require a new template regardless of resolution.

Ordinary personal-kill text may be replaced by double/triple/multikill messages. This version supports one template with multiple scales and does not infer multikill types. The preferred client-event workflow avoids this UI limitation and requires neither template nor ROI.

