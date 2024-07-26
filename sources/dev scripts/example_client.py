import time
import interscript_comm as isc

if __name__ == '__main__':
    while True:
        # Connect to server if not connected
        if not isc.connected_to_server:
            isc.establish_connection_to_server()
        
        if isc.connected_to_server:
            # Check for a message from the server
            isc.receive_message_from_server()

            success = isc.send_message_to_server("Running main tasks.")
            print(f"Sending message successful: {success}.")
            if not success:
                isc.shutdown_server_connection()
        else:
            print("Couldn't talk to server before starting main tasks.")

        # Main tasks
        print("Doing stuff.")
        time.sleep(1)

        if isc.connected_to_server:
            # Check for a message from the server
            incoming_message = isc.receive_message_from_server()

            success = isc.send_message_to_server("Finished main tasks.")
            if not success:
                isc.shutdown_server_connection()
        else:
            print("Couldn't talk to server after finishing main tasks.")
