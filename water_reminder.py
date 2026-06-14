import time
import json
import os
import board
import pwmio
import displayio
import terminalio
import asyncio
from adafruit_display_text import label

# Global config cache and task tracking
CONFIG_FILE = "/sd/water_config.json"
_memory_config = {"enabled": False, "interval": 20}
water_task = None
last_reminder_time = 0
interval_seconds = 0

def load_config():
    global _memory_config
    try:
        # Check if SD card is mounted
        try:
            import storage
            storage.getmount("/sd")
            sd_mounted = True
        except Exception:
            sd_mounted = False

        if sd_mounted:
            # Check if file exists without crashing if not
            try:
                os.stat(CONFIG_FILE)
                with open(CONFIG_FILE, "r") as f:
                    cfg = json.load(f)
                    _memory_config.update(cfg)
            except OSError:
                pass # Config file doesn't exist yet
    except Exception as e:
        print("Error reading water config:", e)
    return _memory_config

def save_config(enabled, interval):
    global _memory_config
    _memory_config["enabled"] = enabled
    _memory_config["interval"] = interval
    try:
        try:
            import storage
            storage.getmount("/sd")
            sd_mounted = True
        except Exception:
            sd_mounted = False

        if sd_mounted:
            with open(CONFIG_FILE, "w") as f:
                json.dump(_memory_config, f)
    except Exception as e:
        print("Error saving water config:", e)

def get_time_remaining_str():
    global last_reminder_time, interval_seconds
    if last_reminder_time == 0 or interval_seconds == 0:
        return "Calculating..."
    elapsed = time.monotonic() - last_reminder_time
    remaining = int(interval_seconds - elapsed)
    if remaining <= 0:
        return "Now!"
    mins = remaining // 60
    secs = remaining % 60
    return f"{mins}m {secs}s"

async def trigger_reminder(sc, mv, keypad):
    print("Triggering water reminder alert!")
    
    # Save active screen and keys
    oled = sc.get_oled()
    previous_group = oled.root_group
    previous_key_functions = keypad.key_functions

    # Create visual alarm screen
    reminder_group = displayio.Group()
    
    # Yellow top strip background equivalent (header text)
    header_label = label.Label(terminalio.FONT, text="*** DRINK WATER ***", color=0xFFFFFF, x=5, y=6)
    # Centered big alert text
    main_label = label.Label(terminalio.FONT, text="Time to drink\nsome water!", color=0xFFFFFF, x=10, y=30)
    # Action key
    footer_label = label.Label(terminalio.FONT, text="Press any key...", color=0xFFFFFF, x=5, y=55)

    reminder_group.append(header_label)
    reminder_group.append(main_label)
    reminder_group.append(footer_label)

    # Set as active root group
    oled.root_group = reminder_group

    # Play piezo alert pattern (three double beeps)
    try:
        buzzer = pwmio.PWMOut(board.GP20, frequency=2000, duty_cycle=0, variable_frequency=True)
        for _ in range(3):
            # Beep 1
            buzzer.duty_cycle = 32768
            await asyncio.sleep(0.08)
            buzzer.duty_cycle = 0
            await asyncio.sleep(0.05)
            # Beep 2
            buzzer.duty_cycle = 32768
            await asyncio.sleep(0.08)
            buzzer.duty_cycle = 0
            await asyncio.sleep(0.3)
        buzzer.deinit()
    except Exception as e:
        print("Buzzer alert failed:", e)

    # Block cooperatively until a key is pressed to dismiss
    dismissed = False
    
    def dismiss_action():
        nonlocal dismissed
        dismissed = True

    keypad.key_functions = keypad.default_key_mappings()
    for key in keypad.key_functions:
        keypad.key_functions[key] = dismiss_action

    while not dismissed:
        await asyncio.sleep(0.05)

    # Wait until user releases the key to avoid key spillover
    while keypad.keypad.pressed_keys:
        await asyncio.sleep(0.05)

    # Restore pre-alarm state
    oled.root_group = previous_group
    keypad.key_functions = previous_key_functions
    print("Water reminder alert dismissed successfully.")

async def water_reminder_loop(sc, mv, keypad):
    global last_reminder_time, interval_seconds
    while True:
        config = load_config()
        if not config.get("enabled", False):
            break

        interval_mins = config.get("interval", 20)
        interval_seconds = interval_mins * 60
        last_reminder_time = time.monotonic()

        seconds_remaining = interval_seconds
        while seconds_remaining > 0:
            await asyncio.sleep(1)
            
            # Re-load config to check for dynamic updates (e.g. interval changed or turned off)
            config = load_config()
            if not config.get("enabled", False):
                return
                
            new_interval = config.get("interval", 20)
            if new_interval != interval_mins:
                interval_mins = new_interval
                interval_seconds = interval_mins * 60
                last_reminder_time = time.monotonic()
                seconds_remaining = interval_seconds
            else:
                seconds_remaining = int(interval_seconds - (time.monotonic() - last_reminder_time))

        await trigger_reminder(sc, mv, keypad)

def init_background(sc, mv, keypad):
    global water_task
    config = load_config()
    if config.get("enabled", False):
        if water_task is None:
            try:
                loop = asyncio.get_event_loop()
                water_task = loop.create_task(water_reminder_loop(sc, mv, keypad))
                print("Water reminder background task scheduled successfully.")
            except Exception as e:
                print("Failed to schedule water reminder task:", e)

def update_settings(enabled, interval_mins, sc, mv, keypad):
    global water_task
    save_config(enabled, interval_mins)
    
    if water_task is not None:
        try:
            water_task.cancel()
        except Exception:
            pass
        water_task = None

    if enabled:
        try:
            loop = asyncio.get_event_loop()
            water_task = loop.create_task(water_reminder_loop(sc, mv, keypad))
            print("Water reminder task restarted with new settings.")
        except Exception as e:
            print("Failed to restart water reminder task:", e)

class WaterReminder:
    def __init__(self, sc, mv, keypad):
        self.sc = sc
        self.mv = mv
        self.keypad = keypad
        self.is_active = True
        self.menu_count = 0
        
        # Load local settings
        cfg = load_config()
        self.enabled = cfg.get("enabled", False)
        self.interval = cfg.get("interval", 20)

    def start(self):
        self.is_active = True
        self.menu_count = 0
        self.setup_keypad()
        self.draw_screen()
        
        while self.is_active:
            self.keypad.process_keypress(True)
            self.draw_screen()
            time.sleep(0.2)

    def setup_keypad(self):
        self.keypad.reset()
        self.keypad.key_functions = self.keypad.default_key_mappings()
        self.keypad.key_functions["A"] = self.handle_select
        self.keypad.key_functions["B"] = self.scroll_up
        self.keypad.key_functions["C"] = self.scroll_down
        self.keypad.key_functions["D"] = self.handle_back

    def draw_screen(self):
        status_str = "ON" if self.enabled else "OFF"
        time_left_str = get_time_remaining_str() if self.enabled else "Disabled"
        
        opt0 = f"{'> ' if self.menu_count == 0 else '  '}Status: {status_str}"
        opt1 = f"{'> ' if self.menu_count == 1 else '  '}Interval: {self.interval}m"
        
        content = f"{opt0}\n{opt1}\nNext: {time_left_str}"
        self.mv.show_screen(content, "Water Reminder", 5, 22, l_menu="Select", r_menu="Back")

    def scroll_up(self):
        self.menu_count = (self.menu_count - 1) % 2
        self.draw_screen()
        time.sleep(0.15)

    def scroll_down(self):
        self.menu_count = (self.menu_count + 1) % 2
        self.draw_screen()
        time.sleep(0.15)

    def handle_select(self):
        if self.menu_count == 0:
            # Toggle ON/OFF
            self.enabled = not self.enabled
            update_settings(self.enabled, self.interval, self.sc, self.mv, self.keypad)
            self.draw_screen()
            time.sleep(0.2)
        elif self.menu_count == 1:
            # Edit interval
            self.edit_interval()

    def edit_interval(self):
        editing = True
        temp_interval = self.interval

        def inc_interval():
            nonlocal temp_interval
            if temp_interval < 120:
                temp_interval += 1
                draw_edit_screen()
            time.sleep(0.15)

        def dec_interval():
            nonlocal temp_interval
            if temp_interval > 1:
                temp_interval -= 1
                draw_edit_screen()
            time.sleep(0.15)

        def save_interval():
            nonlocal editing
            self.interval = temp_interval
            update_settings(self.enabled, self.interval, self.sc, self.mv, self.keypad)
            editing = False
            time.sleep(0.2)

        def cancel_interval():
            nonlocal editing
            editing = False
            time.sleep(0.2)

        def draw_edit_screen():
            content = f"Set Interval:\n <  {temp_interval} Min  >\n\n[B]:+1m  [C]:-1m"
            self.mv.show_screen(content, "Edit Interval", 5, 22, l_menu="Save", r_menu="Cancel")

        # Set temporary key mappings for interval editing
        self.keypad.key_functions = self.keypad.default_key_mappings()
        self.keypad.key_functions["A"] = save_interval
        self.keypad.key_functions["B"] = inc_interval
        self.keypad.key_functions["C"] = dec_interval
        self.keypad.key_functions["D"] = cancel_interval

        draw_edit_screen()

        while editing:
            self.keypad.process_keypress(True)
            time.sleep(0.1)

        # Restore normal keypad settings
        self.setup_keypad()
        self.draw_screen()

    def handle_back(self):
        self.is_active = False
        time.sleep(0.2)
