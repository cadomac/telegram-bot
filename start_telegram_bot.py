import ConfigParser
import logging
import subprocess
import time
import datetime
import sqlite3
import mysql.connector
import collections
from telegram.ext import Job, Updater, CommandHandler
from telegram.replykeyboardmarkup import ReplyKeyboardMarkup

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

class TelegramBot(object):

    def __init__(self):
        self.config = ConfigParser.ConfigParser()
        self.config.read('bot.config')
        self.updater = Updater(token=self.config.get('KEYS', 'bot_api'))
        self.dispatcher = self.updater.dispatcher
        self.job_queue = self.updater.job_queue
        self.key_to_alert_id_mapping = [] # Stores the list of keys that have been sent out at the latest alert


    def send_nagios_alerts(self, bot, job):
        """
        Retrieves alerts and sends them
        """
        admin_id = self.config.get('ADMIN', 'id')

        # Open the database
        db_host_name = self.config.get('DATABASE', 'host')
        db_user_name = self.config.get('DATABASE', 'user')
        db_password = self.config.get('DATABASE', 'password')
        database_name = self.config.get('DATABASE', 'database')

        conn =  mysql.connector.connect(user=db_user_name,password=db_password,host=db_host_name, database=database_name)
        cursor = conn.cursor(buffered=True)
        c = conn.cursor(buffered=True)
        write_cursor = conn.cursor(buffered=True)
        # Get the current unsent alerts. Make sure to send them in order
        c.execute("SELECT id date_inserted,date_sent,message_text,status,hostname,service_name, notification_type FROM nagios_alerts WHERE STATUS='UNSENT' ORDER BY id ASC")
        # Enumerate the counter so we know how many results returned
        results = [one_result for one_result in c]
        total_count_of_alerts = len(results)
        message_str = """"""

        # Send the alerts which are not sent
        for index, one_alert in enumerate(results):
            # First update the alert to be SENT
            alert_id = one_alert[0]
            alert_text = one_alert[2]
            host_name = one_alert[4]
            service_name = one_alert[5]
            notification_type = one_alert[6]
#           write_cursor.execute("UPDATE nagios_alerts SET status='SENT', date_sent = NOW() where id= {0}".format(alert_id))
            # Send the message after we are sure the update occured
            message_str += alert_text
            # Add the alert to lists of alerts we can acknowledge along with a short string
            if notification_type == 'PROBLEM':
                self.key_to_alert_id_mapping.append((alert_id,"{0};{1}".format(host_name, service_name)))
            if index >= 4:
                # Send 5 messages together at a time and then wait till the next call
                break
            message_str += "--------------------\n"
            print alert_text

        if message_str:
            message_str += "{0}/{1} messages sent".format(index+1, total_count_of_alerts) # Since we start at 0
            bot.sendMessage(chat_id=admin_id, text=message_str)
            # Send message with options to acknowledge alerts
            if self.key_to_alert_id_mapping: # We have some alerts that can be acknowledged
                acknowledge_string = """ALERTS THAT CAN BE ACKNOWLEDGED: \n"""
                options = [] # Stores the keys for the keyboard reply
                for index, one_alert in enumerate(self.key_to_alert_id_mapping):
                    options.append(' '.join(['/acknowledge',str(index)])) # Store the key for the keyboard
                    acknowledge_string += "{0} : {1} \n".format(index, one_alert[1])

                # Send the message with the keyboard
                keyboard_options = [ options ]
                reply_keyboard = ReplyKeyboardMarkup(keyboard_options, one_time_keyboard=True)
                bot.sendMessage(chat_id=admin_id, text=acknowledge_string, reply_markup=reply_keyboard)



        # Commit changes and close db
        conn.commit()
        conn.close()

    def power_status(self, bot, update, args):
        ip_address = self.config.get('ADMIN', 'ups_ip') # the ip of the UPS server
        command_to_run = ['/usr/lib/nagios/plugins/show_ups']
        text_output = subprocess.check_output(command_to_run)
        bot.sendMessage(chat_id=update.message.chat_id, text=text_output)

    def acknowledge_alert(self, bot, update, args):
        """Takes the given alert and sends a request to acknowledge it.
        For now we just schedule 1 day of downtime so that it is not forgotten
        """
        if not args:
            # did not pass us an alert id
            bot.sendMessage(chat_id=update.message.chat_id, text="No alert specified")
            return

        try:
            alert_id, _ = self.key_to_alert_id_mapping[int(args[0])]
        except IndexError:
            # Some how the key they sent does not exist
             bot.sendMessage(chat_id=update.message.chat_id, text="Key does not exist")
             return
        # Find the alert id if it exists
        # Open the database
        db_host_name = self.config.get('DATABASE', 'host')
        db_user_name = self.config.get('DATABASE', 'user')
        db_password = self.config.get('DATABASE', 'password')
        database_name = self.config.get('DATABASE', 'database')

        conn =  mysql.connector.connect(user=db_user_name,password=db_password,host=db_host_name, database=database_name)
        cursor = conn.cursor(buffered=True)
        query = """SELECT hostname, service_name FROM nagios_alerts where id=%s"""
        cursor.execute(query, (alert_id,))

        # For now we use the downtime command to make sure the alert is not forgotten about
        current_time = int(time.time()) # Time in linux seconds since it doesnt make much of a difference for 1 second
        one_day = 60 * 60 * 24 # represents 24 hours
        end_time = current_time + one_day # represents 24 hours

        result = cursor.fetchone()
        command_string = """[{0}] """.format(current_time)
        host_name = result[0]
        service_name = result[1]
        ACK_COMMAND = 'SCHEDULE_SVC_DOWNTIME'
        COMMENT_COMMAND = 'ADD_SVC_COMMENT'
        comment = 'DOWNTIME SCHEDULED VIA TELEGRAM'
        command_string += ';'.join([ACK_COMMAND, host_name, service_name, str(current_time), str(end_time), '1', '0', str(one_day), 'nagiosadmin', comment])
        comment_string = """[{0}] {1};{2}""".format(current_time, COMMENT_COMMAND, ';'.join([host_name, service_name, '1', 'nagiosadmin', comment]))
        command_to_run = ['echo {0} > /var/lib/nagios3/rw/nagios.cmd'.format(command_string)]
        text_output = subprocess.check_output(command_to_run)
        print comment_string

    def setup(self):
        power_status_handler = CommandHandler('powerstatus', self.power_status, pass_args=True)
        self.dispatcher.add_handler(power_status_handler)

        acknowledge_alert_handler = CommandHandler('acknowledge', self.acknowledge_alert, pass_args=True)
        self.dispatcher.add_handler(acknowledge_alert_handler)

        # Create the job to check if we have any nagios alerts to send
        job_minute = Job(self.send_nagios_alerts, 60.0)
        self.job_queue.put(job_minute, next_t=0.0)

    def run(self):
        self.setup()
        self.updater.start_polling()
        self.updater.idle()


if __name__ == '__main__':
    telegram_bot = TelegramBot()
    telegram_bot.run()

