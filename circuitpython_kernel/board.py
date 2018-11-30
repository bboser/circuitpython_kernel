# -*- coding: utf-8 -*-
"""Serial Connection to a Board"""
import logging
from serial import Serial
from serial.tools.list_ports import comports
from serial.serialutil import SerialException

# Create BOARD_LOGGER for debug messages.
BOARD_LOGGER = logging.getLogger(__name__)


# Vendor IDs
ADAFRUIT_VID = 0x239A    # SAMD
ESP8266_VID  = 0x10C4    # Huzzah ESP8266

# repl commands
CHAR_CTRL_A = b'\x01'
CHAR_CTRL_B = b'\x02'
CHAR_CTRL_C = b'\x03'
CHAR_CTRL_D = b'\x04'

# repl messages
MSG_NEWLINE = b"\r\n"
MSG_RAWREPL = b"raw REPL; CTRL-B to exit"
MSG_RAWREPL_PROMPT = b"\r\n>"
MSG_SOFT_REBOOT = b'soft reboot\r\n'
MSG_RELOAD = b'Use CTRL-D to reload.'

class BoardError(Exception):
    """Errors relating to board connections"""
    def __init__(self, msg):
        super().__init__(msg)


class Board:
    """Connect to CP VM, reconnect if connection lost"""

    def __init__(self):
        self.connected = False
        self.serial = None

    def write(self, msg):
        try:
            self.serial.write(msg)
        except SerialException as s:
            self.connected = False
            raise BoardError(f"cannot write to board: {s}")


    def read_until(self, msg):
        try:
            return self.serial.read_until(msg)
        except SerialException as s:
            self.connected = False
            raise BoardError(f"cannot read from board: {s}")


    def read_all(self):
        try:
            return self.serial.read_all()
        except SerialException as s:
            self.connected = False
            raise BoardError(f"cannot read from board: {s}")

    def close(self):
        if self.serial and self.connected:
            try:
                self.connected = False
                self.serial.close()
            except:
                pass

    def softreset(self):
        serial = self.serial
        # in case the VM is in a weird state ...
        self.enter_raw_repl()
        # now do the soft reset ...
        BOARD_LOGGER.debug("* ^D, soft reset")
        serial.write(CHAR_CTRL_D)
        serial.read_until(MSG_SOFT_REBOOT)
        serial.read_until(MSG_RELOAD)
        serial.write(b'\n')
        serial.read_until(MSG_RAWREPL)
        serial.read_until(MSG_RAWREPL_PROMPT)
        BOARD_LOGGER.debug("* soft reset complete, in raw repl")

    def enter_raw_repl(self):
        BOARD_LOGGER.debug('* enter raw repl ...')
        serial = self.serial
        serial.write(CHAR_CTRL_C)
        serial.write(CHAR_CTRL_A)
        # wait for prompt
        serial.read_until(MSG_RAWREPL)
        serial.read_until(MSG_RAWREPL_PROMPT)
        BOARD_LOGGER.debug('* entered raw repl, returning to kernel...')

    def connect(self):
        """(re)connect to board and enter raw repl"""
        if self.connected: return
        device = self._find_board()
        try:
            BOARD_LOGGER.debug(f'connect: open {device}')
            self.serial = Serial(device, 115200, parity='N')
        except:
            raise BoardError(f"failed to access {device}")
        # open the port
        if not self.serial.is_open:
            try:
                BOARD_LOGGER.debug('* opening board ...')
                self.serial.open()
                BOARD_LOGGER.debug('* board opened')
            except SerialException as s:
                raise BoardError(f"failed to open {device}")
        else:
            BOARD_LOGGER.debug('serial already open')

        # enter the REPL
        try:
            self.enter_raw_repl()
            self.connected = True
        except:
            raise BoardError(f"failed to enter raw repl with {device}")

    def _find_board(self):
        """Find serial port where an Adafruit board is connected"""
        for port in comports():
            # print out each device
            BOARD_LOGGER.debug(port.device)
            if port.vid == ADAFRUIT_VID or port.vid == ESP8266_VID:
                BOARD_LOGGER.debug(f"CircuitPython Board Found at: {port.device}")
                return port.device
        raise BoardError("found no board")
