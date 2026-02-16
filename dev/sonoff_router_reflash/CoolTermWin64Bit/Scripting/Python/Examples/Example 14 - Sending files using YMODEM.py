# Sending files using YMODEM
#
# Author: Roger Meier, 01-10-2025
# CoolTerm version: 2.4.0

import time
import CoolTerm
s = CoolTerm.CoolTermSocket()

# Specify the array of absolute path(s) to your file(s) here
paths = ["/Users/Shared/pdf_file.pdf","/Users/Shared/textfile.txt"]
mode = 4 # 1: XMODEM, 2:XMODEM_CRC, 3:XMODEM1K, 4: YMODEM

# Get the ID of the first open window
ID = s.GetFrontmostWindow()
if ID < 0:
    print("No open windows")
    sys.exit()

# Open the serial port
if s.Connect(ID):
    
    # send the files
    s.SendFiles(ID,paths,mode)

    # Wait until they are done sending
    status = s.FileTransferStatus(ID)
    while status in [-3,-2]:
        time.sleep(0.5)
        status = s.FileTransferStatus(ID)

    n1 = len(paths)
    n2 = s.FileTransferStatus(ID)
    print("{} of {} files transferred successfully.".format(n2,n1))

    # Close the port
    s.Disconnect(ID)

else:
    print("Not Connected")
    
s.Close()
    