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

# Helper to build a scaled blocky bitmap from a coarse string pattern
def make_blocky_sprite(pattern, block_size, palette):
    unit_h = len(pattern)
    unit_w = len(pattern[0])
    bmp = displayio.Bitmap(unit_w * block_size, unit_h * block_size, 2)
    for uy in range(unit_h):
        for ux in range(unit_w):
            if pattern[uy][ux] == 'x':
                # Fill a block_size x block_size area of pixels
                for dy in range(block_size):
                    for dx in range(block_size):
                        bmp[ux * block_size + dx, uy * block_size + dy] = 1
    return displayio.TileGrid(bmp, pixel_shader=palette)

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
        self.hi_score = 9999
        self.lives = 3
        self.speed = 2.0
        self.game_over = False
        
        # Grid settings (each brick is 3x3 screen pixels)
        self.block_size = 3
        
        # Screen division (Road on left, Console Sidebar on right)
        self.road_max_x = 90
        self.sidebar_x = 94
        
        self.min_y = 16
        self.max_y = 60
        
        # Horizontal Lanes Y coordinates (center coordinates of the 15px high cars)
        # Top, Middle, Bottom lanes
        self.lanes = [18, 32, 46]
        self.current_lane = 1 # Start in Middle lane
        
        # Player coordinates (fixed X near the left edge)
        self.player_x = 10
        self.player_y = self.lanes[self.current_lane]
        
        # Obstacles (Max 2 obstacle cars on screen)
        # Store as: [x, lane_index, sprite_obj, active]
        self.max_obstacles = 2
        self.obstacles = []
        
        # Scrolling borders
        # List of [x, sprite_obj] for top and bottom blocks
        self.border_blocks = []
        self.divider_offset = 0

    def start(self):
        # Override key bindings for Car Race arcade controls
        self.keypad.key_functions = self.keypad.default_key_mappings()
        self.keypad.key_functions["A"] = self.restart_game
        self.keypad.key_functions["B"] = self.move_up
        self.keypad.key_functions["C"] = self.move_down
        self.keypad.key_functions["D"] = self.exit_game

        # Route display to dedicated game group
        while len(self.splash) > 0:
            self.splash.pop()
            
        self.game_group = displayio.Group()
        self.oled.root_group = self.game_group

        # Set up a shared 2-color palette (0: transparent, 1: white)
        self.palette = displayio.Palette(2)
        self.palette[0] = 0x000000
        self.palette[1] = 0xFFFFFF
        self.palette.make_transparent(0)

        # 1. Draw Console Screen Borders & Sidebar Divider
        # Vertical divider line at X = 90
        divider_bmp = displayio.Bitmap(1, 64, 2)
        divider_bmp.fill(1)
        self.divider_line = displayio.TileGrid(divider_bmp, pixel_shader=self.palette)
        self.divider_line.x = self.road_max_x
        self.divider_line.y = 0
        self.game_group.append(self.divider_line)

        # Horizontal line separating the yellow top bar
        hud_line_bmp = displayio.Bitmap(128, 1, 2)
        hud_line_bmp.fill(1)
        self.hud_line = displayio.TileGrid(hud_line_bmp, pixel_shader=self.palette)
        self.hud_line.x = 0
        self.hud_line.y = 13
        self.game_group.append(self.hud_line)

        # 2. Scrolling Road Borders (LCD Blocks)
        # Create solid 3x3 blocks for borders
        border_bmp = displayio.Bitmap(3, 3, 2)
        border_bmp.fill(1)
        
        # Spaced out top and bottom block borders
        # 6 blocks spaced 18 pixels apart
        for i in range(6):
            start_x = i * 18
            # Top block
            top_blk = displayio.TileGrid(border_bmp, pixel_shader=self.palette)
            top_blk.x = start_x
            top_blk.y = self.min_y - 1
            self.game_group.append(top_blk)
            self.border_blocks.append([start_x, self.min_y - 1, top_blk])
            
            # Bottom block
            bot_blk = displayio.TileGrid(border_bmp, pixel_shader=self.palette)
            bot_blk.x = start_x
            bot_blk.y = self.max_y + 1
            self.game_group.append(bot_blk)
            self.border_blocks.append([start_x, self.max_y + 1, bot_blk])

        # 3. Dynamic Lane Divider Dots (Scrolling middle lane markings)
        self.dividers = []
        for y in [30, 42]:
            div_lbl = label.Label(terminalio.FONT, text="- - - - -", color=0xFFFFFF, x=0, y=y)
            self.game_group.append(div_lbl)
            self.dividers.append([y, div_lbl])

        # 4. Brick Game HUD & Console Sidebar
        # Top Header (Brick Game Title)
        self.title_label = label.Label(terminalio.FONT, text="■ BRICK RACER ■", color=0xFFFFFF, x=4, y=6)
        self.game_group.append(self.title_label)

        # Console Sidebar Labels (Retro Brick Game style)
        self.hi_label = label.Label(terminalio.FONT, text="HI-SC", color=0xFFFFFF, x=self.sidebar_x, y=20)
        self.hi_val_label = label.Label(terminalio.FONT, text="9999", color=0xFFFFFF, x=self.sidebar_x, y=28)
        self.score_label = label.Label(terminalio.FONT, text="SCORE", color=0xFFFFFF, x=self.sidebar_x, y=40)
        self.score_val_label = label.Label(terminalio.FONT, text="0000", color=0xFFFFFF, x=self.sidebar_x, y=48)
        self.speed_label = label.Label(terminalio.FONT, text="HP:3", color=0xFFFFFF, x=self.sidebar_x, y=58)
        
        self.game_group.append(self.hi_label)
        self.game_group.append(self.hi_val_label)
        self.game_group.append(self.score_label)
        self.game_group.append(self.score_val_label)
        self.game_group.append(self.speed_label)

        # 5. Coarse Pixel-Art Cars (Built from 3x3 blocks to look like LCD bricks)
        # Player Car (Facing Right)
        player_pattern = [
            "x.x.",
            "xxx.",
            ".x.x",
            "xxx.",
            "x.x."
        ]
        self.player_sprite = make_blocky_sprite(player_pattern, self.block_size, self.palette)
        self.player_sprite.x = self.player_x
        self.player_sprite.y = self.player_y
        self.game_group.append(self.player_sprite)

        # Obstacle Cars (Facing Left)
        obstacle_pattern = [
            ".x.x",
            ".xxx",
            "x.x.",
            ".xxx",
            ".x.x"
        ]
        for _ in range(self.max_obstacles):
            obs_sprite = make_blocky_sprite(obstacle_pattern, self.block_size, self.palette)
            obs_sprite.x = 100
            obs_sprite.y = 0
            self.game_group.append(obs_sprite)
            self.obstacles.append([100, 0, obs_sprite, False])

        print("Brick Game Car Race started.")
        last_spawn_time = time.monotonic()
        
        # Load local highscore if available
        self.load_highscore()
        self.hi_val_label.text = f"{self.hi_score:04d}"
        
        # Game Loop
        while self.is_active:
            self.keypad.process_keypress(True)

            if not self.game_over:
                # Spawn Obstacles
                current_time = time.monotonic()
                if current_time - last_spawn_time > random.uniform(1.2, 2.5):
                    self.spawn_obstacle()
                    last_spawn_time = current_time

                # Animate Dividers & Borders
                self.animate_borders()

                # Update and Collide Obstacles
                self.update_obstacles()

                # Check Game Over
                if self.lives <= 0:
                    self.trigger_game_over()

            time.sleep(0.05)

    def load_highscore(self):
        try:
            with open("/sd/features/installed_apps.json", "r") as f:
                pass # Just check if SD card is mounted
            try:
                with open("/sd/race_highscore.txt", "r") as f:
                    self.hi_score = int(f.read().strip())
            except Exception:
                self.hi_score = 9999
        except Exception:
            self.hi_score = 9999

    def save_highscore(self):
        try:
            with open("/sd/race_highscore.txt", "w") as f:
                f.write(str(self.hi_score))
        except Exception:
            pass

    def spawn_obstacle(self):
        for obs in self.obstacles:
            if not obs[3]:  # inactive
                lane = random.choice([0, 1, 2])
                lane_occupied = False
                for other in self.obstacles:
                    if other[3] and other[0] > 70 and other[1] == lane:
                        lane_occupied = True
                
                if not lane_occupied:
                    obs[0] = 90
                    obs[1] = lane
                    obs[2].x = 90
                    obs[2].y = self.lanes[lane]
                    obs[3] = True  # active
                    break

    def animate_borders(self):
        self.divider_offset = (self.divider_offset - int(self.speed)) % 18
        
        # Scroll the border blocks left
        for blk in self.border_blocks:
            x_offset, y, sprite = blk
            # Calculate new X wrapped inside the road area (0 to 90)
            new_x = (x_offset + self.divider_offset) % 90
            sprite.x = int(new_x)
            
        # Scroll the middle lane divider dotted lines
        for div in self.dividers:
            y, lbl = div
            lbl.x = (self.divider_offset % 24) - 24

    def update_obstacles(self):
        for obs in self.obstacles:
            if obs[3]:  # active
                obs[0] -= self.speed
                obs[2].x = int(obs[0])

                # Collision check
                # Player is at player_x=10, width is 12 (4 units * 3px).
                # Obstacle is at obs[0], width is 12.
                if abs(self.player_x - obs[0]) < 11:  # Horizontally overlapping
                    if self.current_lane == obs[1]:   # Same lane
                        beep(150, 0.3)
                        self.lives -= 1
                        self.speed_label.text = f"HP:{self.lives}"
                        self.reset_obstacle(obs)
                        continue

                # Off-screen check (Passed player successfully)
                if obs[0] < -12:
                    self.reset_obstacle(obs)
                    self.score += 1
                    self.score_val_label.text = f"{self.score:04d}"
                    beep(800, 0.02)
                    
                    # Update High Score
                    if self.score > self.hi_score:
                        self.hi_score = self.score
                        self.hi_val_label.text = f"{self.hi_score:04d}"
                        self.save_highscore()
                        
                    # Slightly increase speed
                    if self.score % 5 == 0 and self.speed < 5.0:
                        self.speed += 0.4

    def reset_obstacle(self, obs):
        obs[0] = 100
        obs[1] = 0
        obs[2].x = 100
        obs[2].y = 0
        obs[3] = False  # inactive

    def move_up(self):
        if self.current_lane > 0 and not self.game_over:
            self.current_lane -= 1
            self.player_y = self.lanes[self.current_lane]
            self.player_sprite.y = self.player_y
            beep(500, 0.02)
        time.sleep(0.1)

    def move_down(self):
        if self.current_lane < 2 and not self.game_over:
            self.current_lane += 1
            self.player_y = self.lanes[self.current_lane]
            self.player_sprite.y = self.player_y
            beep(500, 0.02)
        time.sleep(0.1)

    def trigger_game_over(self):
        self.game_over = True
        beep(100, 0.5)
        # Show Game Over overlay (fits in the road area)
        self.game_over_label = label.Label(terminalio.FONT, text="GAME OVER\nPress [A]\nto Restart", color=0xFFFFFF, x=15, y=self.min_y + 12)
        self.game_group.append(self.game_over_label)

    def restart_game(self):
        if self.game_over:
            self.score = 0
            self.lives = 3
            self.speed = 2.0
            self.current_lane = 1
            self.player_y = self.lanes[self.current_lane]
            self.player_sprite.y = self.player_y
            self.score_val_label.text = "0000"
            self.speed_label.text = "HP:3"
            
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
        displayio.release_displays()
        self.oled.root_group = self.splash
        self.mv.show_screen("Car Race stopped", "Games", 5, 25, r_menu="")
        time.sleep(0.2)
