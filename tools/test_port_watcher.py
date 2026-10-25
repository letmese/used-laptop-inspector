"""Prove the port test can actually hear a USB device.

Two things must work: RegisterDeviceNotification has to return a handle, and the
WM_DEVICECHANGE payload has to be parsed into a device name. Both can be checked
without plugging anything in - the second by feeding a real
DEV_BROADCAST_DEVICEINTERFACE structure through the same filter Windows uses.
"""

import ctypes
import sys

from PySide6.QtWidgets import QApplication

sys.path.insert(0, ".")

from laptop_inspector.ui.tests import port_test as PT

app = QApplication(sys.argv)
dialog = PT.PortTestDialog({"manufacturer": "LENOVO", "family": "ThinkPad W520",
                            "model": "4282AC5"})
dialog.show()
app.processEvents()

print("layout:", dialog.layout.family, "| known:", dialog.layout.known)
print("testable ports:", [p.label for p in dialog.order])
print("notification handle:", dialog._notify, "| registered:", bool(dialog._notify))

watcher = dialog._watcher


def feed(path, arrival=True):
    """Build the exact structure Windows sends and run it through the filter."""
    name_bytes = len(path) + 1
    size = PT.DEV_BROADCAST_DEVICEINTERFACE.dbcc_name.offset + name_bytes * 2
    buf = ctypes.create_string_buffer(size)
    header = ctypes.cast(buf, ctypes.POINTER(PT.DEV_BROADCAST_DEVICEINTERFACE))
    header.contents.dbcc_size = size
    header.contents.dbcc_devicetype = PT.DBT_DEVTYP_DEVICEINTERFACE
    header.contents.dbcc_classguid = PT.GUID_DEVINTERFACE_USB_DEVICE
    ctypes.memmove(ctypes.addressof(buf) +
                   PT.DEV_BROADCAST_DEVICEINTERFACE.dbcc_name.offset,
                   ctypes.create_unicode_buffer(path), name_bytes * 2)

    msg = PT._MSG()
    msg.message = PT.WM_DEVICECHANGE
    msg.wParam = PT.DBT_DEVICEARRIVAL if arrival else PT.DBT_DEVICEREMOVECOMPLETE
    msg.lParam = ctypes.addressof(buf)
    watcher.nativeEventFilter("windows_generic_MSG", ctypes.addressof(msg))


print("\n--- feeding a real arrival ---")
feed(r"\\?\USB#VID_0781&PID_5583#4C530001250612105383#{a5dcbf10-6530-11d2-901f-00c04fb951ed}")
print("index now:", dialog._index, "| tested:", dialog.tested)
print("step label:", dialog.step_lbl.text())
print("detect label:", dialog.detect_lbl.text())

print("\n--- same device, second interface (must not double count) ---")
before = dialog._index
feed(r"\\?\USB#VID_0781&PID_5583#4C530001250612105383&MI_00#{a5dcbf10-6530-11d2-901f-00c04fb951ed}")
print("index before:", before, "after:", dialog._index,
      "| deduped:", before == dialog._index)

print("\n--- volume arrival (must be ignored) ---")
before = dialog._index


class HDR(ctypes.Structure):
    _fields_ = [("size", ctypes.c_ulong), ("devtype", ctypes.c_ulong),
                ("res", ctypes.c_ulong)]


hdr = HDR(12, 2, 0)  # DBT_DEVTYP_VOLUME
msg = PT._MSG()
msg.message = PT.WM_DEVICECHANGE
msg.wParam = PT.DBT_DEVICEARRIVAL
msg.lParam = ctypes.addressof(hdr)
watcher.nativeEventFilter("windows_generic_MSG", ctypes.addressof(msg))
print("index before:", before, "after:", dialog._index,
      "| ignored:", before == dialog._index)

dialog._mark_dead()
print("\nafter mark dead -> index:", dialog._index,
      "| failed:", dialog.failed)
print("result would be:", dialog.tested, "ok /", dialog.failed)

dialog.close()
