from utils.project import *

def capture_image():
    time.sleep(random.randint(1, 20))
    current_date = time.strftime("%Y-%m-%d")
    save_path = f'{get_project_root()}/data/logs/heatmeter_images/{current_date}/'
    if not os.path.exists(save_path):
        os.makedirs(save_path)

    now = datetime.now()
    timestamp = now.strftime("%H%M")
    image_filename = f'{save_path}{timestamp}.jpg'

    # Capture an image using fswebcam
    try:
        subprocess.run(['fswebcam', '-r', '1280x720', '--no-banner', image_filename])
        print(f'Captured image {image_filename}.')
        return image_filename
    except Exception as e:
        print(f"Couldn't capture image {image_filename} due to {e}.")

if __name__ == '__main__':
    capture_image()