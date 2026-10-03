"""One-match local publishing workflow; no GUI framework or extra dependencies."""
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
import yaml
from src.config import load_config
from src.events import extract_events, import_events
from src.lcu import Client, find_lockfile, own_participant
from src.clipper import check_ffmpeg, merge_clips, cut_clips, combine_clips
from src.overrides import parse_time
from src.utils import setup_logging, timestamp, write_json
from src.video import open_video

PROJECT = Path(__file__).resolve().parents[1]
LABELS = {'kill': '击杀', 'death': '死亡', 'assist': '助攻'}


def choose_video() -> Path:
    try:
        import tkinter as tk
        from tkinter.filedialog import askopenfilename
        window = tk.Tk()
        window.withdraw()
        window.attributes('-topmost', True)
        try:
            selected = askopenfilename(title='选择要剪辑的 LoL 录像', initialdir=str(PROJECT),
                                      filetypes=[('游戏录像', '*.mp4 *.mkv *.mov'), ('所有文件', '*.*')])
        finally:
            window.destroy()
        if not selected:
            raise ValueError('没有选择录像，已取消')
        return Path(selected)
    except ImportError:
        entered = input('输入或拖入录像文件路径：').strip().strip('"')
        if not entered:
            raise ValueError('没有选择录像')
        return Path(entered)


def load_settings() -> dict:
    path = PROJECT/'workflow.yaml'
    if not path.is_file():
        path = PROJECT/'workflow.example.yaml'
    settings = yaml.safe_load(path.read_text(encoding='utf-8-sig'))
    if not isinstance(settings, dict) or settings.get('cut_mode') not in ('fast', 'accurate'):
        raise ValueError('workflow.yaml: cut_mode 必须是 fast 或 accurate')
    for key in ('client_dir', 'output_dir'):
        if not isinstance(settings.get(key), str) or not settings[key]:
            raise ValueError(f'workflow.yaml: {key} 必须是路径')
    for key in ('open_folder',):
        if not isinstance(settings.get(key), bool):
            raise ValueError(f'workflow.yaml: {key} 必须是 true 或 false')
    return settings


def local_date(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone(timedelta(hours=9))).strftime('%m-%d %H:%M')
    except (ValueError, AttributeError):
        return '?'


def choose_match(client: Client, summoner: dict) -> int:
    puuid = summoner.get('puuid')
    if not puuid:
        raise ValueError('客户端登录尚未完成，请稍后再试')
    history = client.get(f'/lol-match-history/v1/products/lol/{quote(puuid, safe="")}/matches?begIndex=0&endIndex=20')
    games = history.get('games', {}).get('games')
    if not isinstance(games, list) or not games:
        raise ValueError('没有可用的近期对局')
    champion_names = {}
    try:
        champions = client.get('/lol-game-data/assets/v1/champion-summary.json')
        if isinstance(champions,list):
            champion_names = {c['id']:c.get('name',str(c['id'])) for c in champions if isinstance(c,dict) and 'id' in c}
    except ValueError:
        pass
    print('\n选择录像对应的比赛（时间为日本时间）：')
    for index, game in enumerate(games, 1):
        participants = game.get('participants', [])
        player = participants[0] if len(participants) == 1 else {}
        stats = player.get('stats', {})
        mode = {'PRACTICETOOL':'训练模式','CLASSIC':'召唤师峡谷','ARAM':'大乱斗'}.get(game.get('gameMode'),game.get('gameMode','?'))
        print(f'{index:2}. {local_date(game.get("gameCreationDate"))}  {mode}  '
              f'{timestamp(game.get("gameDuration",0))}  '
              f'KDA {stats.get("kills","?")}/{stats.get("deaths","?")}/{stats.get("assists","?")}  '
              f'{champion_names.get(player.get("championId"), "英雄ID " + str(player.get("championId","?")))}')
    while True:
        answer = input('输入比赛序号（输入 q 取消）：').strip()
        if answer.lower() == 'q':
            raise ValueError('已取消')
        if answer.isdigit() and 1 <= int(answer) <= len(games):
            return int(games[int(answer)-1]['gameId'])
        print('请输入列表中的序号。')


def recording_offset(args) -> float:
    if args.time_offset is not None:
        if args.recording_start is not None or not math.isfinite(args.time_offset):
            raise ValueError('time-offset 必须是有限数字，且不能与 recording-start 同时使用')
        return args.time_offset
    if args.recording_start is not None:
        return -parse_time(args.recording_start)
    print('\n录像第 0 秒时，游戏右上角的计时是多少？例如 01:46。')
    print('如果录像包含加载画面且游戏尚未开始，请输入 offset:20（游戏 00:00 在录像第 20 秒）。')
    while True:
        answer = input('游戏时间（直接回车表示 00:00；q 取消）：').strip()
        if answer.lower() == 'q':
            raise ValueError('已取消')
        try:
            if answer.lower().startswith('offset:'):
                value = float(answer.split(':',1)[1])
                if not math.isfinite(value):
                    raise ValueError('偏移必须是有限数字')
                return value
            return -parse_time(answer or '00:00')
        except ValueError as exc:
            print(f'格式不正确：{exc}')


def source_key(video: Path) -> dict:
    stat = video.stat()
    return {'path':str(video.resolve()), 'size':stat.st_size, 'mtime_ns':stat.st_mtime_ns}


def saved_job(path: Path, key: dict) -> dict | None:
    try:
        job = json.loads(path.read_text(encoding='utf-8'))
        if job['source'] == key and math.isfinite(job['offset']) and Path(job['events_file']).is_file():
            return job
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def unique_output(root: Path, name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for index in range(1, 100000):
        candidate = root/(name if index == 1 else f'{name}_{index:03}')
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise ValueError('导出目录重名过多，请换一个输出目录')


def clip_name(index: int, clip: dict, events: list[dict]) -> str:
    kinds = [events[i]['kind'] for i in clip['event_indices']]
    label = '_'.join(f'{LABELS[kind]}{kinds.count(kind)}' for kind in ('kill','death','assist') if kind in kinds)
    first = events[clip['event_indices'][0]]
    game_time = timestamp(first['game_time']).replace(':','-')
    return f'{index:03}_{label}_{game_time}.mp4'


def champion_slug(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9 .'-]*", value.strip()):
        raise ValueError('请输入英雄英文名，例如 Aatrox 或 Miss Fortune')
    return re.sub(r"[^A-Za-z0-9]", '', value.strip())


def match_champion(client: Client, detail: dict, participant: int) -> str:
    players = detail.get('participants', detail.get('info', {}).get('participants', []))
    player = next((p for p in players if p.get('participantId') == participant), {})
    champion_id = player.get('championId')
    champions = client.get('/lol-game-data/assets/v1/champion-summary.json')
    champion = next((c for c in champions if c.get('id') == champion_id), {})
    alias = champion.get('alias')
    if not alias and champion_id:
        alias = client.get(f'/lol-game-data/assets/v1/champions/{champion_id}.json').get('alias')
    if not alias:
        raise ValueError('客户端缺少英雄英文名，请使用 --champion Aatrox 指定')
    return champion_slug(alias)


def export_package(video: Path, event_file: Path, offset: float, config: dict,
                   root: Path, mode: str, combine: bool, match_id: int | None,
                   champion: str) -> Path:
    champion = champion_slug(champion)
    executable = check_ffmpeg()
    cap, info = open_video(video)
    cap.release()
    data = json.loads(event_file.read_text(encoding='utf-8-sig'))
    if data.get('selection') != 'all':
        raise ValueError('需要全部击杀/死亡/助攻数据（selection: all）；请重新读取 --kind all')
    selected, outside = [], []
    for item in data.get('events', []):
        value = item.get('game_time')
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value < 0:
            raise ValueError('事件文件包含非法游戏时间')
        (selected if 0 <= value+offset < info.duration else outside).append(item)
    if outside:
        print(f'有 {len(outside)} 个事件在录像范围之外，请核对录制开始时间。')
    if not selected:
        raise ValueError('录像范围内没有击杀/死亡/助攻事件，请检查对局和录制起始时间')
    root.mkdir(parents=True, exist_ok=True)
    # Japan time, export date rather than match date; microseconds avoid collisions.
    name = datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d_%H-%M-%S_%f') + f'_{champion}.mp4'
    destination = root/name
    if destination.exists():
        raise ValueError('输出文件重名，请重新导出')
    log_root = PROJECT/'cache'/'export_logs'/destination.stem
    setup_logging(log_root)
    with tempfile.TemporaryDirectory(prefix='.montage_', dir=root) as temporary_dir:
        temporary_root = Path(temporary_dir).resolve()
        if not temporary_root.is_relative_to(root.resolve()):
            raise ValueError('Temporary montage directory outside export folder')
        selected_file = temporary_root/'events.json'
        write_json(selected_file, {**data, 'events':selected})
        events = import_events(selected_file, offset, info.duration)
        merged = merge_clips(events,info.duration,config['pre_kill_seconds'],config['post_kill_seconds'],
                             config['merge_gap'],config['event_windows'])
        print('\n' + '、'.join(f'{sum(e["kind"]==k for e in events)} 次{label}' for k,label in LABELS.items()))
        print(f'开始生成合集（{len(merged)} 段战斗画面）…')
        exports = cut_clips(video,temporary_root,merged,mode,executable)
        combined = temporary_root/'montage.mp4'
        combine_clips(exports,combined,executable)
        combined.replace(destination)
    write_json(log_root/'export.json', {'source':source_key(video),'match_id':match_id,
        'champion':champion,'time_offset':offset,'events':events,'skipped_events':outside,
        'montage_ranges':merged,'combined':str(destination),'status':'complete'})
    print(f'\n完成：{destination}')
    return destination


def run_workflow(args) -> int:
    settings = load_settings()
    video = (args.video or choose_video()).resolve()
    config = load_config(args.config)
    if not video.is_file() or video.suffix.lower() not in {e.lower() for e in config['video_extensions']}:
        raise ValueError('请选择支持的录像文件：MP4/MKV/MOV（或 config.yaml 中的扩展名）')
    key = source_key(video)
    digest = hashlib.sha256(str(video).encode('utf-8')).hexdigest()[:16]
    job_file = PROJECT/'cache'/'workflow'/f'{digest}.json'
    old = None if args.reselect else saved_job(job_file,key)
    explicit = any(value is not None for value in (args.events,args.match_id,args.recording_start,args.time_offset))
    if old and not explicit:
        cached = json.loads(Path(old['events_file']).read_text(encoding='utf-8-sig'))
        if cached.get('selection') != 'all':
            print('旧事件缓存未包含助攻，使用已保存的对局和时间重新读取客户端。')
            args.match_id, args.time_offset = old.get('match_id'), old['offset']
            old = None
    if old and not explicit:
        print('已找到这段录像之前的对局和时间设置，直接重新导出。要重新选择请加 --reselect。')
        event_file,offset,match_id = Path(old['events_file']),old['offset'],old.get('match_id')
    else:
        if args.events:
            event_file = args.events.resolve()
            data = json.loads(event_file.read_text(encoding='utf-8-sig'))
            match_id = data.get('match_id')
            if args.match_id is not None and args.match_id != match_id:
                raise ValueError('--match-id 与离线事件文件中的对局不同')
        else:
            print('读取 LoL 客户端，请保持登录…')
            client = Client(find_lockfile(args.client_dir or Path(settings['client_dir'])))
            summoner = client.get('/lol-summoner/v1/current-summoner')
            match_id = args.match_id if args.match_id is not None else choose_match(client,summoner)
            if isinstance(match_id,bool) or not isinstance(match_id,int) or match_id <= 0:
                raise ValueError('对局 ID 必须是正整数')
            detail = client.get(f'/lol-match-history/v1/games/{match_id}')
            participant = own_participant(detail,summoner)
            champion = getattr(args, 'champion', None)
            if not champion:
                try:
                    champion = match_champion(client, detail, participant)
                except (ValueError, OSError):
                    champion = None
            timeline = client.get(f'/lol-match-history/v1/game-timelines/{match_id}')
            events = extract_events(timeline,participant,'all')
            event_file = PROJECT/'cache'/'workflow'/f'{digest}_{match_id}_events.json'
            write_json(event_file,{'schema':'lol-clipper-events-v1','match_id':match_id,
                                  'participant_id':participant,'champion':champion,'selection':'all','events':events})
        offset = recording_offset(args)
    data = {} if getattr(args, 'champion', None) else json.loads(event_file.read_text(encoding='utf-8-sig'))
    champion = getattr(args, 'champion', None) or data.get('champion') or (old or {}).get('champion')
    if not champion:
        try:
            client = Client(find_lockfile(args.client_dir or Path(settings['client_dir'])))
            detail = client.get(f'/lol-match-history/v1/games/{match_id}')
            participant = data.get('participant_id') or own_participant(detail, client.get('/lol-summoner/v1/current-summoner'))
            champion = match_champion(client, detail, participant)
        except (ValueError, OSError):
            champion = input('请输入本局英雄英文名（例如 Aatrox）：').strip()
    champion = champion_slug(champion)
    root = args.output.resolve() if args.output else (PROJECT/settings['output_dir']).resolve()
    output = export_package(video,event_file,offset,config,root,settings['cut_mode'],True,match_id,champion)
    # Remember only a successfully exported choice, never a failed alignment.
    write_json(job_file,{'source':key,'events_file':str(event_file.resolve()),'offset':offset,'match_id':match_id,'champion':champion})
    if settings['open_folder'] and not args.no_open and os.name == 'nt':
        try:
            os.startfile(str(output.parent))
        except OSError:
            print('无法自动打开文件夹，可复制上面的输出路径打开。')
    return 0
