"""Keep tkinter discoverable for the portable Python build runtime.

The bundled build runtime has working tkinter files, but PyInstaller's Tcl/Tk
probe cannot locate them and otherwise removes tkinter from the module graph.
The spec supplies the Tcl/Tk runtime files explicitly.
"""


def pre_find_module_path(hook_api):
    return None
