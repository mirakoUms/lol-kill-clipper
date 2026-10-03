# Match events without template matching

This tool reads historical match events from the logged-in local League client. It does not scrape or operate Akari. A Riot developer API key is not required for this local client workflow.

Local endpoints are version-dependent and are not an officially supported third-party contract. Akari may use other data sources, so a failed request here does not prove that the data is unavailable everywhere.

## List recent games

```powershell
.\.venv\Scripts\python.exe fetch_events.py --client-dir "C:\Riot Games\League of Legends" --list
```

Choose the match corresponding to your recording using its date, duration, mode, and K/D/A. The standalone list prints the timestamp returned by the client; the wizard renders dates in Japan time. The tool does not silently pick the newest game.

## Export events

Replace `123456789` with the actual game ID:

```powershell
.\.venv\Scripts\python.exe fetch_events.py --client-dir "C:\Riot Games\League of Legends" --match-id 123456789 --kind all --output events.json
```

The standalone exporter defaults to `--kind kill`. Use `death` for deaths, `assist` for assists, `both` for kills/deaths only, or `all` for the complete publishing workflow. Assists are selected from `assistingParticipantIds`; kills/deaths take precedence to avoid duplicate roles. The logged-in player is identified by PUUID or summoner ID, then events are selected using their killer/victim participant IDs. Explicit `--participant-id` is available for known player slots; do not guess a slot.

```json
{
  "schema": "lol-clipper-events-v1",
  "match_id": 123456789,
  "participant_id": 1,
  "selection": "all",
  "events": [
    {"game_time": 135.192, "kind": "kill", "killer_id": 1, "victim_id": 2}
  ]
}
```

Times are seconds after game start. No credentials are stored in the exported file.

## Align to the recording

**Video time = game time + offset.**

If the recording starts at game `01:46`, offset is `-106`. A game event at `02:15.192` is then at recording `00:29.192`. If loading footage precedes the game, the offset can be positive.

Check at least one event near the beginning and one near the end of a continuous recording. Pauses, replay speed changes, and missing sections can invalidate a constant offset.

```powershell
.\.venv\Scripts\python.exe auto_kill.py "my game.mp4" --events events.json --time-offset -106 --detect-only
.\.venv\Scripts\python.exe auto_kill.py "my game.mp4" --events events.json --time-offset -106 --cut-mode accurate --combine
```

This mode does not load templates, run cooldown grouping, or use the detector cache. `confidence` is `null`, because events are not template estimates. The advanced CLI rejects events outside the video; the everyday wizard explicitly filters and reports uncovered events in partial recordings.

The advanced CLI's legacy JSON field is named `kills` even when deaths are included; inspect each event's `kind`. Legacy clip names use `kill_...`; the everyday wizard creates descriptive kill/death/assist labels instead.

## Optional manual start/end

Copy `event_overrides.example.yaml` to `event_overrides.yaml`:

```yaml
events:
  2:
    start: "01:10"
    end: "01:41.733"
```

Event numbers correspond to the chronological console list, starting at 1. Boundaries use **video time**, not game time. The interval must contain the event and stay within the recording. Omit one boundary to retain its configured default. Recheck event numbers after changing selection or input.

```powershell
.\.venv\Scripts\python.exe auto_kill.py "my game.mp4" --events events.json --time-offset -106 --event-overrides event_overrides.yaml --cut-mode accurate --combine
```

Manual overrides are supported by the advanced CLI, not the drag-and-drop wizard.

## Connection and data limits

The client must remain open and logged in while fetching data. A missing lockfile means the installation path or client state needs checking. HTTP 404 can indicate incomplete login, unavailable historical data, or changed local endpoints.

Authentication is read from the client's temporary lockfile and retained in process memory. GET requests are confined to literal `127.0.0.1`; proxies and redirects are disabled. The local self-signed certificate is accepted only for this connection. Do not publish lockfile contents or client credentials.

Historical timeline data inspected during development had roughly one-minute position snapshots and precise kill/death/assist timestamps, without continuous health or per-hit damage timestamps. The tool therefore uses configurable fixed windows, not automatic combat-start inference.

See [Riot's local client API documentation](https://developer.riotgames.com/docs/lol#league-client-api) and [VALIDATION.md](VALIDATION.md).

Assists use a 15-second lead-in and 5-second follow-up by default. Existing configurations without an assist window inherit the kill window. Old wizard caches are refreshed from the client using the saved match and time alignment; old offline files must be re-exported with `--kind all`.
