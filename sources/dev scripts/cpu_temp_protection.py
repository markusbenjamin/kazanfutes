import time
import csv
from datetime import datetime
import os
import subprocess
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import ssl

# List to hold temperature data in RAM
CPU_temp_warning = 75
CPU_temp_shutoff = 85
temp_data = []

def send_email(subject, message):
    sender_email = "kazankontroll@gmail.com"
    receiver_email = "markus.benjamin@gmail.com"
    password = "ytjd xnnq lmci jrop"
    email = MIMEMultipart()
    email["From"] = sender_email
    email["To"] = receiver_email
    email["Subject"] = subject
    email.attach(MIMEText(message, "plain"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(sender_email, password)
        server.sendmail(sender_email, receiver_email, email.as_string())

# Function to get the current temperature
def get_CPU_temperature():
    output = subprocess.run(['vcgencmd', 'measure_temp'], capture_output=True, text=True).stdout
    temp_str = output.split('=')[1].split('\'')[0]
    return float(temp_str)

# Function to be called when temperature exceeds the threshold
def monitor_CPU_temp():
    current_CPU_temp = get_CPU_temperature()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    temp_data.append((timestamp, current_CPU_temp))
    
    # 3) Periodically save data to CSV every hour
    if datetime.now().minute == 0 and datetime.now().second == 0:
        with open('CPU_temp_log.csv', mode='a', newline='') as file:
            writer = csv.writer(file)
            writer.writerows(temp_data)
            temp_data.clear()  # Clear the temp_data list after saving to file
    
    # 4) Check if temperature exceeds the threshold
    if CPU_temp_warning < current_CPU_temp:
        send_email("RasPi overheat warning", f"CPU temp: {get_CPU_temperature()}")
    if CPU_temp_shutoff < current_CPU_temp:
        send_email("RasPi overheat shutoff", f"CPU temp: {get_CPU_temperature()}")
        #ERROR HANDLING