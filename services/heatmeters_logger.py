from utils.project import *

success = False
try:
    crop_rectangles = [
        (192,401,228,420),
        (193,555,229,572),
        (191,704,227,723),
        (191,251,227,270)
    ]

    captured_image_path = capture_image_to_disk('data/logs/heat_delivery/raw/')
    generate_and_save_cycle_crops(
        captured_image_path,
        crop_rectangles
    )
    success = True
except ModuleException as e:
    ServiceException("Module error while trying to capture heatmeter images", original_exception=e, severity = 2)
except Exception:
    ServiceException("Module error while trying to capture heatmeter images", severity = 2)

# Log execution
log({"success":success})