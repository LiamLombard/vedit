import os

from vedit.logger import Logger
from vedit.gui import VEditGUI

if os.name == "nt":
    from ctypes import windll

    windll.shcore.SetProcessDpiAwareness(1)

logger = Logger()
app = VEditGUI()
app.run()
