import os

# UI
DEFAULT_SLIDER_VALUES = {
    "Brightness": 100,
    "Color": 100,
    "Contrast": 100,
    "Sharpness": 100,
    "Blur": 0,
    "Deblur": 2,
    "AI_UPSCALE": 200,
}

DEFAULT_VALUE_SELECTION_METHODS = ['switch', 'slider', 'checkbox']
DEFAULT_RESOLUTION_VALUES = {"2x" : 2,
                            "4x" : 4,
                            "8x" : 8,
                            "16x" : 16,}

DEFAULT_SWITCH_METHOD_ON_VALUE = True
DEFAULT_SWITCH_METHOD_OFF_VALUE = False

ICONS_DIRECTORY = "icons"


# APP
DEFAULT_IMAGE_ID = None
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOAD_MODULE = 'Image_Effects'
DEBUG=False


# UPSCALING
IMAGE_TILE_SIZE = 128
IMAGE_TILE_OVERLAP = 60