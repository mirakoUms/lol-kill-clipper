"""Read-only localhost League Client API. Credentials never leave this process."""
import base64
import json
import os
from pathlib import Path
import ssl
import subprocess
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPSHandler, ProxyHandler, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def find_lockfile(explicit: Path | None = None) -> Path:
    if explicit is not None:
        path = explicit / 'lockfile' if explicit.is_dir() else explicit
        if not path.is_file():
            raise ValueError(f'Client lockfile not found: {path}. Keep LoL client open and logged in.')
        return path
    candidates = []
    if os.name == 'nt':
        # Only paths are returned; do not dump process command lines with tokens.
        command = "@(Get-Process LeagueClient,LeagueClientUx -ErrorAction SilentlyContinue | ForEach-Object { $_.Path }) | ConvertTo-Json -Compress"
        try:
            process = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                                     capture_output=True, text=True, timeout=15)
            paths = json.loads(process.stdout or '[]')
            if isinstance(paths, str):
                paths = [paths]
            if isinstance(paths, list):
                candidates.extend(Path(path).parent/'lockfile' for path in paths if path)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    for drive in ('C:', 'D:', 'E:', 'F:'):
        candidates.append(Path(drive + '/Riot Games/League of Legends/lockfile'))
    for path in candidates:
        if path.is_file():
            return path
    raise ValueError('Cannot locate LoL client. Use --client-dir "D:\\Riot Games\\League of Legends" and keep client logged in.')


def connection(path: Path) -> tuple[int, str]:
    fields = path.read_text(encoding='utf-8').strip().split(':')
    if len(fields) != 5 or fields[4] != 'https':
        raise ValueError('Invalid client lockfile; restart the LoL client')
    try:
        port = int(fields[2])
    except ValueError:
        raise ValueError('Invalid client port') from None
    if not 1 <= port <= 65535 or not fields[3]:
        raise ValueError('Invalid client connection settings')
    auth = base64.b64encode(('riot:' + fields[3]).encode('utf-8')).decode('ascii')
    return port, auth


class Client:
    def __init__(self, lockfile: Path):
        self.port, self._auth = connection(lockfile)
        # Self-signed LCU certificate: exception confined to literal loopback.
        self._opener = build_opener(ProxyHandler({}), NoRedirect(),
                                   HTTPSHandler(context=ssl._create_unverified_context()))

    def get(self, endpoint: str):
        if not endpoint.startswith('/lol-') or '?' in endpoint.split('/')[0]:
            raise ValueError('Invalid client endpoint')
        request = Request(f'https://127.0.0.1:{self.port}{endpoint}',
                          headers={'Authorization': 'Basic ' + self._auth, 'Accept': 'application/json'})
        try:
            with self._opener.open(request, timeout=20) as response:
                return json.load(response)
        except HTTPError as exc:
            raise ValueError(f'Client returned HTTP {exc.code} for {endpoint}. Check login/match availability; local API may have changed.') from None
        except (URLError, TimeoutError, OSError):
            raise ValueError('Cannot connect to local LoL client. Keep it open and logged in; restart if needed.') from None


def own_participant(detail: dict, summoner: dict) -> int:
    identities = detail.get('participantIdentities', [])
    for identity in identities:
        player = identity.get('player', {})
        puuid_match = bool(summoner.get('puuid')) and player.get('puuid') == summoner['puuid']
        id_match = bool(summoner.get('summonerId')) and str(player.get('summonerId')) == str(summoner['summonerId'])
        if puuid_match or id_match:
            return identity['participantId']
    raise ValueError('Logged-in player not found in this match. Select your own match or use --participant-id explicitly.')
