# Examples

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
