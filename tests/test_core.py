from copy import deepcopy
from pathlib import Path
import json
from types import SimpleNamespace
from unittest.mock import patch
import cv2
import numpy as np
import pytest
from src.config import load_config, validate
from src.utils import timestamp, roi_pixels
from src.detector import group_candidates, load_templates, detect
from src.clipper import merge_clips, cut_clips, ffmpeg_command, check_ffmpeg
from src.cache import fingerprint, save_cache, read_cache
from src.pipeline import run

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config():
    return load_config(ROOT / 'config.example.yaml')


@pytest.mark.parametrize('seconds,expected', [(323.25,'00:05:23.250'), (3599.9996,'01:00:00.000'),
                                             (0,'00:00:00.000'), (90061.125,'25:01:01.125')])
def test_timestamp(seconds, expected):
    assert timestamp(seconds) == expected


def test_roi():
    assert roi_pixels({'x1':.7,'y1':0,'x2':1,'y2':.3},1920,1080) == (1344,0,1920,324)
    assert roi_pixels({'x1':0,'y1':0,'x2':1,'y2':1},2560,1440) == (0,0,2560,1440)


@pytest.mark.parametrize('key,value', [('scan_interval',0), ('scan_interval',float('nan')),
    ('match_threshold',1.1), ('kill_cooldown',-1), ('cut_mode','wrong'), ('merge_gap',True),
    ('video_extensions',[]), ('roi',{'x1':.9,'x2':.7,'y1':0,'y2':.3}),
    ('roi',{'x1':0,'x2':1.1,'y1':0,'y2':1}), ('debug',{'max_images':-1})])
def test_invalid_config(config, key, value):
    config[key] = value
    with pytest.raises(ValueError):
        validate(config)


def test_grouping_peak_and_persistent_ui():
    candidates = [{'time':i*.25, 'confidence':.94 if i==4 else .83} for i in range(40)]
    events = group_candidates(candidates,5,.25)
    assert len(events) == 1 and events[0]['time'] == 1 and events[0]['event_end'] == 9.75
    candidates += [{'time':15,'confidence':.85}]
    assert len(group_candidates(candidates,5,.25)) == 2


def test_cooldown():
    candidates = [{'time':1,'confidence':.83},{'time':4,'confidence':.94},{'time':9,'confidence':.88}]
    assert [e['time'] for e in group_candidates(candidates,5,.25)] == [4,9]


def test_merge():
    clips = merge_clips([{'time':323},{'time':329},{'time':400}],500,8,5,8)
    assert clips[0] == {'start':315,'end':334,'event_indices':[0,1]}
    assert len(clips) == 2
    assert merge_clips([{'time':1},{'time':99}],100,8,5,8)[-1]['end'] == 100
    assert merge_clips([],100,8,5,8) == []


def test_cache_invalidation(tmp_path, config):
    video = tmp_path / '录像 空格.mp4'
    template = tmp_path / 'template.png'
    video.write_bytes(b'video')
    template.write_bytes(b'template')
    config['template']['path'] = str(template)
    key = fingerprint(video,config)
    cache = tmp_path / 'cache.json'
    save_cache(cache,key,[],100)
    assert read_cache(cache,key) == ([],100.)
    changed = deepcopy(config)
    changed['pre_kill_seconds'] = 20
    assert fingerprint(video,changed) == key
    changed['match_threshold'] = .9
    assert read_cache(cache,fingerprint(video,changed)) is None
    template.write_bytes(b'new template')
    assert read_cache(cache,fingerprint(video,config)) is None
    video.write_bytes(b'changed video')
    assert fingerprint(video,config)['size'] != key['size']
    video.touch()
    assert fingerprint(video,config)['mtime_ns'] != key['mtime_ns']
    cache.write_text('bad JSON')
    assert read_cache(cache,key) is None


def test_missing_template(config):
    config['template']['path'] = str(ROOT / 'templates' / 'nonexistent_test_template.png')
    with pytest.raises(ValueError, match='Please create the template first'):
        load_templates(config['template'])


def test_missing_ffmpeg():
    with patch('src.clipper.shutil.which', return_value=None), patch.dict('sys.modules', {'imageio_ffmpeg': None}), pytest.raises(ValueError,match='FFmpeg not found'):
        check_ffmpeg()


def test_command_and_nvenc_fallback(tmp_path):
    clip = {'start':1.,'end':3.,'event_indices':[0]}
    video = tmp_path / '日本語 录像.mp4'
    attempts = []
    def fake_run(command, **kwargs):
        attempts.append(command)
        if 'h264_nvenc' in command:
            return SimpleNamespace(returncode=1,stderr=b'No capable devices found')
        Path(command[-1]).write_bytes(b'fake output for subprocess unit test')
        return SimpleNamespace(returncode=0,stderr=b'')
    with patch('src.clipper.subprocess.run', side_effect=fake_run):
        outputs = cut_clips(video,tmp_path/'clips',[clip],'accurate','ffmpeg')
    assert len(attempts)==2 and 'libx264' in attempts[1]
    assert str(video) in attempts[0]
    assert outputs[0]['codec']=='libx264'
    assert not list((tmp_path/'clips').glob('*.partial.mp4'))
    assert 'copy' in ffmpeg_command('ffmpeg',video,tmp_path/'x.mp4',clip,'copy')


@pytest.fixture
def synthetic(tmp_path, config):
    """Artificial test signal only: not a LoL template or accuracy evaluation."""
    rng = np.random.default_rng(123)
    template = rng.integers(0,256,(16,24),dtype=np.uint8)
    template_path = tmp_path/'测试 模板.png'
    cv2.imencode('.png',template)[1].tofile(template_path)
    video = tmp_path/'英雄 日本語 空格.avi'
    writer = cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'MJPG'),20,(160,120))
    assert writer.isOpened()
    for i in range(100):
        frame = rng.integers(0,100,(120,160,3),dtype=np.uint8)
        if 20 <= i < 35 or 70 <= i < 85:
            frame[20:36,100:124] = cv2.cvtColor(template,cv2.COLOR_GRAY2BGR)
        writer.write(frame)
    writer.release()
    config.update(roi={'x1':.5,'y1':0,'x2':1,'y2':.5},kill_cooldown=1.,match_threshold=.8)
    config['template']['path'] = str(template_path)
    config['video_extensions'] = ['.avi']
    config['debug'] = {'max_images':4,'sample_images':1}
    return video,config


def test_synthetic_detection_debug(synthetic, tmp_path):
    video,config = synthetic
    events,duration = detect(video,config,load_templates(config['template']),tmp_path/'debug')
    assert len(events) == 2 and duration == 5
    assert 1 <= events[0]['time'] < 1.75 and 3.5 <= events[1]['time'] < 4.25
    assert len(list((tmp_path/'debug').glob('*.jpg'))) <= 4
    assert (tmp_path/'debug'/'confidence.csv').is_file()


def test_batch_cache_corruption(synthetic, tmp_path):
    import yaml
    video,config = synthetic
    path = tmp_path/'settings.yaml'
    path.write_text(yaml.safe_dump(config),encoding='utf-8')
    args = SimpleNamespace(input=video,config=path,force=False,debug=False,detect_only=True)
    assert run(args) == 0
    assert run(args) == 0
    results = json.loads((tmp_path/'results.json').read_text(encoding='utf-8'))
    assert results[video.name]['detection_cached']
    (tmp_path/'损坏.avi').write_bytes(b'broken')
    args.input = tmp_path
    assert run(args) == 1
    results = json.loads((tmp_path/'results.json').read_text(encoding='utf-8'))
    assert results[video.name]['status']=='ok' and results['损坏.avi']['status']=='failed'
