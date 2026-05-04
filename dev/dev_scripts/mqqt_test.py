import time
import uuid
import paho.mqtt.client as mqtt

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883
TEST_TOPIC = f"kazanfutes/test/{uuid.uuid4().hex}"

got_message = False

def on_connect(client, userdata, flags, rc):
    print(f"connected, rc={rc}")
    client.subscribe(TEST_TOPIC)
    client.publish(TEST_TOPIC, payload="hello from python", qos=1)

def on_message(client, userdata, msg):
    global got_message
    print(f"received on {msg.topic}: {msg.payload.decode()}")
    got_message = True

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

client.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
client.loop_start()

t0 = time.time()
while time.time() - t0 < 5:
    if got_message:
        break
    time.sleep(0.1)

client.loop_stop()
client.disconnect()

if got_message:
    print("mqtt python access ok")
else:
    print("mqtt test failed: no message received")