from utils.project import *

if __name__ == '__main__':
    crop_rectangles = [
        (191,401,227,420),
        (192,555,227,572),
        (191,704,225,723),
        (191,251,225,270)
    ]

    captured_image_path = capture_image_to_disk('data/logs/heat_delivery/raw/')
    generate_and_save_cycle_crops(
        captured_image_path,
        crop_rectangles
    )