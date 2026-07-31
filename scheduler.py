from apscheduler.schedulers.background import BackgroundScheduler
from django_apscheduler.jobstores import DjangoJobStore
import subprocess
import sys
import os
from datetime import datetime


def sync_blacklisted_agents():
    print(f'[{datetime.now()}] Running weekly IRDAI sync...')
    result = subprocess.run(
        [sys.executable, 'auto_download_blacklisted.py'],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__))
    )
    print(result.stdout)
    if result.stderr:
        print('Errors:', result.stderr)
    os.makedirs('logs', exist_ok=True)
    with open('logs/sync_log.txt', 'a') as f:
        f.write(f'\n[{datetime.now()}] Sync run\n')
        f.write(result.stdout)
        if result.stderr:
            f.write(f'Errors: {result.stderr}')


def run_refresh_chips():
    print(f'[{datetime.now()}] Running refresh_chips...')
    result = subprocess.run(
        [sys.executable, 'manage.py', 'refresh_chips'],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__))
    )
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print('Errors:', result.stderr)

def start():
    scheduler = BackgroundScheduler()
    scheduler.add_jobstore(DjangoJobStore(), 'default')
    scheduler.add_job(
        sync_blacklisted_agents,
        'cron',
        day_of_week='sun',
        hour=9,
        minute=0,
        name='sync_blacklisted_agents',
        jobstore='default',
        replace_existing=True,
    )
    scheduler.add_job(
        run_refresh_chips,
        'cron',
        hour='0,12',
        minute=0,
        name='refresh_chips',
        jobstore='default',
        replace_existing=True,
    )
    scheduler.start()
    print('Scheduler started — IRDAI sync runs every Sunday at 9:00 AM, refresh_chips runs at 0:00 and 12:00')
