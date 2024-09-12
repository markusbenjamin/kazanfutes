from utils.project import *

settings.set("detailed_error_reporting",False)

if send_email(to=settings.get("admin_email"),subject="Test."):
    report("Email successfully sent.")
else:
    report("Couldn't send email.")