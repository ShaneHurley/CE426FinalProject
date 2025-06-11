#!/usr/bin/env python3
import RPi.GPIO as GPIO
import threading
import time
from queue import Queue

# === Configuration ===
NORMAL_CODE = "1234"       # Normal unlock code
LOCKDOWN_CODE = "9999"     # Lockdown code
WINDOW_UNLOCK_TIME = 15    # seconds the window stays unlocked
WINDOW_INTERVAL = 30       # time between unlock windows (s)
TEMP_UNLOCK_TIME = 10      # unlock time for Normal Mode (s)

ROW_PINS = [5, 6, 13, 19]
COL_PINS = [12, 16, 20, 21]
KEY_MAP = [
    ['1','2','3','A'],
    ['4','5','6','B'],
    ['7','8','9','C'],
    ['*','0','#','D']
]
RELAY_PIN = 18

GPIO.setmode(GPIO.BCM)
for r in ROW_PINS:
    GPIO.setup(r, GPIO.OUT, initial=GPIO.HIGH)
for c in COL_PINS:
    GPIO.setup(c, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(RELAY_PIN, GPIO.OUT, initial=GPIO.LOW)

# === Relay Control ===
class RelayControl:
    @staticmethod
    def lock():
        GPIO.output(RELAY_PIN, GPIO.LOW)
    @staticmethod
    def unlock():
        GPIO.output(RELAY_PIN, GPIO.HIGH)

# === System States ===
LOCKDOWN = 'LOCKDOWN'
WINDOW = 'WINDOW'
NORMAL = 'NORMAL'

class Lockbox:
    def __init__(self):
        self.state = NORMAL
        self.state_lock = threading.Lock()
        self.lockdown_active = False
        self.window_active = False

    def enter_lockdown(self):
        with self.state_lock:
            self.state = LOCKDOWN
            self.lockdown_active = True
            RelayControl.lock()
            print("[STATE] LOCKDOWN")

    def exit_lockdown(self):
        with self.state_lock:
            self.state = NORMAL
            self.lockdown_active = False
            RelayControl.lock()
            print("[STATE] LOCKDOWN CLEARED → NORMAL MODE")

    def trigger_window_unlock(self):
        with self.state_lock:
            if not self.lockdown_active:
                self.window_active = True
                self.state = WINDOW
                RelayControl.unlock()
                print(f"[STATE] WINDOW UNLOCK for {WINDOW_UNLOCK_TIME} seconds")

    def end_window_unlock(self):
        with self.state_lock:
            self.window_active = False
            self.state = NORMAL
            RelayControl.lock()
            print("[STATE] WINDOW CLOSED → NORMAL MODE")

    def temporary_unlock(self):
        with self.state_lock:
            if self.lockdown_active:
                print("[INFO] LOCKDOWN ACTIVE - IGNORING NORMAL UNLOCK")
                return
            if self.window_active:
                print("[INFO] WINDOW UNLOCK ACTIVE - NO NEED FOR TEMPORARY UNLOCK")
                return
            RelayControl.unlock()
            print(f"[STATE] TEMPORARY UNLOCK for {TEMP_UNLOCK_TIME} seconds")
            time.sleep(TEMP_UNLOCK_TIME)
            RelayControl.lock()
            print("[STATE] TEMPORARY UNLOCK ENDED → NORMAL MODE")

class KeypadThread(threading.Thread):
    def __init__(self, key_queue):
        super().__init__(daemon=True)
        self.key_queue = key_queue

    def run(self):
        while True:
            for i, r in enumerate(ROW_PINS):
                GPIO.output(r, GPIO.LOW)
                for j, c in enumerate(COL_PINS):
                    if GPIO.input(c) == GPIO.HIGH:
                        self.key_queue.put(KEY_MAP[i][j])
                        time.sleep(0.3)  # debounce
                GPIO.output(r, GPIO.HIGH)
            time.sleep(0.05)

class StateMachineThread(threading.Thread):
    def __init__(self, lockbox, key_queue):
        super().__init__(daemon=True)
        self.lockbox = lockbox
        self.key_queue = key_queue
        self.buffer = ""

    def run(self):
        while True:
            key = self.key_queue.get()
            print(f"[KEY] {key}")
            if key == '*':
                self.buffer = ""
                print("[BUFFER CLEARED]")
                continue
            self.buffer += key
            if len(self.buffer) >= 4:
                self.process_code()
                self.buffer = ""

    def process_code(self):
        if self.buffer == LOCKDOWN_CODE:
            if self.lockbox.lockdown_active:
                self.lockbox.exit_lockdown()
            else:
                self.lockbox.enter_lockdown()
        elif self.buffer == NORMAL_CODE:
            self.lockbox.temporary_unlock()
        else:
            print("[INFO] INVALID CODE")

class WindowModeThread(threading.Thread):
    def __init__(self, lockbox):
        super().__init__(daemon=True)
        self.lockbox = lockbox

    def run(self):
        while True:
            time.sleep(WINDOW_INTERVAL)
            if not self.lockbox.lockdown_active:
                self.lockbox.trigger_window_unlock()
                time.sleep(WINDOW_UNLOCK_TIME)
                self.lockbox.end_window_unlock()

def main():
    lockbox = Lockbox()
    key_queue = Queue()

    threads = [
        KeypadThread(key_queue),
        StateMachineThread(lockbox, key_queue),
        WindowModeThread(lockbox)
    ]
    for t in threads:
        t.start()

    print("Lockbox system running. Press keys on keypad.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        GPIO.cleanup()

if __name__ == "__main__":
    main()