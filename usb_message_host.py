#!/usr/bin/env python3
import argparse
import os
import platform
import time

import usb.core
import usb.util
from usb.backend import libusb1


DEFAULT_VID = 0xCAFE
DEFAULT_PID = 0x4010
VENDOR_CLASS = 0xFF
MAX_PACKET = 64


def _backend():
    try:
        import libusb_package

        backend = libusb_package.get_libusb1_backend()
        if backend is not None:
            return backend
    except ImportError:
        pass

    return libusb1.get_backend()


class USBMessageClient:
    def __init__(
        self,
        vid=DEFAULT_VID,
        pid=DEFAULT_PID,
        timeout_ms=1000,
        set_configuration=False,
    ):
        self.vid = vid
        self.pid = pid
        self.timeout_ms = timeout_ms
        self.set_configuration = set_configuration
        self.dev = None
        self.interface_number = None
        self.ep_in = None
        self.ep_out = None
        self._rx = bytearray()

    def open(self):
        backend = _backend()
        if backend is None:
            raise RuntimeError(
                "PyUSB could not load a libusb-1.0 backend. "
                "On Windows, run: python -m pip install libusb-package"
            )

        self.dev = usb.core.find(
            idVendor=self.vid, idProduct=self.pid, backend=backend
        )
        if self.dev is None:
            raise RuntimeError(
                "USB message device not found "
                f"(VID=0x{self.vid:04x}, PID=0x{self.pid:04x})"
            )

        if self.set_configuration:
            try:
                self.dev.set_configuration()
            except usb.core.USBError:
                pass

        cfg = self.dev.get_active_configuration()
        intf = self._find_vendor_interface(cfg)
        self.interface_number = intf.bInterfaceNumber

        if self._kernel_driver_active(self.interface_number):
            self.dev.detach_kernel_driver(self.interface_number)

        usb.util.claim_interface(self.dev, self.interface_number)
        self.ep_out = usb.util.find_descriptor(
            intf,
            custom_match=lambda ep: usb.util.endpoint_direction(ep.bEndpointAddress)
            == usb.util.ENDPOINT_OUT,
        )
        self.ep_in = usb.util.find_descriptor(
            intf,
            custom_match=lambda ep: usb.util.endpoint_direction(ep.bEndpointAddress)
            == usb.util.ENDPOINT_IN,
        )

        if self.ep_in is None or self.ep_out is None:
            raise RuntimeError("vendor interface does not expose bulk IN and OUT endpoints")
        return self

    def close(self):
        if self.dev is not None and self.interface_number is not None:
            usb.util.release_interface(self.dev, self.interface_number)
            usb.util.dispose_resources(self.dev)
        self.dev = None

    def send(self, payload):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        if len(payload) > 0xFFFF:
            raise ValueError("message too large")
        frame = len(payload).to_bytes(2, "big") + payload
        self.dev.write(self.ep_out.bEndpointAddress, frame, timeout=self.timeout_ms)

    def send_text(self, text):
        self.send(text.encode("utf-8"))

    def recv(self, timeout_ms=None):
        timeout_ms = self.timeout_ms if timeout_ms is None else timeout_ms
        deadline = time.monotonic() + (timeout_ms / 1000)

        while True:
            msg = self._pop_message()
            if msg is not None:
                return msg

            remaining = int((deadline - time.monotonic()) * 1000)
            if remaining <= 0:
                return None

            try:
                chunk = self.dev.read(
                    self.ep_in.bEndpointAddress,
                    MAX_PACKET,
                    timeout=min(remaining, timeout_ms),
                )
                self._rx.extend(bytes(chunk))
            except usb.core.USBError as exc:
                if _is_timeout(exc):
                    return None
                raise

    def recv_text(self, timeout_ms=None):
        msg = self.recv(timeout_ms)
        if msg is None:
            return None
        return msg.decode("utf-8")

    def recv_nowait(self):
        msg = self._pop_message()
        if msg is not None:
            return msg

        try:
            chunk = self.dev.read(
                self.ep_in.bEndpointAddress,
                MAX_PACKET,
                timeout=1,
            )
            self._rx.extend(bytes(chunk))
        except usb.core.USBError as exc:
            if _is_timeout(exc):
                return None
            raise
        return self._pop_message()

    def recv_text_nowait(self):
        msg = self.recv_nowait()
        if msg is None:
            return None
        return msg.decode("utf-8")

    def request_text(self, text, timeout_ms=None):
        self.send_text(text)
        return self.recv_text(timeout_ms)

    def _find_vendor_interface(self, cfg):
        for intf in cfg:
            if intf.bInterfaceClass == VENDOR_CLASS:
                return intf
        raise RuntimeError("USB message vendor interface not found")

    def _kernel_driver_active(self, interface_number):
        try:
            return self.dev.is_kernel_driver_active(interface_number)
        except (NotImplementedError, usb.core.USBError):
            return False

    def _pop_message(self):
        if len(self._rx) < 2:
            return None
        payload_len = int.from_bytes(self._rx[:2], "big")
        frame_len = 2 + payload_len
        if len(self._rx) < frame_len:
            return None
        payload = bytes(self._rx[2:frame_len])
        del self._rx[:frame_len]
        return payload

    def __enter__(self):
        return self.open()

    def __exit__(self, exc_type, exc, tb):
        self.close()


def _is_timeout(exc):
    return getattr(exc, "errno", None) in (60, 110, 116) or "timed out" in str(exc).lower()


def main():
    parser = argparse.ArgumentParser(description="Send a framed USB message to an ESP32.")
    parser.add_argument("message", nargs="?", default="ping")
    parser.add_argument("--vid", type=lambda value: int(value, 0), default=DEFAULT_VID)
    parser.add_argument("--pid", type=lambda value: int(value, 0), default=DEFAULT_PID)
    parser.add_argument("--timeout-ms", type=int, default=1000)
    parser.add_argument(
        "--list",
        action="store_true",
        help="list USB devices visible through PyUSB/libusb and exit",
    )
    parser.add_argument(
        "--diag",
        action="store_true",
        help="print PyUSB/libusb diagnostics and exit",
    )
    parser.add_argument(
        "--open-only",
        action="store_true",
        help="open and claim the message interface, then exit without transfers",
    )
    parser.add_argument(
        "--set-configuration",
        action="store_true",
        help="call set_configuration() before claiming the interface",
    )
    args = parser.parse_args()

    if args.diag:
        print_diagnostics()
        return

    if args.list:
        list_devices()
        return

    with USBMessageClient(
        args.vid,
        args.pid,
        args.timeout_ms,
        set_configuration=args.set_configuration,
    ) as client:
        if args.open_only:
            print(
                "Opened USB message interface "
                f"{client.interface_number}, OUT=0x{client.ep_out.bEndpointAddress:02x}, "
                f"IN=0x{client.ep_in.bEndpointAddress:02x}"
            )
            return
        client.send_text(args.message)
        reply = client.recv_text(args.timeout_ms)
        if reply is None:
            print("No reply before timeout")
        else:
            print(reply)


def list_devices():
    backend = _backend()
    if backend is None:
        print(
            "PyUSB could not load a libusb-1.0 backend. "
            "On Windows, run: python -m pip install libusb-package"
        )
        return

    devices = list(usb.core.find(find_all=True, backend=backend))
    if not devices:
        print("PyUSB/libusb did not report any USB devices.")
        return

    for dev in devices:
        print(f"VID=0x{dev.idVendor:04x} PID=0x{dev.idProduct:04x}")


def print_diagnostics():
    backend = _backend()
    print(f"Python: {platform.python_version()} {platform.architecture()[0]}")
    print(f"Platform: {platform.platform()}")
    print(f"PATH: {os.environ.get('PATH', '')}")
    if backend is None:
        print("libusb backend: not loaded")
        print("Install hint: python -m pip install libusb-package")
    else:
        print(f"libusb backend: {backend!r}")


if __name__ == "__main__":
    main()
