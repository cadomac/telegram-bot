cd /home/asterisk/telegram-bot
source /etc/bash_completion.d/virtualenvwrapper
source /home/asterisk/.virtualenvs/telegram-bot/bin/activate
python send_nagios_alert.py &> /tmp/testing.log
deactivate
