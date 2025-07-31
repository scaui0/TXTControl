"""
TXTControl - A pythonic implementation of ftrobopy using asyncio.

This library allows controlling the fischertechnik TXT controller with Python from a remote.
It provides an asynchronous API, making it easy to integrate in modern Python applications without using complex
thread-handling.

Author: Franz Weingartz
Licensed under the MIT License.
"""

import asyncio
import socket
import struct
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from itertools import chain
from math import log
from typing import Self, Literal, Any


class TXTError(Exception):
    """Base class for TXT-related errors."""


class TXTConnectionError(TXTError):
    """TXT-related ConnectionError."""


class _InputType(Enum):
    """The input type for the input ports of the TXT."""
    VOLTAGE = 0
    SWITCH = 1
    RESISTOR = 2
    # TODO: [sic?]. seems like 2 is correct, not 1. I don't know why, the original variable this is taken from used 1

    ULTRASONIC = 3


class _InputMethod(Enum):
    """The input method for the input ports of TXT."""
    ANALOG = 0
    DIGITAL = 1


class _OutputType(Enum):
    """The output type for the output/motor ports."""
    OUTPUT = 0
    MOTOR = 1


@dataclass
class _Buffer:
    """Class containing all the exchange data."""
    pwm: list[int]
    motor_sync: list[int]
    motor_distance: list[int]
    motor_cmd_id: list[int]
    counter: list[int]
    sound: list[int]
    sound_index: list[int]
    sound_repeat: list[int]

    current_input: list[int]
    current_counter: list[int]
    current_counter_value: list[int]
    current_counter_cmd_id: list[int]
    current_motor_cmd_id: list[int]
    current_sound_cmd_id: list[int]

    config_id: list[int]
    motor_config: list[_OutputType]
    input_config: list[tuple[_InputType, _InputMethod]]

    timer: float

    # Useless constants (needed for protocol)
    motor_config_extended: list[Literal[0]] = field(
        default_factory=lambda: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                                 0, 0, 0])
    ftX1_pgm_state_req: int = 0
    ftX1_old_FtTransfer: int = 0
    ftX1_dummy: bytes = b'\x00\x00'
    ftX1_cnt: list[int | bytes] = field(default_factory=lambda: [1, b'\x00\x00\x00',
                                                                 1, b'\x00\x00\x00',
                                                                 1, b'\x00\x00\x00',
                                                                 1, b'\x00\x00\x00',
                                                                 1, b'\x00\x00\x00',
                                                                 1, b'\x00\x00\x00',
                                                                 1, b'\x00\x00\x00',
                                                                 1, b'\x00\x00\x00'])

    @property
    def as_fields(self):
        return [
            self.pwm[:8],
            self.motor_sync[:4],
            self.motor_distance[:4],
            self.motor_cmd_id[:4],
            self.counter[:4],
            [
                self.sound[0], self.sound_index[0], self.sound_repeat[0],
                0, 0
            ]
        ]

    @classmethod
    def empty(cls) -> Self:
        return cls(
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0],
            [0, 0],
            [0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0, 0, 0],
            # Yes, I spammed these zeros by myself. 110 times!
            [0, 0],
            [_OutputType.MOTOR] * 8,
            [(_InputType.SWITCH, _InputMethod.DIGITAL)] * 16,

            time.time()
        )


_AUTODETECT_HOSTS = [
    "192.168.7.2",  # USB (Ethernet)
    "192.168.8.2",  # WLAN
    "192.168.9.2"  # Bluetooth
]

_DEFAULT_PORT = 65000


def _auto_detect_txt_host():
    def test_connection(test_host, port=_DEFAULT_PORT):
        try:
            with socket.create_connection((test_host, port), timeout=1):
                return True
        except (ConnectionRefusedError, TimeoutError):
            return False

    for host in _AUTODETECT_HOSTS:
        if test_connection(host):
            return host

    raise TXTConnectionError("Autodetect failed! Please specify the host manually!")


class TXT:
    """
    The class representing the TXT connection.

    If `host` is not given, TXTControl tries to find a TXT using the following ports:
    1. `192.168.7.2` USB (Ethernet)
    2. `192.168.8.2` WLAN
    3. `192.168.9.2` Bluetooth

    Examples:
        >>> async with TXT() as txt:
        ...     print("TXT connected!")
    """

    def __init__(self, host=None, port=6500):
        if host is None:
            host = _auto_detect_txt_host()

        self.host = host
        self.port = port

        self.device_name = None
        self.device_version = None  # why isn't is set anywhere?
        self.firmware_version = None

        self.used_input_slots: list[Any] = [None] * 8
        self.used_output_slots: list[Any] = [None] * 4

        self._connection_lock = asyncio.Lock()
        self._is_running = False
        self._update_intervall = 0.02
        self._buffer = _Buffer.empty()
        self._update_event = asyncio.Event()

        self._reader: asyncio.StreamReader
        self._writer: asyncio.StreamWriter

    async def __aenter__(self):
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)

        await self._simple_request(
            (m_id := 0x163FF61D),
            0xCA689F75,
            "<I",
            buffer=struct.pack('<I64s', m_id, b'')
        )

        self._is_running = True
        self._keep_connection_task = asyncio.create_task(self._keep_connection())

        await self.query_status()
        await self.update_config()

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._is_running = False
        await self._keep_connection_task

        await self._simple_request(0x9BE5082C, 0xFBF600D2, "<I")

        self._writer.close()
        await self._writer.wait_closed()

    async def _simple_request(self, m_id, expected_response, format_string, *, buffer=None):
        """Make a simple request and returns the fields the TXT returned."""
        if buffer is None:
            buffer = struct.pack("<I", m_id)

        async with self._connection_lock:
            self._writer.write(buffer)
            await self._writer.drain()
            # raw_data = await self._reader.readexactly(512)
            raw_data = await self._reader.read(512)

        if len(raw_data) == struct.calcsize(format_string):
            response_id, *data = struct.unpack(format_string, raw_data)
        else:
            raise TXTConnectionError("No or invalid data received from TXT!")

        if response_id != expected_response:
            raise TXTConnectionError(
                f"ResponseID {hex(response_id)} does not match required ID {hex(expected_response)}")

        return data

    async def query_status(self):  # TODO: what are the return types?
        """Query the current status of the TXT.

        Returns:
            device name, device version
        """
        device_name, version = await self._simple_request(0xDC21219A, 0xBAC9723E, "<I16sI")

        self.device_name = device_name.decode("utf-8").strip("\x00")

        v1 = (version >> 24) & 0xFF
        v2 = (version >> 16) & 0xFF
        v3 = (version >> 8) & 0xFF

        self.firmware_version = f"{v1}.{v2}.{v3}"
        return self.device_name, self.device_version

    async def _keep_connection(self):
        """Keeps the connection to the TXT and exchanges the input and output values periodically."""
        while self._is_running:
            await asyncio.sleep(self._update_intervall)

            # TODO: Use _simple_request
            m_id = 0xCC3597BA
            expected_response = 0x4EEFAC41

            # Pack the values for the outputs.
            fields = [[m_id]] + self._buffer.as_fields
            fields = list(chain(*fields))
            buffer = struct.pack("<I8h4h4h4h4hHHHbb", *fields)

            async with self._connection_lock:
                self._writer.write(buffer)
                await self._writer.drain()
                data = await self._reader.readexactly(512)

            self._buffer.timer = time.time()
            format_string = "<I8h4h4h4h4hH4bB4bB4bB4bB4bBb"
            if len(data) != struct.calcsize(format_string):
                raise TXTConnectionError(
                    f"Received data size {len(data)} does not match length of format string"
                    f" {struct.calcsize(format_string)}"
                )

            response = struct.unpack(format_string, data)
            if response[0] != expected_response:
                raise TXTConnectionError(
                    f"ResponseID {hex(response[0])} does not match required ID {hex(expected_response)}!")

            b = self._buffer
            b.current_input[:8] = response[1:9]
            b.current_counter[:4] = response[9:13]
            b.current_counter_value[:4] = response[13:17]
            b.current_counter_cmd_id[:4] = response[17:21]
            b.current_motor_cmd_id[:4] = response[21:25]
            b.current_sound_cmd_id[0] = response[25]
            # Ignore IR data (response[26:52])
            b.handle_data()
            self._update_event.clear()
            self._update_event.set()

    def _set_pwm(self, port, value):
        self._buffer.pwm[port] = value

    def _get_pwm(self, port=None):
        if port is None:
            value = self._buffer.pwm[:8]
        else:
            value = self._buffer.pwm[port]

        return value

    def _set_motor_sync(self, m1, m2):
        self._buffer.motor_sync[m1] = m2 + 1

    def _get_motor_sync(self, port=None):
        if port is None:
            value = self._buffer.motor_sync[:4]
        else:
            value = self._buffer.motor_sync[port]

        return value

    def _set_motor_distance(self, port, value):
        self._buffer.motor_distance[port] = value

    def _get_motor_distance(self, port=None):
        if port is None:
            value = self._buffer.motor_distance[:4]
        else:
            value = self._buffer.motor_distance[port]

        return value

    def _get_current_input(self, port=None):
        if port is None:
            value = self._buffer.current_input[:8]
        else:
            value = self._buffer.current_input[port]

        return value

    def _get_current_counter_change(self, port=None):
        # In ftrobopy this method is called getCurrentCounterInput
        if port is None:
            value = self._buffer.current_counter[:4]
        else:
            value = self._buffer.current_counter[port]

        return value

    def _get_current_counter_value(self, port=None):
        if port is None:
            value = self._buffer.current_counter_value[:4]
        else:
            value = self._buffer.current_counter_value[port]

        return value

    def _get_current_counter_command_id(self, port=None):
        if port is None:
            value = self._buffer.current_counter_cmd_id[:4]
        else:
            value = self._buffer.current_counter_cmd_id[port]

        return value

    def _get_counter_command_id(self, port=None):
        if port is None:
            value = self._buffer.counter[:4]
        else:
            value = self._buffer.counter[port]

        return value

    def _increment_counter_command_id(self, port):
        self._buffer.counter[port] += 1
        self._buffer.counter[port] &= 0x07  # same as %= 8

    def _get_current_motor_command_id(self, port=None):
        if port is None:
            value = self._buffer.current_motor_cmd_id[:4]
        else:
            value = self._buffer.current_motor_cmd_id[port]

        return value

    def _get_motor_command_id(self, port=None):
        if port is None:
            value = self._buffer.motor_cmd_id[:4]
        else:
            value = self._buffer.motor_cmd_id[port]

        return value

    def _increment_motor_command_id(self, port):
        self._buffer.motor_cmd_id[port] += 1
        self._buffer.motor_cmd_id[port] &= 0x07  # Same as %= 8

    def _get_sound_command_id(self):
        return self._buffer.sound[0]

    def _increment_sound_command_id(self):
        self._buffer.sound[0] += 1
        self._buffer.sound[0] &= 0x0F  # same as %= 16

    def _set_sound_index(self, sound):
        self._buffer.sound_index[0] = sound

    def _get_sound_index(self):
        return self._buffer.sound_index[0]

    def _set_sound_repeat(self, times):
        self._buffer.sound_repeat[0] = times

    def _get_sound_repeat(self):
        return self._buffer.sound_repeat[0]

    def _set_config(self, motor_config, input_config):
        self._buffer.config_id[0] += 1
        self._buffer.motor_config[:4] = motor_config
        self._buffer.input_config[:8] = input_config

    def _get_config(self):
        return self._buffer.motor_config, self._buffer.input_config

    async def update_config(self):
        """
        Transfer the current configuration to the TXT.

        This function is automatically called when using the `create` method to create inputs or outputs.
        """

        def prepare_input_config(c):
            return [c[0][0], c[0][1], b'\x00\x00',
                    c[1][0], c[1][1], b'\x00\x00',
                    c[2][0], c[2][1], b'\x00\x00',
                    c[3][0], c[3][1], b'\x00\x00',
                    c[4][0], c[4][1], b'\x00\x00',
                    c[5][0], c[5][1], b'\x00\x00',
                    c[6][0], c[6][1], b'\x00\x00',
                    c[7][0], c[7][1], b'\x00\x00']

        m_id = 0x060EF27E
        expected_response = 0x9689A68C

        self._buffer.config_id[0] += 1

        b = self._buffer
        fields = [
            m_id,
            b.config_id[0],
            0,  # extension
            b.ftX1_pgm_state_req,
            b.ftX1_old_FtTransfer,
            b.ftX1_dummy
        ]
        fields += list(map(int, b.motor_config[:4]))
        fields += prepare_input_config(b.input_config[:8])
        fields += b.ftX1_cnt[:8]
        fields += b.motor_config_extended[:16]

        buffer = struct.pack("<Ihh B B 2s BBBB BB2s BB2s BB2s BB2s BB2s BB2s BB2s BB2s B3s B3s B3s B3s 16h",
                             *fields)
        async with self._connection_lock:
            self._writer.write(buffer)
            await self._writer.drain()
            data = await self._reader.readexactly(512)

        format_string = "<I"
        if len(data) == struct.calcsize(format_string):
            response_id, = struct.unpack(format_string, data)
        else:
            raise TXTConnectionError("No or invalid data received from TXT!")

        if response_id != expected_response:
            raise TXTConnectionError(
                f"ResponseID {hex(response_id)} does not match required ID {hex(expected_response)}"
            )

    def _get_camera_host(self) -> tuple[str, int]:
        return self.host, self.port + 1

    async def _start_camera_on_txt(self):
        width = 320
        height = 240
        fps = 15
        power_line_frequency = 0  # 0=auto, 1=50Hz, 2=60Hz

        message_id = 0x882A40A6
        expected_response_id = 0xCF41B24E
        await self._simple_request(
            message_id, expected_response_id, "<I",
            buffer=struct.pack("<I4i", message_id, width, height, fps, power_line_frequency)
        )

    async def _stop_camera_on_txt(self):
        await self._simple_request(0x17C31F2F, 0x4B3C1EB6, "<I")

    async def wait(self):
        """Wait until the next time the TXT sends new input values."""
        await self._update_event.wait()

    @asynccontextmanager
    async def sync_data(self):
        """
        Contextmanager that syncs multiple commands without sending the current state to the TXT.

        Warnings:
            This method just blocks the connection. Long-running operations will result in a deadlock or in a
            TXTConnectionError!
        """
        async with self._connection_lock:
            yield


# noinspection PyProtectedMember
class Motor:
    """Class representing a TXT motor."""

    def __init__(self, txt: TXT, port: int):
        """
        Creates a new motor class instance. To update the config of the TXT, use the `.create` method or call
        `txt.update_config()` by yourself!

        Args:
            txt: The base TXT class object.
            port: the port of the motor. 0-3 for M1-M4
        """
        self._txt: TXT = txt
        self._port = port

        if txt.used_output_slots[port] is not None:
            raise TXTError(f"Motor slot {port} is already used!")

        txt.used_output_slots[port] = self

        motor_config, input_config = txt._get_config()
        motor_config[port] = _OutputType.MOTOR
        txt._set_config(motor_config, input_config)

        self._speed = 0
        self._distance = 0

    @classmethod
    async def create(cls, txt: TXT, port: int):
        """
        Create a new Motor class. Automatically updates the config of the TXT.

        Args:
            txt: The base TXT class object.
            port: the port of the motor. 0-3 for M1-M4
        """
        instance = cls(txt, port)
        await txt.update_config()
        return instance

    @property
    def speed(self):
        return self._speed

    @speed.setter
    def speed(self, speed: int):
        self._speed = speed

        if speed > 0:
            self._txt._set_pwm(self._port * 2, speed)
            self._txt._set_pwm(self._port * 2 + 1, 0)
        else:
            self._txt._set_pwm(self._port * 2, 0)
            self._txt._set_pwm(self._port * 2 + 1, -speed)

    @property
    def distance(self):
        return self._distance

    @distance.setter
    def distance(self, distance):
        self._distance = distance
        self._txt._set_motor_distance(self._port, distance)
        self._txt._increment_motor_command_id(self._port)

    @property
    def current_distance(self):
        """The current counter value."""
        return self._txt._get_current_counter_value(self._port)

    @property
    def finished(self):
        """If the motor reached its goal position."""
        # Counter hasn't changed in the last tick
        return self._txt._get_motor_command_id(self._port) == self._txt._get_current_motor_command_id(self._port)

    def stop(self):
        """Stop the motor."""
        self.speed = 0
        self.distance = 0


# noinspection PyProtectedMember
class SyncedMotor:
    """
    Class for running two synced motors.
    """

    def __init__(self, m1: Motor, m2: Motor):
        self.m1 = m1
        self.m2 = m2
        self._txt = m1._txt

        self._speed = 0
        self._distance = 0

        self._sync_motors()

    def _sync_motors(self):
        self._txt._set_motor_sync(self.m1._port, self.m2._port)
        self._txt._set_motor_sync(self.m2._port, self.m1._port)
        self._txt._increment_motor_command_id(self.m1._port)
        self._txt._increment_motor_command_id(self.m2._port)

    @property
    def speed(self):
        return self._speed

    @speed.setter
    def speed(self, speed):
        self._speed = speed
        self.m1.speed = speed
        self.m2.speed = speed

    @property
    def distance(self):
        return self._distance

    @distance.setter
    def distance(self, distance):
        self.m1.distance = distance
        self.m2.distance = distance

    @property
    def current_distance(self):
        """The current counter value."""
        return self.m1.current_distance

    @property
    def finished(self):
        """If the motors reached their goal position."""
        return self.m1.finished and self.m2.finished

    def stop(self):
        """Stop the motors."""
        self.m1.stop()
        self.m2.stop()


# noinspection PyProtectedMember
class Output:
    """Class representing a simple output like a LED."""

    def __init__(self, txt: TXT, port: int):  # port: 0-7
        """
        Create a new output class instance.

        Args:
            txt: The base TXT class object.
            port: The output port. 0-7 for port 1-8.
        """
        self._txt = txt
        self._port = port

        slot = port // 2
        slot_part = port % 2
        if txt.used_output_slots[slot] is not None:
            if isinstance(txt.used_output_slots[slot], list):
                if txt.used_output_slots[slot][slot_part] is not None:
                    raise TXTError(f"Output slot {port} is already used!")
            else:
                TXTError(f"Output slot {port} is already used!")

        if isinstance(txt.used_output_slots[slot], list):
            txt.used_output_slots[slot][slot_part] = self
        else:
            if slot_part == 0:
                txt.used_output_slots[slot] = [self, None]
            else:
                txt.used_output_slots[slot] = [None, self]

        motor_config, input_config = txt._get_config()
        motor_config[slot] = _OutputType.OUTPUT
        txt._set_config(motor_config, input_config)

        self._level = 0

    @classmethod
    async def create(cls, txt: TXT, port: int):
        """
        Create a new Output class. Automatically updates the config of the TXT.

        Args:
            txt: The base TXT class object.
            port: The output port. 0-7 for port 1-8.
        """
        instance = cls(txt, port)
        await txt.update_config()
        return instance

    @property
    def level(self):
        """The current output level (0-512)"""
        return self._level

    @level.setter
    def level(self, level):
        """The current output level (0-512)"""
        self._level = level
        self._txt._set_pwm(self._port, level)


# noinspection PyProtectedMember
class _Input:
    """Base class for input."""

    _CONFIG = (_InputType.SWITCH, _InputMethod.DIGITAL)

    def __init__(self, txt: TXT, port: int):
        """
        Create a new inout class instance.

        Args:
            txt: the base TXT class.
            port: the input port. 0-7 for port I1-I8
        """
        self._txt = txt
        self._port = port

        if txt.used_input_slots[port] is not None:
            raise TXTError(f"Input slot {port} is already used!")

        txt.used_input_slots[port] = self

        motor_config, input_config = txt._get_config()
        input_config[port] = self._CONFIG
        self._txt._set_config(motor_config, input_config)

    @classmethod
    async def create(cls, txt: TXT, port: int) -> Self:
        """
        Create a new input class instance. Automatically updates the TXT config.

        Args:
            txt: the base TXT class.
            port: the input port. 0-7 for port I1-I8
        """
        instance = cls(txt, port)
        await txt.update_config()
        return instance

    @property
    def state(self):
        """The current input value."""
        return self._txt._get_current_input(self._port)


class Button(_Input):
    """Button input."""

    @property
    def state(self) -> bool:
        return bool(super().state)


class Resistor(_Input):
    """Resistor input."""

    _CONFIG = (_InputType.RESISTOR, _InputMethod.ANALOG)

    @property
    def ntc_temperature(self):
        """Converts the current input to a temperature."""

        value = self.state
        if value == 0:
            raise TXTError("Invalid input value 0 for ntc-temperature calculation.")

        # Calculation taken from ftrobopy
        x = log(value)
        y = x * x * 1.39323522
        z = x * -43.9417405
        return y + z + 271.870481


class Ultrasonic(_Input):
    """Ultrasonic input."""
    _CONFIG = (_InputType.ULTRASONIC, _InputMethod.ANALOG)


class Voltage(_Input):
    """Voltage input."""
    _CONFIG = (_InputType.VOLTAGE, _InputMethod.ANALOG)


class Color(Enum):
    WHITE = 0
    RED = 1
    BLUE = 2


class ColorSensor(Voltage):
    """Color sensor input."""

    @property
    def color(self) -> Color:
        """The current color."""

        v = self.state
        if v < 200:
            return Color.WHITE
        elif v < 1000:
            return Color.RED

        return Color.BLUE


class TrailFollower(Voltage):
    """Trail follower input."""
    _CONFIG = (_InputType.VOLTAGE, _InputMethod.ANALOG)  # Why is this analog?

    @property
    def state(self) -> bool:
        """If a trail is recognized or not."""

        s = super().state

        # Original comment in ftrobopy: in direct-mode digital 1 is set by motor-shield if voltage is > 600mV
        if s == 1:
            return True

        return s > 600

    @property
    def voltage(self):
        """The raw input value."""
        return super().state


class Sound(IntEnum):
    """The sounds that the TXT can play. The sound names are not the original ones!"""

    EMPTY = 0
    AIRPLANE = 1
    ALARM = 2
    BELL = 3
    BRAKES = 4
    CAR_HORN_SHORT = 5
    CAR_HORN_LONG = 6
    BREAKING_WOOD = 7
    EXCAVATOR = 8
    FANTASY_1 = 9
    FANTASY_2 = 10
    FANTASY_3 = 11
    FANTASY_4 = 12
    FARM = 13
    FIRE_SIREN = 14
    CAMPFIRE = 15
    FORMULA1_CAR = 16
    HELICOPTER = 17
    HYDRAULIC = 18
    RUNNING_ENGINE = 19
    STARTING_ENGINE = 20
    PROPELLER_PLANE = 21
    ROLLER_COASTER = 22
    SHIP_HORN = 23
    TRACTOR = 24
    TRUCK = 25
    WINK = 26
    DRIVING_NOISE = 27
    RAISE_HEAD = 28
    TILT_HEAD = 29


# noinspection PyProtectedMember
class Speaker:
    """Class for playing sounds on the TXT."""

    def __init__(self, txt: TXT):
        self._txt = txt

    def play_sound(self, sound: Sound, repeat: int = 1):
        """Play the given sound on the TXT."""
        self._txt._set_sound_index(int(sound))
        self._txt._set_sound_repeat(repeat)
        self._txt._increment_sound_command_id()

    def stop_sound(self):
        """Stop the current playing sound."""
        self.play_sound(Sound.EMPTY)

    @property
    def finished(self):
        """If the current sound has finished playing."""
        return self._txt._buffer.current_sound_cmd_id[0] == self._txt._get_sound_command_id()

    async def wait_finished(self):
        """Wait for the current sound to finish playing."""
        while not self.finished:
            await self._txt.wait()


# noinspection PyProtectedMember
class Camera:
    """Class for using the TXT camera on the USB port."""

    def __init__(self, txt: TXT):
        self._txt = txt
        self._host, self._port = txt._get_camera_host()
        self._num_frames_ready = 0
        self._frame_width = 0
        self._frame_height = 0
        self._frame_size_raw = 0
        self._frame_size_compressed = 0
        self._frame_data = bytearray()

        self._stop_event = asyncio.Event()
        self._writer: asyncio.StreamWriter | None = None
        self._reader: asyncio.StreamReader | None = None

        self._task = None

    async def start(self):
        """Start the camera."""
        if self._task is None:
            await self._txt._start_camera_on_txt()
            self._task = asyncio.create_task(self._run())

    async def stop(self):
        """Stop the camera."""
        self._stop_event.set()
        await self._txt._stop_camera_on_txt()

        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()

        if self._task is not None:
            await self._task

    async def _run(self):
        await self._connect()

        expected_response_id = 0xBDC2D7A1
        ack_id = 0xADA09FBA
        header_format_string = "<Iihhii"
        header_size = struct.calcsize(header_format_string)

        while not self._stop_event.is_set():
            header = await self._reader.readexactly(header_size)
            response = struct.unpack(header_format_string, header)

            if response[0] != expected_response_id:
                raise TXTConnectionError(
                    f"ResponseID {hex(response[0])} does not match required ID {hex(expected_response_id)}")

            self._num_frames_ready = response[1]
            self._frame_width = response[2]
            self._frame_height = response[3]
            self._frame_size_raw = response[4]
            self._frame_size_compressed = response[5]
            self._frame_data = bytearray()

            remaining = self._frame_size_compressed
            buffer = bytearray()
            while remaining > 0:
                chunk = await self._reader.read(1500)
                if not chunk:
                    raise TXTConnectionError("Connection to camera lost!")
                buffer.extend(chunk)
                remaining -= len(chunk)

            self._frame_data = buffer
            self._writer.write(
                struct.pack("<I", ack_id)
            )
            await self._writer.drain()

    async def _connect(self):
        attempts = 0
        while attempts <= 150 and not self._stop_event.is_set():
            try:
                self._reader, self._writer = await asyncio.open_connection(self._host, self._port)
                return
            except ConnectionError:
                attempts += 1
                await asyncio.sleep(0.02)

        raise TXTConnectionError("Camera is not connected!")

    @property
    def last_frame(self):
        """The last frame the camera took."""
        return bytes(self._frame_data)

    @property
    def frame_size(self):
        """The current frame size."""
        return self._frame_width, self._frame_height
