import time
import json
import os
import gc
import storage
import rtc

try:
    import wifi
    import socketpool
    import adafruit_requests
    import ssl
    wifi_available = True
except ImportError:
    wifi_available = False

import pico_encrypt

# --- Cryptographic Helpers (Pure Python to ensure full compatibility) ---

def sha1(data: bytes) -> bytes:
    """Pure Python SHA-1 implementation."""
    h0 = 0x67452301
    h1 = 0xEFCDAB89
    h2 = 0x98BADCFE
    h3 = 0x10325476
    h4 = 0xC3D2E1F0
    
    orig_len_bits = len(data) * 8
    data = bytearray(data)
    data.append(0x80)
    
    while (len(data) * 8) % 512 != 448:
        data.append(0)
        
    data += orig_len_bits.to_bytes(8, 'big')
    
    for offset in range(0, len(data), 64):
        w = [0] * 80
        for i in range(16):
            w[i] = int.from_bytes(data[offset + i*4 : offset + i*4 + 4], 'big')
            
        for i in range(16, 80):
            val = w[i-3] ^ w[i-8] ^ w[i-14] ^ w[i-16]
            w[i] = ((val << 1) | (val >> 31)) & 0xFFFFFFFF
            
        a, b, c, d, e = h0, h1, h2, h3, h4
        
        for i in range(80):
            if 0 <= i <= 19:
                f = (b & c) | ((~b) & d)
                k = 0x5A827999
            elif 20 <= i <= 39:
                f = b ^ c ^ d
                k = 0x6ED9EBA1
            elif 40 <= i <= 59:
                f = (b & c) | (b & d) | (c & d)
                k = 0x8F1BBCDC
            else:
                f = b ^ c ^ d
                k = 0xCA62C1D6
                
            temp = (((a << 5) | (a >> 27)) + f + e + k + w[i]) & 0xFFFFFFFF
            e = d
            d = c
            c = ((b << 30) | (b >> 2)) & 0xFFFFFFFF
            b = a
            a = temp
            
        h0 = (h0 + a) & 0xFFFFFFFF
        h1 = (h1 + b) & 0xFFFFFFFF
        h2 = (h2 + c) & 0xFFFFFFFF
        h3 = (h3 + d) & 0xFFFFFFFF
        h4 = (h4 + e) & 0xFFFFFFFF
        
    return (h0.to_bytes(4, 'big') +
            h1.to_bytes(4, 'big') +
            h2.to_bytes(4, 'big') +
            h3.to_bytes(4, 'big') +
            h4.to_bytes(4, 'big'))

def hmac_sha1(key: bytes, msg: bytes) -> bytes:
    """HMAC-SHA1 calculation."""
    block_size = 64
    if len(key) > block_size:
        key = sha1(key)
    if len(key) < block_size:
        key = key + b'\x00' * (block_size - len(key))
        
    o_key_pad = bytes(x ^ 0x5c for x in key)
    i_key_pad = bytes(x ^ 0x36 for x in key)
    
    return sha1(o_key_pad + sha1(i_key_pad + msg))

def base32_decode(s: str) -> bytes:
    """Decode a Base32 string into bytes."""
    s = s.upper().strip().replace(" ", "").replace("-", "")
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    char_map = {char: val for val, char in enumerate(alphabet)}
    
    bit_buffer = 0
    bit_count = 0
    res = bytearray()
    
    for char in s:
        if char == '=':
            break
        if char not in char_map:
            raise ValueError(f"Invalid char {char}")
        val = char_map[char]
        bit_buffer = (bit_buffer << 5) | val
        bit_count += 5
        if bit_count >= 8:
            bit_count -= 8
            res.append((bit_buffer >> bit_count) & 0xFF)
            
    return bytes(res)

def get_totp(secret_b32: str, current_time: int) -> str:
    """Compute the 6-digit TOTP code for the given secret and epoch time."""
    try:
        key = base32_decode(secret_b32)
    except Exception:
        return "BAD_SEC"
        
    counter = current_time // 30
    msg = counter.to_bytes(8, 'big')
    
    h = hmac_sha1(key, msg)
    
    offset = h[-1] & 0x0f
    code = ((h[offset] & 0x7f) << 24) | \
           ((h[offset+1] & 0xff) << 16) | \
           ((h[offset+2] & 0xff) << 8) | \
           (h[offset+3] & 0xff)
           
    otp = code % 1000000
    return f"{otp:06d}"

# --- Main App Class ---

class TOTPApp:
    def __init__(self, sc, mv, keypad):
        self.sc = sc
        self.mv = mv
        self.keypad = keypad
        self.splash = self.sc.get_screen()
        self.oled = self.sc.get_oled()
        
        self.is_running = True
        self.accounts = []
        self.menu_count = 0
        self.master_pin = ""
        
        # Files on SD card
        self.encrypted_file = "/sd/totp_secrets.enc"
        self.setup_file = "/sd/totp_setup.json"
        
    def path_exists(self, filepath):
        try:
            os.stat(filepath)
            return True
        except OSError:
            return False

    def connect_wifi(self):
        if not wifi_available:
            return False
        if wifi.radio.connected:
            return True
            
        # Try visible networks with stored credentials
        visible_ssids = set()
        try:
            wifi.radio.enabled = True
            time.sleep(0.1)
            for net in wifi.radio.start_scanning_networks():
                if net.ssid:
                    visible_ssids.add(net.ssid)
            wifi.radio.stop_scanning_networks()
        except Exception:
            pass
            
        saved_creds = {}
        try:
            with open("/sd/wifi_config.json", "r") as f:
                saved_creds = json.load(f)
        except Exception:
            pass
            
        all_creds = {"NO1": "Finish4293"}
        all_creds.update(saved_creds)
        
        for ssid, password in all_creds.items():
            if ssid in visible_ssids:
                try:
                    wifi.radio.connect(ssid, password)
                    if wifi.radio.connected:
                        return True
                except Exception:
                    pass
                    
        # Blind fallback
        if not wifi.radio.connected:
            try:
                wifi.radio.connect('NO1', 'Finish4293')
            except Exception:
                pass
        return wifi.radio.connected

    def sync_time(self):
        self.mv.show_screen("Connecting WiFi...", "Sync Time", 5, 25)
        if not self.connect_wifi():
            self.mv.show_screen("WiFi connection\nfailed!", "Sync Time", 5, 25, r_menu="OK")
            time.sleep(1.5)
            return False
            
        self.mv.show_screen("Fetching time...", "Sync Time", 5, 25)
        try:
            pool = socketpool.SocketPool(wifi.radio)
            requests = adafruit_requests.Session(pool, ssl.create_default_context())
            response = requests.get("https://pico.akshaygupta.me/datetime")
            data = response.json()
            response.close()
            
            # Update Pico RTC
            year = data.get("year", 2026)
            month = data.get("month", 6)
            day = data.get("day", 14)
            hours = data.get("hours", 0)
            minutes = data.get("minutes", 0)
            seconds = data.get("seconds", 0)
            week_day = data.get("week_day", 1)
            
            cp_weekday = (week_day - 1) % 7
            r = rtc.RTC()
            r.datetime = time.struct_time((year, month, day, hours, minutes, seconds, cp_weekday, -1, -1))
            self.mv.show_screen("Time synced\nsuccessfully!", "Sync Time", 5, 25, r_menu="OK")
            time.sleep(1.5)
            return True
        except Exception as e:
            print("Time sync error:", e)
            self.mv.show_screen("Time sync\nfailed!", "Sync Time", 5, 25, r_menu="OK")
            time.sleep(1.5)
            return False

    # --- PIN Screen Handling ---

    def draw_pin_screen(self):
        stars = "* " * len(self.entered_pin)
        spaces = "_ " * (8 - len(self.entered_pin))
        display_str = f"Enter PIN:\n{stars}{spaces}"
        self.mv.show_screen(display_str, "Master PIN", 5, 25, l_menu="Submit", r_menu="Exit")

    def pin_press(self, char):
        if len(self.entered_pin) < 8:
            self.entered_pin += char
            self.draw_pin_screen()
            time.sleep(0.15)

    def pin_backspace(self):
        if len(self.entered_pin) > 0:
            self.entered_pin = self.entered_pin[:-1]
            self.draw_pin_screen()
            time.sleep(0.15)

    def pin_cancel(self):
        self.pin_cancelled = True
        time.sleep(0.15)

    def pin_submit(self):
        self.pin_submitted = True
        time.sleep(0.15)

    def get_pin_input(self):
        self.entered_pin = ""
        self.pin_submitted = False
        self.pin_cancelled = False
        self.draw_pin_screen()
        
        self.keypad.key_functions = {}
        for num in ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]:
            self.keypad.key_functions[num] = lambda n=num: self.pin_press(n)
        self.keypad.key_functions["C"] = self.pin_backspace
        self.keypad.key_functions["*"] = self.pin_backspace
        self.keypad.key_functions["D"] = self.pin_cancel
        self.keypad.key_functions["#"] = self.pin_submit
        self.keypad.key_functions["A"] = self.pin_submit
        
        while not self.pin_submitted and not self.pin_cancelled and self.is_running:
            self.keypad.process_keypress(True)
            time.sleep(0.05)
            
        if self.pin_cancelled or not self.is_running:
            return None
        return self.entered_pin

    # --- Onboarding & Verification Logic ---

    def check_onboarding(self, pin):
        # 1. First-time setup from plain text json file
        if self.path_exists(self.setup_file):
            self.mv.show_screen("Encrypting plain\nsecrets file...", "Onboarding", 5, 25)
            try:
                with open(self.setup_file, "r") as f:
                    setup_data = f.read()
                
                # Verify it is valid json
                json.loads(setup_data)
                
                # Encrypt and save
                encrypted_bytes = pico_encrypt.encrypt(setup_data, pin)
                with open(self.encrypted_file, "wb") as f:
                    f.write(encrypted_bytes)
                
                # Securely delete setup file
                os.remove(self.setup_file)
                self.mv.show_screen("Success! Plain\nsetup file deleted.", "Onboarding", 5, 25)
                time.sleep(2.0)
            except Exception as e:
                self.mv.show_screen(f"Setup parse error:\n{type(e).__name__}", "Error", 5, 25, r_menu="OK")
                time.sleep(2.5)
                return False

        # 2. Attempt decryption and load accounts
        if not self.path_exists(self.encrypted_file):
            self.mv.show_screen("No secrets found!\nPlease create\n/sd/totp_setup.json", "Error", 5, 25, r_menu="Exit")
            while self.is_running:
                self.keypad.process_keypress(True)
                time.sleep(0.1)
            return False

        try:
            with open(self.encrypted_file, "rb") as f:
                enc_data = f.read()
            decrypted_str = pico_encrypt.decrypt(enc_data, pin)
            self.accounts = json.loads(decrypted_str)
            if not isinstance(self.accounts, list):
                raise ValueError("JSON must be list")
            return True
        except Exception:
            self.mv.show_screen("Incorrect PIN!", "Error", 5, 25)
            time.sleep(1.5)
            return False

    # --- Menu Views ---

    def draw_menu(self):
        names = [acc.get("name", "Unknown") for acc in self.accounts]
        self.mv.show_menu(names, self.menu_count, "TOTP Accounts", l_menu="Select", r_menu="Back")

    def scroll_up(self):
        self.menu_count = (self.menu_count - 1) % len(self.accounts)
        self.draw_menu()
        time.sleep(0.2)

    def scroll_down(self):
        self.menu_count = (self.menu_count + 1) % len(self.accounts)
        self.draw_menu()
        time.sleep(0.2)

    def select_account(self):
        if not self.accounts:
            return
        self.show_totp_code(self.accounts[self.menu_count])

    def stop(self):
        self.is_running = False

    # --- OTP Display Screen Loop ---

    def show_totp_code(self, account):
        name = account.get("name", "TOTP Code")
        secret = account.get("secret", "")
        
        self.viewing_code = True
        self.mv.show_screen("Loading code...", name, 5, 25, r_menu="Back")
        
        # Override key mappings for view
        self.keypad.key_functions = self.keypad.default_key_mappings()
        self.keypad.key_functions["D"] = self.exit_code_view
        
        last_otp = ""
        
        while self.viewing_code and self.is_running:
            # 1. Calculate time remaining
            now = rtc.RTC().datetime if hasattr(rtc, "RTC") else time.localtime()
            epoch = time.mktime(now)
            remaining = 30 - (epoch % 30)
            
            # 2. Get code
            otp = get_totp(secret, epoch)
            
            # 3. Create visual bar
            filled = int((remaining / 30) * 12)
            bar = f"[{'=' * filled}{' ' * (12 - filled)}] {remaining:2d}s"
            
            # Format OTP with a space in the middle for easier reading
            formatted_otp = f"{otp[:3]} {otp[3:]}"
            
            # Only update screen on changes to avoid flicker
            display_text = f"Code: {formatted_otp}\n\n{bar}"
            self.mv.update_content(display_text)
            
            # Check for keys (like D to return)
            self.keypad.process_keypress(True)
            time.sleep(0.2)
            
        # Re-map keypad back to menu
        self.setup_menu_keys()
        self.draw_menu()

    def exit_code_view(self):
        self.viewing_code = False
        time.sleep(0.15)

    def setup_menu_keys(self):
        self.keypad.key_functions = self.keypad.default_key_mappings()
        self.keypad.key_functions["A"] = self.select_account
        self.keypad.key_functions["B"] = self.scroll_up
        self.keypad.key_functions["C"] = self.scroll_down
        self.keypad.key_functions["D"] = self.stop

    # --- App Start ---

    def start(self):
        self.is_running = True
        self.menu_count = 0
        
        # Verify SD card is mounted
        try:
            storage.getmount("/sd")
        except Exception:
            self.mv.show_screen("SD Card not\nmounted!", "TOTP Auth", 5, 25, r_menu="OK")
            time.sleep(2.0)
            return

        # 1. Ask for PIN and authenticate
        authenticated = False
        while not authenticated and self.is_running:
            pin = self.get_pin_input()
            if pin is None:
                # Cancelled PIN input
                return
            authenticated = self.check_onboarding(pin)

        if not self.is_running:
            return

        # 2. Sync time choice screen
        self.mv.show_screen("Sync time over\nWiFi (NTP)?", "Time Sync", 5, 25, l_menu="Sync", r_menu="Skip")
        self.keypad.key_functions = self.keypad.default_key_mappings()
        
        choice = None
        def choose_sync():
            nonlocal choice
            choice = "sync"
        def choose_skip():
            nonlocal choice
            choice = "skip"
            
        self.keypad.key_functions["A"] = choose_sync
        self.keypad.key_functions["D"] = choose_skip
        
        while choice is None and self.is_running:
            self.keypad.process_keypress(True)
            time.sleep(0.05)
            
        if not self.is_running:
            return
        elif choice == "sync":
            self.sync_time()
            
        # 3. Proceed to menu
        self.setup_menu_keys()
        self.draw_menu()
        
        while self.is_running:
            self.keypad.process_keypress(True)
            time.sleep(0.1)
            
        # Restore default keypad mappings and return to main screen
        self.keypad.key_functions = self.keypad.default_key_mappings()
        self.oled.root_group = self.splash
        gc.collect()
