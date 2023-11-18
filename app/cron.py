from crontab import CronTab

PING = 10

with CronTab(user="root") as cron:
    cron.remove_all()
    job = cron.new(command="/app/retrieve.sh")
    job.minute.every(PING)
