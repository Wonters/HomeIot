from crontab import CronTab

with CronTab(user='') as cron:
    cron.remove_all()
    # job = cron.new(command='curl http://127.0.0.1:9000/retrieve')
    # job.minute.every(1)
