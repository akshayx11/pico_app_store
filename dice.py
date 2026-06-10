import time
import random

class DiceRoller:
    def __init__(self, sc, mv, keypad):
        self.sc = sc
        self.mv = mv
        self.keypad = keypad
        self.is_running = True

    def start(self):
        self.is_running = True
        self.mv.show_screen("Press [A] to Roll!\n\n[D] to Exit", "Dice Roller", 5, 25, l_menu="Roll", r_menu="Exit")
        
        # Configure keypad handlers
        self.keypad.key_functions = self.keypad.default_key_mappings()
        self.keypad.key_functions["A"] = self.roll_dice
        self.keypad.key_functions["D"] = self.stop
        
        while self.is_running:
            self.keypad.process_keypress(True)
            time.sleep(0.1)
            
    def roll_dice(self):
        # Rolling animation
        for i in range(8):
            roll_val = random.randint(1, 6)
            self.mv.show_screen(f"Rolling...\n\n     [ {roll_val} ]", "Dice Roller", 5, 25)
            time.sleep(0.1)
            
        # Final result
        final_val = random.randint(1, 6)
        self.mv.show_screen(f"Rolled a {final_val}!\nPress [A] to Roll\n[D] to Exit", "Dice Roller", 5, 25, l_menu="Roll", r_menu="Exit")
        time.sleep(0.2)

    def stop(self):
        self.is_running = False
