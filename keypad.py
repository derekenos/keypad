
from array import array
from utime import sleep_ms
from micropython import (
    alloc_emergency_exception_buf,
    schedule,
)
from machine import (
    Pin,
    Timer,
)


alloc_emergency_exception_buf(100)


###############################################################################
# Led Routines
###############################################################################

LED_COL_1_2_PIN = Pin(19, Pin.IN)
LED_COL_3_4_PIN = Pin(23, Pin.IN)
LED_ROW_1_PIN = Pin(25, Pin.OUT)
LED_ROW_2_PIN = Pin(21, Pin.OUT)
LED_ROW_3_PIN = Pin(22, Pin.OUT)

NUM_BRIGHTNESS_LEVELS = 8

# Alias the max brightness level for easy-non-the-eyes LED state array tables.
X = NUM_BRIGHTNESS_LEVELS - 4


led_states = array('B', (
    0, 0, 0, 0,
    0, 0, 0, 0,
    0, 0, 0, 0,
))

current_led_col_num = 1
current_brightness_frame_num = 1


def advance_active_led_col(timer):
    global current_led_col_num
    global current_brightness_frame_num

    LED_COL_1_2_PIN.init(Pin.IN)
    LED_COL_3_4_PIN.init(Pin.IN)

    active_col_val = 0 if current_led_col_num in (1, 3) else 1
    inactive_row_val = active_col_val
    active_row_val = inactive_row_val ^ 1

    col_idx = current_led_col_num - 1

    row_1_val = led_states[col_idx]
    row_2_val = led_states[4 + col_idx]
    row_3_val = led_states[8 + col_idx]

    LED_ROW_1_PIN.value(active_row_val if current_brightness_frame_num <=
                        row_1_val else inactive_row_val)
    LED_ROW_2_PIN.value(active_row_val if current_brightness_frame_num <=
                        row_2_val else inactive_row_val)
    LED_ROW_3_PIN.value(active_row_val if current_brightness_frame_num <=
                        row_3_val else inactive_row_val)

    if current_led_col_num in (1, 2):
        LED_COL_1_2_PIN.value(active_col_val)
        LED_COL_1_2_PIN.init(Pin.OUT)
    else:
        LED_COL_3_4_PIN.value(active_col_val)
        LED_COL_3_4_PIN.init(Pin.OUT)

    current_led_col_num += 1
    if current_led_col_num > 4:
        current_led_col_num = 1

        current_brightness_frame_num += 1
        if current_brightness_frame_num > NUM_BRIGHTNESS_LEVELS:
            current_brightness_frame_num = 1


# Initialize the LED scanning timer interrupt.
Timer(0).init(freq=8000, mode=Timer.PERIODIC, callback=advance_active_led_col)


###############################################################################
# Switch Routines
###############################################################################

SW_COL_PINS = (
    Pin(34, Pin.IN), # No pull-up available on pin 34
    Pin(38, Pin.IN), # No pull-up available on pin 38
    Pin(35, Pin.IN), # No pull-up available on pin 35
    Pin(18, Pin.IN, Pin.PULL_UP),
)

SW_ROW_PINS = (
    Pin(33, Pin.OUT, value=0),
    Pin(32, Pin.IN),
    Pin(26, Pin.IN),
)

DEBOUNCE_COUNT_TARGET = 2

switch_last_read_states = array('B', (
    1, 1, 1, 1,
    1, 1, 1, 1,
    1, 1, 1, 1,
))

switch_debounce_counters = array('B', (
    0, 0, 0, 0,
    0, 0, 0, 0,
    0, 0, 0, 0,
))

switch_states = array('B', (
    1, 1, 1, 1,
    1, 1, 1, 1,
    1, 1, 1, 1,
))

current_switch_row_num = 1


class Empty(Exception): pass
class Full(Exception): pass


class Buffer():
    def __init__(self, size):
        self.buffer = array('B', [0 for i in range(size)])
        self.max_length = size
        self.length = 0
        self.max_i = size - 1
        self.read_i = 0
        self.write_i = 0

    def write(self, val):
        if self.length == self.max_length:
            raise Full
        self.buffer[self.write_i] = val
        self.length += 1
        if self.write_i < self.max_i:
            self.write_i += 1
        else:
            self.write_i = 0

    def read(self):
        if self.length == 0:
            raise Empty
        val = self.buffer[self.read_i]
        self.length -= 1
        if self.read_i < self.max_i:
            self.read_i += 1
        else:
            self.read_i = 0
        return val


button_down_event_buffer = Buffer(12)
button_down_event_buffer_write = button_down_event_buffer.write
button_up_event_buffer = Buffer(12)
button_up_event_buffer_write = button_up_event_buffer.write


def read_switches(timer):
    global current_switch_row_num
    global switch_last_read_states
    global switch_debounce_counters
    global switch_states
    global button_down_event_buffer_write

    # Get the last switch states and debounce counters.
    current_row_idx = current_switch_row_num - 1
    current_row_offset = current_row_idx * 4

    for col_offset in (0, 1, 2, 3):
        offset = current_row_offset + col_offset

        # Read the current switch value.
        sw_val = SW_COL_PINS[col_offset].value()

        if sw_val != switch_last_read_states[offset]:
            # If current state != to last, reset the debounce counter and
            # save this state as last.
            switch_debounce_counters[offset] = 0
            switch_last_read_states[offset] = sw_val
        elif switch_debounce_counters[offset] < DEBOUNCE_COUNT_TARGET:
            # If it hasn't reached the debounce target, increment the count.
            switch_debounce_counters[offset] += 1
        elif switch_states[offset] != sw_val:
            # Switch state is same as last and debounce target has been
            # reached - record the switch state.
            switch_states[offset] = sw_val

            if sw_val == 0:
                button_down_event_buffer_write(offset)
            # else:
            #     button_up_event_buffer_write(offset)

    current_switch_row_num += 1
    if current_switch_row_num > 3:
        current_switch_row_num = 1

    # Activate the next row.
    if current_switch_row_num == 1:
        SW_ROW_PINS[2].init(Pin.IN)
        SW_ROW_PINS[0].init(Pin.OUT, value=0)
    elif current_switch_row_num == 2:
        SW_ROW_PINS[0].init(Pin.IN)
        SW_ROW_PINS[1].init(Pin.OUT, value=0)
    else:
        SW_ROW_PINS[1].init(Pin.IN)
        SW_ROW_PINS[2].init(Pin.OUT, value=0)


# Initialize the switch scanning timer interrupt.
Timer(1).init(freq=1000, mode=Timer.PERIODIC, callback=read_switches)


###############################################################################
# Utility Functions
###############################################################################

def test_leds():
    global led_states

    led_states_mv = memoryview(led_states)

    for _led_states in (
            (X, 0, 0, 0,
             X, 0, 0, 0,
             X, 0, 0, 0,
            ),

            (0, X, 0, 0,
             0, X, 0, 0,
             0, X, 0, 0,
            ),

            (0, 0, X, 0,
             0, 0, X, 0,
             0, 0, X, 0,
            ),

            (0, 0, 0, X,
             0, 0, 0, X,
             0, 0, 0, X,
            ),

            (X, X, X, X,
             0, 0, 0, 0,
             0, 0, 0, 0,
            ),

            (0, 0, 0, 0,
             X, X, X, X,
             0, 0, 0, 0,
            ),

            (0, 0, 0, 0,
             0, 0, 0, 0,
             X, X, X, X,
            ),

        ):

        led_states_mv[:] = bytearray(_led_states)
        sleep_ms(300)

    # Fade all in
    for brightness_level in range(1, NUM_BRIGHTNESS_LEVELS + 1):
        led_states_mv[:] = bytearray([brightness_level for i in range(12)])
        sleep_ms(100)

    # Fade all out
    for brightness_level in range(NUM_BRIGHTNESS_LEVELS, 0, -1):
        led_states_mv[:] = bytearray([brightness_level for i in range(12)])
        sleep_ms(100)

    # Turn all off
    led_states_mv[:] = bytearray([0 for i in range(12)])


def button_presses():
    while True:
        while button_down_event_buffer.length:
            yield button_down_event_buffer.read()
        sleep_ms(500)


def print_button_presses():
    while True:
        memoryview(led_states)[:] = bytearray([x ^ 1 for x in switch_states])

        while button_down_event_buffer.length:
            print('Button Down: {}'
                  .format(button_down_event_buffer.read() + 1)
            )

        while button_up_event_buffer.length:
            print('Button Up: {}'
                  .format(button_up_event_buffer.read() + 1)
            )

###############################################################################
# The Game
###############################################################################
from random import choice

MIN_SEQUENCE_LENGTH = 1
MAX_SEQUENCE_LENGTH = 7
WIN = True
LOSE = False

ALL_OFF_LED_STATE = array('B', (
    0, 0, 0, 0,
    0, 0, 0, 0,
    0, 0, 0, 0,
))

LOSE_LED_STATE = array('B', (
    X, X, X, X,
    X, 0, 0, X,
    X, X, X, X,
))

BUTTON_INDEXES = range(12)

get_random_button_idx = lambda: choice(BUTTON_INDEXES)
get_random_brightness_level = lambda: choice(range(NUM_BRIGHTNESS_LEVELS))
get_random_led_state = lambda: array('B', [
    get_random_brightness_level() for _ in BUTTON_INDEXES
])


def play():
    get_random_sequence = lambda length: [
        get_random_button_idx() for _ in range(length)
    ]

    led_states_mv = memoryview(led_states)

    def show_the_sequence(sequence):
        for button_idx in sequence:
            led_states_mv[button_idx] = X
            sleep_ms(300)
            led_states_mv[button_idx] = 0
            sleep_ms(300)

    def win():
        for num_states in range(10):
            led_states_mv[:] = get_random_led_state()
            sleep_ms(300)
            led_states_mv[:] = ALL_OFF_LED_STATE

    def lose():
        for num_flashes in range(5):
            led_states_mv[:] = LOSE_LED_STATE
            sleep_ms(300)
            led_states_mv[:] = ALL_OFF_LED_STATE
            sleep_ms(300)

    def get_player_turn_result(sequence):
        seq_i = 0
        last_seq_i = len(sequence) - 1
        for button_idx in button_presses():

            # DEBUG
            print('@ seq_i {} expected {}, got {}'.format(
                seq_i, sequence[seq_i], button_idx))

            if button_idx != sequence[seq_i]:
                return LOSE
            if seq_i == last_seq_i:
                return WIN
            seq_i += 1

    sequence_length = MIN_SEQUENCE_LENGTH
    while sequence_length <= MAX_SEQUENCE_LENGTH:
        sequence = get_random_sequence(sequence_length)

        # DEBUG
        print('sequence: {}'.format(sequence))

        show_the_sequence(sequence)
        if get_player_turn_result(sequence) == WIN:
            sequence_length += 1
        else:
            lose()
            sequence_length = 1
        sleep_ms(500)

    win()
