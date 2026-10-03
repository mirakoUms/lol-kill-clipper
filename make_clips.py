"""Small Windows export wizard: select video, match, game time at recording start."""
import argparse
import sys
from pathlib import Path


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    cli = argparse.ArgumentParser(description='一键导出全部击杀/死亡：选录像 → 选对局 → 填录制开始时的游戏时间')
    cli.add_argument('video', nargs='?', type=Path, help='录像路径；也可拖到 start_clips.cmd，省略时弹出文件选择器')
    cli.add_argument('--match-id', type=int, help='已知的对局 ID，可跳过选择')
    cli.add_argument('--recording-start', help='录像第 0 秒对应的游戏时间，例如 01:46')
    cli.add_argument('--time-offset', type=float, help='高级：录像时间减游戏时间，可正可负；不能与 recording-start 同时用')
    cli.add_argument('--events', type=Path, help='离线使用已保存的 both 事件 JSON')
    cli.add_argument('--client-dir', type=Path, help='覆盖 workflow.yaml 中的客户端路径')
    cli.add_argument('--output', type=Path, help='输出根目录')
    cli.add_argument('--reselect', action='store_true', help='重新选择对局和时间，不复用这段录像的设置')
    cli.add_argument('--no-open', action='store_true', help='完成后不打开文件夹')
    cli.add_argument('--config', type=Path, default=Path(__file__).parent/'config.yaml')
    args = cli.parse_args()
    try:
        from src.workflow import run_workflow
        return run_workflow(args)
    except KeyboardInterrupt:
        print('\n已取消。')
        return 1
    except Exception as exc:
        print(f'无法完成导出：{exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
