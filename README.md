# TXTControl

A Pythonic, asyncio-based ftrobopy implementation for the Fischertechnik TXT Controller.

> **Warning!**
>
> Even when I think this program should work, I didn't test it duo to my broken accu. If you want to use it now, do it
> at your own risk. If you find any error, please open a new GitHub Issue. I will try to test the program as fast as
> possible.

## What is TXTControl?

TXTControl is an asynchronous high-level alternative to [ftrobopy](https://github.com/ftrobopy/ftrobopy). It allows
easy integration into modern existing applications.

## Motivation

When I started programming my TXT robot, I had to use ftrobopy as there were no alternatives. After a lot of
frustrations about this very unpythonic library, which looked as if it was the first Python program by a C programmer,
I finally brought by robot to life. But my code looked like C, not Python. Then, a few years later, I wrote this program
to help people with the same problem.

> **New to asyncio?**
> Check out the official Python asyncio tutorial: https://docs.python.org/3/library/asyncio.html

## Example

The following example will play a sound if the button is pressed otherwise, the motor will run. The program ends when
the terminator button is hit.

```python
from txtcontrol import TXT, Motor, Button, Speaker, Sound


async def main():
    with TXT() as txt:
        motor = await Motor.create(txt, 0)
        button = await Button.create(txt, 0)
        terminator_button = await Button.create(txt, 1)
        speaker = Speaker(txt)

        while not terminator_button.state:
            if button.state:
                motor.speed = 512
                speaker.stop_sound()
            else:
                motor.speed = 0
                if speaker.finished:
                    speaker.play_sound(Sound.CAR_HORN_SHORT)

            await txt.wait()  # Wait for the next update intervall
```

## API-Reference

### `TXTError`

Base class for TXT-related errors.

### `TXTConnectionError` (*base: `TXTError`*)

TXT-related ConnectionError.

### `TXT(host: str | None = None, port=65000)`

The class representing the TXT connection.

If `host` is not given, TXTControl tries to find a TXT using the following ports:

1. `192.168.7.2` USB (Ethernet)
2. `192.168.8.2` WLAN
3. `192.168.9.2` Bluetooth

#### Example

```python
from txtcontrol import TXT

async with TXT() as txt:
    print("TXT connected!")
```

#### `async query_status()`

Query the current status of the TXT.

Returns: device name, device version

#### `async update_config()`

Transfer the current configuration to the TXT.

This function is automatically called when using the `create` method to create inputs or outputs.

#### `async wait()`

Wait until the next time the TXT sends new input values.

#### `async sync_data()`

Contextmanager that syncs multiple commands without sending the current state to the TXT.

**Warnings**:
This method just blocks the connection. Long-running operations will result in a deadlock or in a
TXTConnectionError!

### `Motor(txt: TXT, port: int)`

Class representing a TXT motor.

#### `async create(txt: TXT, port: int)`

Create a new Motor class. Automatically updates the config of the TXT.

Args:

* txt: The base TXT class object.
* port: the port of the motor. 0–3 for M1–M4

#### `property speed: int`

The current motor speed.

#### `property distance: int`

The current target distance.

#### `property current_distance: int`

The current value of the motor counter (C1-C4).

#### `property finished: bool`

If the motor reached its goal position.

#### `stop()`

Stop the motor.

### `SyncedMotor(m1: Motor, m2: Motor)`

Class for running two synced motors.

#### `property speed: int`

The current motor speed.

#### `property distance: int`

The current target distance.

#### `property current_distance: int`

The current value of the motor counter (C1-C4).

#### `property finished: bool`

If the motors reached their goal position.

#### `stop()`

Stop the motors.

### `Output(txt: TXT, port: int)`

Class representing a simple output like a LED.

#### `async create(txt: TXT, port: int)`

Create a new Output class. Automatically updates the config of the TXT.

Args:

* txt: The base TXT class object.
* port: The output port. 0-7 for port 1-8.

#### `property level: int`

The current output level (0–512)

### `_Input(txt: TXT, port: int)`

Base class for input. Should not be used directly!

#### `async create(txt: TXT, port: int)`

Create a new input class instance. Automatically updates the TXT config.

Args:

* txt: the base TXT class.
* port: the input port. 0–7 for port I1-I8

#### `property state: int`

The current input value.

### `Button` (*base: `_Input`*)

#### `property state: bool`

The current input value (pressed or not).

### `Resistor` (*base: `_Input`*)

Resistor input.

#### `property ntc_temperature: int`

Converts the current input to a temperature

### `Ultrasonic` (*base: `_Input`*)

Ultrasonic input.

### `Voltage` (*base: `_Input`*)

Voltage input.

### `enum Color`

Values:

* WHITE = 0
* RED = 1
* BLUE = 2

### `ColorSensor` (*base: `Voltage`*)

Color sensor input.

#### `property color: Color`

The current color.

### `TrailFollower` (*base: `Voltage`*)

Trail follower input.

### `property state: bool`

If a trail is recognized or not.

### `property voltage: int`

The raw input value.

### `enum Sound`

The sounds that the TXT can play. The sound names are not the original ones!

Values:

* EMPTY = 0
* AIRPLANE = 1
* ALARM = 2
* BELL = 3
* BRAKES = 4
* CAR_HORN_SHORT = 5
* CAR_HORN_LONG = 6
* BREAKING_WOOD = 7
* EXCAVATOR = 8
* FANTASY_1 = 9
* FANTASY_2 = 10
* FANTASY_3 = 11
* FANTASY_4 = 12
* FARM = 13
* FIRE_SIREN = 14
* CAMPFIRE = 15
* FORMULA1_CAR = 16
* HELICOPTER = 17
* HYDRAULIC = 18
* RUNNING_ENGINE = 19
* STARTING_ENGINE = 20
* PROPELLER_PLANE = 21
* ROLLER_COASTER = 22
* SHIP_HORN = 23
* TRACTOR = 24
* TRUCK = 25
* WINK = 26
* DRIVING_NOISE = 27
* RAISE_HEAD = 28
* TILT_HEAD = 29

### `Speaker(txt: TXT)`

Class for playing sounds on the TXT.

#### `play_sound(sound: Sound, repeat: int = 1)`

Play the given sound on the TXT.

#### `stop_sound()`

Stop the current playing sound.

#### `property finished: bool`

If the current sound has finished playing.

#### `async wait_finished()`

Wait for the current sound to finish playing.

### `Camera(txt: TXT)`

#### `async start()`

Start the camera.

#### `async stop()`

Stop the camera.

#### `property last_frame: bytes`

The last frame the camera took.

#### `property frame_size: tuple[int, int]`

The current frame size.
