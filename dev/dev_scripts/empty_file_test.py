import os

filepath = "C:\\Users\\Beno\\Documents\\SZAKI\\dev\\kazanfutes\\data\\logs\\errors\\daily_report.json"
filepath = "C:\\Users\\Beno\\Documents\\SZAKI\\dev\\kazanfutes\\data\\logs\\errors\\test_daily_report.json"

with open(filepath, 'r') as file:
    lines = file.readlines()
    print(len(lines))
if 0<len(lines):
    print("bla")
else:
    os.remove(filepath)