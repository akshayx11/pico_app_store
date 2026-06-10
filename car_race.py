import random
import time
import displayio
import terminalio
import board
from adafruit_display_text import label

# Optional PWM Buzzer setup
import pwmio
buzzer = None
try:
    buzzer = pwmio.PWMOut(board.GP20, frequency=1000, duty_cycle=0)
except Exception:
    pass

def beep(freq, duration):
    if buzzer:
        try:
            buzzer.frequency = freq
            buzzer.duty_cycle = 16384  # 25% duty cycle
            time.sleep(duration)
            buzzer.duty_cycle = 0
        except Exception:
            pass

class CarRace:
    def __init__(self, sc, mv, keypad):
        self.sc = sc
        self.mv = mv
        self.keypad = keypad
        self.oled = self.sc.get_oled()
        self.splash = self.sc.get_screen()
        
        # Game State
        self.is_active = True
        self.score = 0
        self.lives = 3
        self.speed = 2.0
        self.game_over = False
        
        # Screen size and layout
        self.screen_width = 128
        self.screen_height = self.oled.height
        
        # Boundaries (Yellow top offset if 64px display)
        if self.screen_height == 64:
            self.min_y = 20
            self.max_y = 54
        else:
            self.min_y = 8
            self.max_y = self.screen_height - 10
            
        # Lane X coordinates (Left, Center, Right)
        self.lanes = [28, 60, 92]
        self.current_lane = 1 # Start in Center lane
        
        # Player coordinates
        self.player_x = self.lanes[self.current_lane]
        self.player_y = self.max_y - 4
        
        # Obstacles (Max 2 obstacle cars on screen to avoid congestion)
        self.max_obstacles = 2
        self.obstacles = []  # List of [x, y, label_obj, active]
        
        # Road lane dividers Y coordinates for animation
        self.divider_y = 0

    def start(self):
        # Override key bindings for Car Race arcade controls
        self.keypad.key_functions = self.keypad.default_key_mappings()
        self.keypad.key_functions["A"] = self.restart_game
        self.keypad.key_functions["B"] = self.move_left
        self.keypad.key_functions["C"] = self.move_right
        self.keypad.key_functions["D"] = self.exit_game

        # Route display to dedicated game group
        while len(self.splash) > 0:
            self.splash.pop()
            
        self.game_group = displayio.Group()
        self.oled.root_group = self.game_group

        # Static Road Borders
        left_border = label.Label(terminalio.FONT, text="|\n|\n|\n|\n|", color=0xFFFFFF, x=10, y=self.min_y + 12)
        right_border = label.Label(terminalio.FONT, text="|\n|\n|\n|\n|", color=0xFFFFFF, x=114, y=self.min_y + 12)
        self.game_group.append(left_border)
        self.game_group.append(right_border)

        # Dynamic Lane Dividers (dotted lines moving down)
        self.dividers = []
        for x in [45, 79]:
            for offset in [0, 20, 40]:
                div_lbl = label.Label(terminalio.FONT, text=".", color=0xFFFFFF, x=x, y=self.min_y + offset)
                self.game_group.append(div_lbl)
                self.dividers.append([x, offset, div_lbl])

        # HUD (Score & Lives)
        self.score_label = label.Label(terminalio.FONT, text="S:0", color=0xFFFFFF, x=2, y=6)
        self.lives_label = label.Label(terminalio.FONT, text="HP:3", color=0xFFFFFF, x=95, y=6)
        self.game_group.append(self.score_label)
        self.game_group.append(self.lives_label)

        # Player Car (represented as retro wheels and chassis)
        # o-o (wheels)
        #  |  (body)
        # o-o (wheels)
        self.player_label = label.Label(
            terminalio.FONT, 
            text="o-o\n | \no-o", 
            color=0xFFFFFF, 
            x=self.player_x, 
            y=self.player_y
        )
        self.game_group.append(self.player_label)

        # Pre-allocated Obstacles (spawned off-screen initially)
        for _ in range(self.max_obstacles):
            obs_lbl = label.Label(
                terminalio.FONT, 
                text="x-x\n | \nx-x", 
                color=0xFFFFFF, 
                x=-30, 
                y=-20
            )
            self.game_group.append(obs_lbl)
            self.obstacles.append([-30, -20, obs_lbl, False])

        print("Car Race game started.")
        last_spawn_time = time.monotonic()
        
        # Game Loop
        while self.is_active:
            self.keypad.process_keypress(True)

            if not self.game_over:
                # 1. Spawn Obstacles
                current_time = time.monotonic()
                if current_time - last_spawn_time > random.uniform(2.0, 3.5):
                    self.spawn_obstacle()
                    last_spawn_time = current_time

                # 2. Animate Road Lane Dividers
                self.animate_dividers()

                # 3. Update and Collide Obstacles
                self.update_obstacles()

                # 4. Check Game Over
                if self.lives <= 0:
                    self.trigger_game_over()

            time.sleep(0.05)

    def spawn_obstacle(self):
        # Find an inactive obstacle slot
        for obs in self.obstacles:
            if not obs[3]:  # inactive
                lane = random.choice([0, 1, 2])
                # Avoid spawning exactly side-by-side with another active obstacle
                lane_occupied = False
                for other in self.obstacles:
                    if other[3] and other[1] < self.min_y + 10 and other[0] == self.lanes[lane]:
                        lane_occupied = True
                
                if not lane_occupied:
                    obs[0] = self.lanes[lane]
                    obs[1] = self.min_y - 15
                    obs[2].x = obs[0]
                    obs[2].y = int(obs[1])
                    obs[3] = True  # active
                    break

    def animate_dividers(self):
        self.divider_y = (self.divider_y + int(self.speed)) % 20
        for div in self.dividers:
            # Shift the dot down dynamically
            x, offset, lbl = div
            new_y = self.min_y + ((offset + self.divider_y) % 40)
            lbl.y = int(new_y)

    def update_obstacles(self):
        for obs in self.obstacles:
            if obs[3]:  # active
                obs[1] += self.speed
                obs[2].y = int(obs[1])

                # Collision check
                # Player car center is at self.player_x + 8, self.player_y + 8
                # Obstacle car center is at obs[0] + 8, obs[1] + 8
                if abs(self.player_x - obs[0]) < 12:  # Same lane
                    if abs(self.player_y - obs[1]) < 15:  # Overlapping Y
                        # Hit!
                        beep(150, 0.3)
                        self.lives -= 1
                        self.lives_label.text = f"HP:{self.lives}"
                        self.flash_screen()
                        # Deactivate hit obstacle
                        self.reset_obstacle(obs)
                        continue

                # Off-screen check
                if obs[1] > self.max_y + 15:
                    self.reset_obstacle(obs)
                    self.score += 1
                    self.score_label.text = f"S:{self.score}"
                    beep(800, 0.02)
                    # Slightly increase speed as score goes up
                    if self.score % 5 == 0 and self.speed < 4.5:
                        self.speed += 0.3

    def reset_obstacle(self, obs):
        obs[0] = -30
        obs[1] = -20
        obs[2].x = -30
        obs[2].y = -20
        obs[3] = False  # inactive

    def flash_screen(self):
        # Simple negative color flash
        self.oled.invert(True)
        time.sleep(0.1)
        self.oled.invert(False)

    def move_left(self):
        if self.current_lane > 0 and not self.game_over:
            self.current_lane -= 1
            self.player_x = self.lanes[self.current_lane]
            self.player_label.x = self.player_x
            beep(500, 0.02)
        time.sleep(0.1)

    def move_right(self):
        if self.current_lane < 2 and not self.game_over:
            self.current_lane += 1
            self.player_x = self.lanes[self.current_lane]
            self.player_label.x = self.player_x
            beep(500, 0.02)
        time.sleep(0.1)

    def trigger_game_over(self):
        self.game_over = True
        beep(100, 0.5)
        # Show Game Over text overlaid
        self.game_over_label = label.Label(terminalio.FONT, text="GAME OVER\nPress [A] to\nRestart", color=0xFFFFFF, x=30, y=self.min_y + 10)
        self.game_group.append(self.game_over_label)

    def restart_game(self):
        if self.game_over:
            self.score = 0
            self.lives = 3
            self.speed = 2.0
            self.current_lane = 1
            self.player_x = self.lanes[self.current_lane]
            self.player_label.x = self.player_x
            self.score_label.text = "S:0"
            self.lives_label.text = "HP:3"
            
            # Remove game over text
            try:
                self.game_group.remove(self.game_over_label)
            except Exception:
                pass
                
            for obs in self.obstacles:
                self.reset_obstacle(obs)
                
            self.game_over = False
            beep(600, 0.1)

    def exit_game(self):
        self.is_active = False
        # Release displays and restore main screen
        displayio.release_displays()
        self.oled.root_group = self.splash
        self.mv.show_screen("Car Race stopped", "Games", 5, 25, r_menu="")
        time.sleep(0.2)
