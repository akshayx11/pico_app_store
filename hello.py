import time

class HelloWorld:
    def __init__(self, sc, mv, keypad):
        self.sc = sc
        self.mv = mv
        self.keypad = keypad
        self.is_running = True

    def start(self):
        self.is_running = True
        self.mv.show_screen("Hello World!\nPress any key...\n[D] to Exit", "Greeting", 5, 25, r_menu="Exit")
        
        # Configure keypad handlers
        self.keypad.key_functions = self.keypad.default_key_mappings()
        self.keypad.key_functions["D"] = self.stop
        
        # Bind keys to show pressed indicator
        for key in ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "A", "B", "C"]:
            self.keypad.key_functions[key] = lambda k=key: self.show_key(k)
            
        while self.is_running:
            self.keypad.process_keypress(True)
            time.sleep(0.1)
            
    def show_key(self, key):
        self.mv.show_screen(f"Hello World!\nYou pressed: {key}\n[D] to Exit", "Greeting", 5, 25, r_menu="Exit")
        time.sleep(0.1)

    def stop(self):
        self.is_running = False
