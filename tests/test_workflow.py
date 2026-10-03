from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import pytest
from src.config import load_config
from src.workflow import recording_offset, saved_job, source_key, unique_output, export_package, clip_name, run_workflow, choose_match


def test_offset_human_input():
    args=SimpleNamespace(time_offset=None,recording_start='1：46')
    assert recording_offset(args)==-106
    args.recording_start=None
    with patch('builtins.input',side_effect=['bad','01:46']):
        assert recording_offset(args)==-106
    with patch('builtins.input',return_value='offset:20'):
        assert recording_offset(args)==20


def test_offset_mutual_exclusion():
    with pytest.raises(ValueError):
        recording_offset(SimpleNamespace(time_offset=20,recording_start='01:46'))


def test_saved_job_invalidates_source(tmp_path):
    video=tmp_path/'录像.mp4'
    video.write_bytes(b'test')
    events=tmp_path/'events.json'
    events.write_text('{"selection":"all"}')
    job=tmp_path/'job.json'
    job.write_text(json.dumps({'source':source_key(video),'events_file':str(events),'offset':-106,'match_id':1}))
    assert saved_job(job,source_key(video)) is not None
    video.write_bytes(b'changed')
    assert saved_job(job,source_key(video)) is None


def test_preserves_previous_export(tmp_path):
    first=unique_output(tmp_path,'测试')
    (first/'keep.txt').write_text('old work')
    second=unique_output(tmp_path,'测试')
    assert second!=first and (first/'keep.txt').read_text()=='old work'


def test_clip_name_order_and_kind():
    events=[{'kind':'kill','game_time':135.192},{'kind':'death','game_time':202.733}]
    assert clip_name(2,{'event_indices':[1]},events).startswith('002_死亡1_')


def test_package_keeps_all_individual_events_and_merges_montage(tmp_path):
    video=tmp_path/'录像 空格.mp4'
    video.write_bytes(b'unit test placeholder')
    event_file=tmp_path/'input.json'
    event_file.write_text(json.dumps({'schema':'lol-clipper-events-v1','match_id':1,'selection':'all','events':[
        {'kind':'kill','game_time':50},{'kind':'assist','game_time':60},{'kind':'kill','game_time':200}]}))
    config=load_config(Path(__file__).resolve().parents[1]/'config.example.yaml')
    calls=[]
    def fake_cut(video,output,clips,mode,executable,names=None):
        output.mkdir(parents=True,exist_ok=True)
        calls.append(clips)
        result=[]
        for i,clip in enumerate(clips):
            path=output/(names[i] if names else f'kill_{i+1:03}.mp4')
            path.write_bytes(b'fake unit test output')
            result.append({**clip,'path':str(path),'codec':'test'})
        return result
    def fake_combine(exports,path,executable):
        path.write_bytes(b'fake combined unit test output')
    with patch('src.workflow.check_ffmpeg',return_value='ffmpeg'), \
         patch('src.workflow.open_video',return_value=(SimpleNamespace(release=lambda:None),SimpleNamespace(duration=150))), \
         patch('src.workflow.cut_clips',side_effect=fake_cut), \
         patch('src.workflow.combine_clips',side_effect=fake_combine):
        output=export_package(video,event_file,0,config,tmp_path/'exports','accurate',True,1)
    manifest=json.loads((output/'export.json').read_text(encoding='utf-8'))
    assert len(manifest['clips'])==2
    assert '助攻' in manifest['clips'][1]['path']
    assert manifest['clips'][1]['start']==45
    assert len(manifest['skipped_events'])==1
    assert len(calls[0])==2 and len(calls[1])==1
    assert len(manifest['montage_ranges'])==1
    assert (output/'全部事件合集.mp4').is_file()
    assert (output/'片段清单.csv').read_bytes().startswith(b'\xef\xbb\xbf')
    assert not list(output.glob('.montage_*'))


def test_wizard_reuses_successful_choice_without_client(tmp_path):
    video=tmp_path/'video.mp4'
    video.write_bytes(b'test')
    events=tmp_path/'events.json'
    events.write_text('{"selection":"all"}')
    args=SimpleNamespace(video=video,config=Path(__file__).resolve().parents[1]/'config.example.yaml',
        reselect=False,events=None,match_id=None,recording_start=None,time_offset=None,
        output=tmp_path/'out',client_dir=None,no_open=True)
    old={'source':source_key(video),'events_file':str(events),'offset':-106,'match_id':1}
    with patch('src.workflow.saved_job',return_value=old), \
         patch('src.workflow.Client',side_effect=AssertionError('Must not reconnect')), \
         patch('src.workflow.export_package',return_value=tmp_path/'out') as export, \
         patch('src.workflow.write_json'):
        assert run_workflow(args)==0
        assert export.call_args.args[2]==-106


def test_match_selector_validates_index():
    def get(endpoint):
        if 'champion-summary' in endpoint:
            return [{'id':266,'name':'亚托克斯'}]
        return {'games':{'games':[{'gameId':123,'gameCreationDate':'2026-10-03T02:41:17Z',
            'gameDuration':212,'gameMode':'PRACTICETOOL','participants':[{'championId':266,'stats':{'kills':1,'deaths':1,'assists':0}}]}]}}
    with patch('builtins.input',side_effect=['0','1']):
        assert choose_match(SimpleNamespace(get=get),{'puuid':'test'})==123


def test_old_cache_refreshes_assists_without_reentering_alignment(tmp_path):
    video=tmp_path/'video.mp4'
    video.write_bytes(b'test')
    events=tmp_path/'events.json'
    events.write_text('{"selection":"both"}')
    args=SimpleNamespace(video=video,config=Path(__file__).resolve().parents[1]/'config.example.yaml',
        reselect=False,events=None,match_id=None,recording_start=None,time_offset=None,
        output=tmp_path/'out',client_dir=None,no_open=True)
    old={'source':source_key(video),'events_file':str(events),'offset':-106,'match_id':123}
    def get(endpoint):
        if 'current-summoner' in endpoint:
            return {'puuid':'self'}
        if 'game-timelines' in endpoint:
            return {'frames':[{'events':[{'type':'CHAMPION_KILL','killerId':4,'victimId':5,
                'assistingParticipantIds':[2],'timestamp':135000}]}]}
        return {'participantIdentities':[{'participantId':2,'player':{'puuid':'self'}}]}
    with patch('src.workflow.saved_job',return_value=old), \
         patch('src.workflow.find_lockfile',return_value=tmp_path/'lockfile'), \
         patch('src.workflow.Client',return_value=SimpleNamespace(get=get)), \
         patch('src.workflow.choose_match',side_effect=AssertionError('Must reuse match')), \
         patch('builtins.input',side_effect=AssertionError('Must reuse alignment')), \
         patch('src.workflow.export_package',return_value=tmp_path/'out') as export, \
         patch('src.workflow.write_json') as write:
        assert run_workflow(args)==0
        assert export.call_args.args[2]==-106
        data=write.call_args_list[0].args[1]
        assert data['selection']=='all' and data['events'][0]['kind']=='assist'


def test_legacy_config_inherits_kill_window_for_assists():
    from src.config import validate
    config=load_config(Path(__file__).resolve().parents[1]/'config.example.yaml')
    del config['event_windows']['assist']
    config['event_windows']['kill']={'pre':25,'post':7}
    assert validate(config)['event_windows']['assist']=={'pre':25,'post':7}
