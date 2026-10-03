import pytest
from src.clipper import merge_clips
from src.overrides import parse_time, load_overrides
from src.config import load_config, validate
from pathlib import Path


def test_different_windows():
    events=[{'time':100,'kind':'kill'}, {'time':200,'kind':'death'}]
    clips=merge_clips(events,300,8,5,0,{'kill':{'pre':15,'post':5},'death':{'pre':40,'post':5}})
    assert [(c['start'],c['end']) for c in clips]==[(85,105),(160,205)]


def test_long_death_window_reorders_and_merges():
    events=[{'time':50,'kind':'kill'}, {'time':70,'kind':'death'}]
    clips=merge_clips(events,100,8,5,0,{'death':{'pre':60,'post':5}})
    assert clips==[{'start':10,'end':75,'event_indices':[0,1]}]


def test_manual_override(tmp_path):
    path=tmp_path/'overrides.yaml'
    path.write_text('events:\n  2:\n    start: "00:30.000"\n')
    clips=merge_clips([{'time':20},{'time':100,'kind':'death'}],120,8,5,0,overrides=load_overrides(path))
    assert clips[1]['start']==30 and clips[1]['end']==105


@pytest.mark.parametrize('override', [{2:{'start':0}}, {1:{'start':21}}, {1:{'end':19}}, {1:{'end':101}}])
def test_invalid_override(override):
    with pytest.raises(ValueError):
        merge_clips([{'time':20}],100,8,5,0,overrides=override)


def test_clamp_to_video():
    assert merge_clips([{'time':5,'kind':'death'}],10,8,5,0,{'death':{'pre':40,'post':5}})[0]['start']==0


@pytest.mark.parametrize('value', [True, -1, float('nan'), '01:60', '01:60:00', 'abc'])
def test_bad_time(value):
    with pytest.raises(ValueError):
        parse_time(value)


def test_timestamp_formats():
    assert parse_time('01:46')==106
    assert parse_time('01:01:46.5')==3706.5
    assert parse_time(45)==45


def test_invalid_window_config():
    config=load_config(Path(__file__).resolve().parents[1]/'config.example.yaml')
    config['event_windows']['death']['pre']=-1
    with pytest.raises(ValueError):
        validate(config)
