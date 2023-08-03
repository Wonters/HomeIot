from crontab import CronTab
from pathlib import Path

PING = 10

crontab_file = Path('crontab')
crontab_file.touch(exist_ok=True)

with CronTab(tabfile='crontab') as cron:
    cron.remove_all()
    job = cron.new(command='python -c "from domeo import save, retrieve; save(retrieve())"')
    job.minute.every(PING)
