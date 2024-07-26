import tinytuya

# Connect to Device
d = tinytuya.OutletDevice(
    dev_id='bfcc9911191a84463ar1gd',
    address='192.168.34.103',
    local_key='t@&Q&~2q>g[4h5xX',
    version=3.3)

# Get Status
data = d.status()
print(data['dps']['1'])

# Turn On if Off and Off if On
if data['dps']['1']:
    print('trying to turn off')
    d.turn_off()
    print((d.status())['dps']['1'])
else:
    print('trying to turn on')
    d.turn_on()
    print((d.status())['dps']['1'])