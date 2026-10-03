"""List recent matches / export exact kill or death events from local client."""
import argparse
from pathlib import Path
from urllib.parse import quote
from src.events import extract_events
from src.lcu import Client, find_lockfile, own_participant
from src.utils import timestamp, write_json


def main() -> int:
    cli = argparse.ArgumentParser(description='Read recent match events from the logged-in LoL client (no Akari export needed).')
    cli.add_argument('--client-dir', type=Path, help='LoL installation folder or lockfile path')
    cli.add_argument('--list', action='store_true', help='List recent matches (default if no match selected)')
    cli.add_argument('--match-id', type=int, help='Match gameId from the list')
    cli.add_argument('--participant-id', type=int, help='Override player slot; normally detected automatically')
    cli.add_argument('--kind', choices=['kill', 'death', 'both'], default='kill')
    cli.add_argument('--output', type=Path, default=Path('events.json'))
    args = cli.parse_args()
    try:
        if args.match_id is not None and args.match_id <= 0:
            raise ValueError('--match-id must be positive')
        client = Client(find_lockfile(args.client_dir))
        summoner = client.get('/lol-summoner/v1/current-summoner')
        if args.list or args.match_id is None:
            puuid = summoner.get('puuid')
            if not puuid:
                raise ValueError('Player identity unavailable; wait until client login completes')
            history = client.get(f'/lol-match-history/v1/products/lol/{quote(puuid, safe="")}/matches?begIndex=0&endIndex=20')
            games = history.get('games', {}).get('games')
            if not isinstance(games, list):
                raise ValueError('Unexpected match history format')
            print('MATCH ID | DATE | MODE | DURATION | CHAMPION ID | K/D/A')
            for game in games:
                participants = game.get('participants', [])
                player = participants[0] if len(participants) == 1 else {}
                stats = player.get('stats', {})
                print(f'{game.get("gameId")} | {game.get("gameCreationDate", "?")} | {game.get("gameMode", "?")} | '
                      f'{timestamp(game.get("gameDuration", 0))} | {player.get("championId", "?")} | '
                      f'{stats.get("kills", "?")}/{stats.get("deaths", "?")}/{stats.get("assists", "?")}')
            if not games:
                print('No recent matches available.')
            return 0
        detail = client.get(f'/lol-match-history/v1/games/{args.match_id}')
        participant = args.participant_id if args.participant_id is not None else own_participant(detail, summoner)
        timeline = client.get(f'/lol-match-history/v1/game-timelines/{args.match_id}')
        events = extract_events(timeline, participant, args.kind)
        write_json(args.output, {'schema': 'lol-clipper-events-v1', 'match_id': args.match_id,
                                'participant_id': participant, 'selection': args.kind, 'events': events})
        for event in events:
            print(f'{timestamp(event["game_time"])} {event["kind"]}')
        print(f'Saved {len(events)} events to {args.output}. Confirm the match and video time offset before cutting.')
        return 0
    except Exception as exc:
        print(f'Error: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
