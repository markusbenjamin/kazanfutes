from utils.project import *

success = False
try:
    time.sleep(random.randint(1, 20)) # To avoid synchronisation with the cycling of heatmeter displays
    captured_image_path = capture_image_to_disk('data/logs/heat_delivery/raw/')

    crop_rectangles = [
        #(x1,y1,x2,y2)
        (180, 400, 223, 417), # 1-es kör
        (180, 552, 223, 569), # 2-es kör
        (176, 703, 220, 719), # 3-mas kör
        (180, 248, 224, 267)  # 4-es kör
    ]

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