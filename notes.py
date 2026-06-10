import time
import os
import json
import displayio
import terminalio
from adafruit_display_text import label

class NotesApp:
    def __init__(self, sc, mv, keypad):
        self.sc = sc
        self.mv = mv
        self.keypad = keypad
        self.splash = self.sc.get_screen()
        self.oled = self.sc.get_oled()
        
        self.is_running = True
        self.notes = []
        self.menu_count = 0
        self.state = "LIST"  # States: "LIST", "VIEW", "ADD"
        
        self.notes_file = "/sd/notes.json"
        self.load_notes()

    def path_exists(self, filepath):
        try:
            os.stat(filepath)
            return True
        except OSError:
            return False

    def load_notes(self):
        try:
            if self.path_exists(self.notes_file):
                with open(self.notes_file, "r") as f:
                    self.notes = json.load(f)
            else:
                self.notes = []
        except Exception as e:
            print("Failed to load notes:", e)
            self.notes = []

    def save_notes_to_sd(self):
        try:
            with open(self.notes_file, "w") as f:
                json.dump(self.notes, f)
        except Exception as e:
            print("Failed to save notes:", e)

    def start(self):
        self.is_running = True
        self.state = "LIST"
        self.menu_count = 0
        
        # Configure menu controls initially
        self.setup_list_controls()
        self.draw_screen()
        
        while self.is_running:
            if self.state == "ADD":
                # Handle active text typing loop
                self.keypad.process_keypress(False)  # Alphabet mode
                current_typing = self.keypad.typed_text + (
                    self.keypad.current_key_mapping[self.keypad.last_key][self.keypad.char_index] 
                    if self.keypad.last_key else ""
                )
                if current_typing != self.typed_note:
                    self.typed_note = current_typing
                    self.mv.update_content(self.typed_note)
            else:
                # Normal menu navigation loop
                self.keypad.process_keypress(True)
            time.sleep(0.1)

    def draw_screen(self):
        if self.state == "LIST":
            # Add an extra item at the end for adding a new note
            names = []
            for note in self.notes:
                preview = note[:12] + ".." if len(note) > 12 else note
                preview = preview.replace("\n", " ")
                names.append(preview)
            names.append("[New Note]")
            
            self.mv.show_menu(names, self.menu_count, "Notes", l_menu="Select", r_menu="Back")
        elif self.state == "VIEW":
            note_text = self.notes[self.menu_count]
            # Show the selected note's full text
            self.mv.show_screen(note_text, f"Note {self.menu_count+1}", 5, 25, l_menu="Delete", r_menu="Back")
        elif self.state == "ADD":
            # Show the note editor
            self.mv.show_screen(self.typed_note, "New Note", 5, 25, l_menu="Save", r_menu="Back")

    def setup_list_controls(self):
        self.keypad.reset()
        self.keypad.key_functions = self.keypad.default_key_mappings()
        self.keypad.key_functions["A"] = self.list_select_action
        self.keypad.key_functions["B"] = self.list_scroll_up
        self.keypad.key_functions["C"] = self.list_scroll_down
        self.keypad.key_functions["D"] = self.list_back_action

    def list_scroll_up(self):
        self.menu_count = (self.menu_count - 1) % (len(self.notes) + 1)
        self.draw_screen()
        time.sleep(0.2)

    def list_scroll_down(self):
        self.menu_count = (self.menu_count + 1) % (len(self.notes) + 1)
        self.draw_screen()
        time.sleep(0.2)

    def list_select_action(self):
        if self.menu_count == len(self.notes):
            # Selected the "[New Note]" option
            self.trigger_add_note()
        else:
            # View current note
            self.state = "VIEW"
            self.setup_view_controls()
            self.draw_screen()
        time.sleep(0.2)

    def list_back_action(self):
        self.is_running = False

    def trigger_add_note(self):
        self.state = "ADD"
        self.typed_note = ""
        self.keypad.reset()
        
        self.keypad.key_functions = self.keypad.default_key_mappings()
        self.keypad.key_functions["A"] = self.save_note
        self.keypad.key_functions["D"] = self.cancel_add_note
        self.draw_screen()
        time.sleep(0.2)

    def save_note(self):
        if self.typed_note.strip():
            self.notes.append(self.typed_note)
            self.save_notes_to_sd()
        self.state = "LIST"
        self.menu_count = len(self.notes) - 1
        self.setup_list_controls()
        self.draw_screen()
        time.sleep(0.2)

    def cancel_add_note(self):
        self.state = "LIST"
        self.setup_list_controls()
        self.draw_screen()
        time.sleep(0.2)

    def setup_view_controls(self):
        self.keypad.reset()
        self.keypad.key_functions = self.keypad.default_key_mappings()
        self.keypad.key_functions["A"] = self.delete_note
        self.keypad.key_functions["D"] = self.exit_view

    def delete_note(self):
        if 0 <= self.menu_count < len(self.notes):
            self.notes.pop(self.menu_count)
            self.save_notes_to_sd()
        self.state = "LIST"
        self.menu_count = max(0, self.menu_count - 1)
        self.setup_list_controls()
        self.draw_screen()
        time.sleep(0.2)

    def exit_view(self):
        self.state = "LIST"
        self.setup_list_controls()
        self.draw_screen()
        time.sleep(0.2)
