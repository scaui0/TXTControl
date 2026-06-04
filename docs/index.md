# TXTControl

A Pythonic, asyncio-based ftrobopy implementation for the Fischertechnik TXT Controller.

!!! danger "Warning"

    Even when I think this program should work, I didn't test it duo to my broken accu. If you want to use it now, do it
    at your own risk. If you find any error, please open a new GitHub Issue. I will try to test the program as fast as
    possible.

## What is TXTControl?

TXTControl is an asynchronous high-level alternative to [ftrobopy](https://github.com/ftrobopy/ftrobopy). It allows
easy integration into modern existing applications.

## Motivation

When I started programming my TXT robot, I had to use ftrobopy as there were no alternatives. After a lot of
frustrations about this very unpythonic library, which looked as if it was the first Python program by a C programmer,
I finally brought by robot to life. Sadly, my code looked like C, not like Python. Then, a few years later, I wrote this
program to help people like me who wanted to write Pythonic code.

!!! info "New to asyncio?"

    Check out the 
    [official asyncio owerview](https://docs.python.org/3/howto/a-conceptual-overview-of-asyncio.html#a-conceptual-overview-of-asyncio)
    or the [library reference](https://docs.python.org/3/library/asyncio.html).

## Example

The following example will play a sound if the button is pressed otherwise, the motor will run. The program ends when
the terminator button is hit.

```python
from txtcontrol import TXT, Motor, Button, Speaker, Sound


async def main():
    async with TXT() as txt:
        motor = await Motor.create(txt, 0)
        button = await Button.create(txt, 0)
        terminator_button = await Button.create(txt, 1)
        speaker = Speaker(txt)

        while not terminator_button.state:
            if button.state:
                motor.speed = 0
                if speaker.finished:
                    speaker.play_sound(Sound.CAR_HORN_SHORT)
            else:
                motor.speed = 512
                speaker.stop_sound()

            await txt.wait()  # Wait for the next update intervall
```

For more examples see [Examples](examples.md)
