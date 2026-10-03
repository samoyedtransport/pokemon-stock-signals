"""Persistent runner for an awake computer or hosted background service."""
import argparse
import getpass
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


def run_loop(interval, stop, run_check, clock=time.monotonic):
    failures = 0
    while not stop.is_set():
        start = clock()
        code = run_check()
        failures = failures + 1 if code else 0
        # Repeated whole-job failures back off rather than hammering endpoints.
        delay = min(900, interval * 2 ** min(max(failures - 1, 0), 4))
        if stop.wait(max(1, delay - (clock() - start))):
            break


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--interval', type=int, default=60, help='Seconds between check starts (minimum 30; default 60)')
    parser.add_argument('--once', action='store_true', help='Run one check and exit')
    parser.add_argument('--dry-run', action='store_true', help='Do not send messages or advance alert state')
    args = parser.parse_args()
    if args.interval < 30:
        parser.error('Minimum interval is 30 seconds')
    root = Path(__file__).resolve().parent
    env = dict(os.environ)
    if not args.dry_run and not env.get('DISCORD_WEBHOOK_URL'):
        if not sys.stdin.isatty():
            raise SystemExit('Configure DISCORD_WEBHOOK_URL in the hosting service environment.')
        env['DISCORD_WEBHOOK_URL'] = getpass.getpass('Discord webhook URL (hidden; not saved): ').strip()
        if not env['DISCORD_WEBHOOK_URL']:
            raise SystemExit('Webhook is required for alerts.')
    # Keep operational history separate from checked-in code and search output.
    env.setdefault('MONITOR_DATA_DIR', str(root / '.state'))
    command = [sys.executable, '-u', str(root / 'monitor.py')]
    if args.dry_run:
        command.append('--dry-run')
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, lambda *_: stop.set())

    def check():
        try:
            return subprocess.run(command, cwd=root, env=env, timeout=180, check=False).returncode
        except subprocess.TimeoutExpired:
            print('Check timed out; the next cycle will retry.', flush=True)
            return 1

    if args.once:
        raise SystemExit(check())
    print(f'Continuous monitor starting: {args.interval}-second target interval. Keep this process running.', flush=True)
    run_loop(args.interval, stop, check)


if __name__ == '__main__':
    main()
