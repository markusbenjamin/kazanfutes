from utils.project import *

settings.set_detailed_error_reporting(False)

if send_email(to="markus.benjamin@gmail.com",subject="Test."):
    report("Email successfully sent.")
else:
    report("Couldn't send email.")