"""Clock/data transport shared by the TM1637 and TM1640 display modules."""

import time


class DisplayLink:
    """Send display bytes LSB first; GPIO ownership belongs to the caller."""

    def __init__(self, gpio, clk, dio, ack=False):
        self.gpio, self.clk, self.dio = gpio, clk, dio
        self.ack = ack
        self.missing_ack = 0

    def delay(self):
        time.sleep(0.00001)

    def start(self):
        self.gpio.output(self.dio, 1)
        self.gpio.output(self.clk, 1)
        self.delay()
        self.gpio.output(self.dio, 0)
        self.delay()
        self.gpio.output(self.clk, 0)

    def stop(self):
        self.gpio.output(self.clk, 0)
        self.gpio.output(self.dio, 0)
        self.delay()
        self.gpio.output(self.clk, 1)
        self.delay()
        self.gpio.output(self.dio, 1)
        self.delay()

    def write_byte(self, value):
        for bit in range(8):
            self.gpio.output(self.clk, 0)
            self.gpio.output(self.dio, (value >> bit) & 1)
            self.delay()
            self.gpio.output(self.clk, 1)
            self.delay()
        self.gpio.output(self.clk, 0)
        if self.ack:  # TM1637 has an ACK clock; TM1640 does not.
            self.gpio.setup(self.dio, self.gpio.IN, pull_up_down=self.gpio.PUD_UP)
            try:
                self.delay()
                self.gpio.output(self.clk, 1)
                self.delay()
                if self.gpio.input(self.dio):
                    self.missing_ack += 1
            finally:
                self.gpio.output(self.clk, 0)
                self.gpio.setup(self.dio, self.gpio.OUT, initial=self.gpio.LOW)
            self.delay()

    def send(self, values):
        self.start()
        try:
            for value in values:
                self.write_byte(value)
        finally:
            self.stop()

    def show(self, frame, brightness):
        self.send([0x80])
        self.write_frame(frame)
        self.send([0x88 | brightness])

    def write_frame(self, frame):
        self.send([0x40])
        self.send([0xC0, *frame])
