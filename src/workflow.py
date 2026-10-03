"""One-match local publishing workflow; no GUI framework or extra dependencies."""
import csv
import hashlib
import json
import math
import os
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
LABELS = {'kill': '击杀', 'death': '死亡'}


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
    for key in ('combine', 'open_folder'):
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
    label = '_'.join(f'{LABELS[kind]}{kinds.count(kind)}' for kind in ('kill','death') if kind in kinds)
    first = events[clip['event_indices'][0]]
    game_time = timestamp(first['game_time']).replace(':','-')
    return f'{index:03}_{label}_{game_time}.mp4'


def export_package(video: Path, event_file: Path, offset: float, config: dict,
                   root: Path, mode: str, combine: bool, match_id: int | None) -> Path:
    executable = check_ffmpeg()
    cap, info = open_video(video)
    cap.release()
    # Events before/after this recording are expected for a partial recording.
    # Filter them explicitly and report counts; never silently omit them.
    data = json.loads(event_file.read_text(encoding='utf-8-sig'))
    if data.get('selection') != 'both':
        raise ValueError('一键导出需要全部击杀/死亡数据（selection: both）；请重新读取 --kind both')
    selected, outside = [], 0
    for item in data.get('events', []):
        value = item.get('game_time')
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value < 0:
            raise ValueError('事件文件包含非法游戏时间')
        if 0 <= value+offset < info.duration:
            selected.append(item)
        else:
            outside += 1
    if outside:
        print(f'有 {outside} 个事件发生在录像覆盖范围之外，无法剪出，已列入清单。请核对录制开始时间。')
    if not selected:
        raise ValueError('录像时间范围内没有击杀/死亡事件，请检查对局和录制起始时间')
    output = unique_output(root, f'{video.stem}_对局{match_id or "offline"}')
    setup_logging(output/'logs')
    selected_file = output/'events.json'
    write_json(selected_file,{**data,'events':selected})
    events = import_events(selected_file,offset,info.duration)
    clips = []
    for index,event in enumerate(events):
        clip = merge_clips([event],info.duration,config['pre_kill_seconds'],config['post_kill_seconds'],
                           0,config['event_windows'])[0]
        clip['event_indices'] = [index]
        clips.append(clip)
    names = [clip_name(i,clip,events) for i,clip in enumerate(clips,1)]
    print(f'\n录像内共 {sum(e["kind"]=="kill" for e in events)} 次击杀、{sum(e["kind"]=="death" for e in events)} 次死亡。')
    print(f'开始导出全部 {len(clips)} 个独立切片…')
    exports = cut_clips(video,output,clips,mode,executable,names=names)
    merged = merge_clips(events,info.duration,config['pre_kill_seconds'],config['post_kill_seconds'],
                         config['merge_gap'],config['event_windows'])
    if combine:
        if merged == clips:
            combine_clips(exports,output/'全部事件合集.mp4',executable)
        else:
            # Temporary merged material only serves the montage; keep every
            # independent event clip for editing and avoid repeated footage.
            with tempfile.TemporaryDirectory(prefix='.montage_',dir=output) as temporary_dir:
                temporary_root = Path(temporary_dir).resolve()
                if not temporary_root.is_relative_to(output.resolve()):
                    raise ValueError('Temporary montage directory outside export folder')
                montage_exports = cut_clips(video,temporary_root,merged,mode,executable)
                combine_clips(montage_exports,temporary_root/'all_events.mp4',executable)
                (temporary_root/'all_events.mp4').replace(output/'全部事件合集.mp4')
    rows = []
    for i, clip in enumerate(exports,1):
        rows.append({'序号':i,'文件':Path(clip['path']).name,
                     '事件':'、'.join(f'{LABELS[events[n]["kind"]]} {timestamp(events[n]["game_time"])}' for n in clip['event_indices']),
                     '录像开始':timestamp(clip['start']),'录像结束':timestamp(clip['end']),
                     '时长秒':round(clip['end']-clip['start'],3)})
    with (output/'片段清单.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_json(output/'export.json',{'source':source_key(video),'match_id':match_id,'time_offset':offset,
               'event_windows':config['event_windows'],'events':events,'skipped_events':[e for e in data['events'] if e not in selected],
               'clips':[{**clip,'path':Path(clip['path']).name} for clip in exports],
               'montage_ranges':merged,
               'combined':'全部事件合集.mp4' if combine else None,'status':'complete'})
    print(f'\n完成：{len(exports)} 个独立切片' + (' + 1 个合集' if combine else ''))
    print(f'输出文件夹：{output}')
    return output


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
            timeline = client.get(f'/lol-match-history/v1/game-timelines/{match_id}')
            events = extract_events(timeline,participant,'both')
            event_file = PROJECT/'cache'/'workflow'/f'{digest}_{match_id}_events.json'
            write_json(event_file,{'schema':'lol-clipper-events-v1','match_id':match_id,
                                  'participant_id':participant,'selection':'both','events':events})
        offset = recording_offset(args)
    root = args.output.resolve() if args.output else (PROJECT/settings['output_dir']).resolve()
    output = export_package(video,event_file,offset,config,root,settings['cut_mode'],settings['combine'],match_id)
    # Remember only a successfully exported choice, never a failed alignment.
    write_json(job_file,{'source':key,'events_file':str(event_file.resolve()),'offset':offset,'match_id':match_id})
    if settings['open_folder'] and not args.no_open and os.name == 'nt':
        try:
            os.startfile(str(output))
        except OSError:
            print('无法自动打开文件夹，可复制上面的输出路径打开。')
    return 0
