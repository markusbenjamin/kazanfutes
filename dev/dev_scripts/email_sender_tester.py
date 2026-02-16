from utils.project import *

settings["detailed_error_reporting"] = False

if send_email(to=settings["admin_email"],subject="Test.",body={"message":"json"}):
    report("Email successfully sent.")
else:
    report("Couldn't send email.")