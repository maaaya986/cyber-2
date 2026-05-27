import pygame # Library for making games and graphics
import socket # Library for network communication
import pickle # Library for converting Python objects to bytes and back
import threading # Library for running multiple tasks at once
import time # Library for time-related functions (like pausing)
import hashlib # Library for creating secure "fingerprints" of data (like passwords)
import ssl # Library for secure network communication (TLS/SSL)
import struct # Library for packing/unpacking binary data (like message lengths)
import os # Library for interacting with the operating system (like file paths)
from logger_util import Logger # Our custom logging class
from pyfonts import load_font # Library to load fonts from Google Fonts

# --- Game Configuration ---
WIDTH = 30 # Number of tiles horizontally in the maze
HEIGHT = 30 # Number of tiles vertically in the maze
TILE_SIZE = 20 # Size of each tile in pixels (e.g., 20x20 pixels)
PORT = 5555 # The network port the server is listening on
SERVER = "127.0.0.1" # The IP address of the server (localhost for testing)
CONTROLS_HEIGHT = 150 # Extra space at the bottom of the screen for UI elements

# Colors used in the game
COLORS = {
    0: (7, 168, 124),     # Wall color (Teal-Green)
    1: (200, 200, 200),  # Path color (Light Gray)
    2: (0, 255, 0),      # Food color (Fallback if icon not loaded)
    3: (255, 0, 0),      # Poison color (Fallback if icon not loaded)
    9: (0, 0, 255),      # Exit color (Blue)
}

# --- UI Element Base Class ---
class UIElement:
    """
    A base class for any interactive element on the screen (buttons, input fields).
    It defines common properties like position and color.
    """
    def __init__(self, rect, color):
        self.rect = pygame.Rect(rect) # The rectangular area of the element
        self.color = color # The main color of the element

    def draw(self, screen, font):
        """Draws the element on the screen. To be implemented by child classes."""
        pass

    def handle_event(self, event):
        """Handles user input (like clicks or typing). To be implemented by child classes."""
        return False

# --- Button Class ---
class Button(UIElement):
    """A clickable button that performs an action when pressed."""
    def __init__(self, rect, text, action_val):
        super().__init__(rect, (100, 100, 100)) # Call UIElement's constructor
        self.text = text # Text displayed on the button
        self.action_val = action_val # Value returned when button is clicked (e.g., "UP", "LOGIN")

    def draw(self, screen, font):
        """Draws the button's rectangle and its text."""
        pygame.draw.rect(screen, self.color, self.rect, border_radius=8) # Draw the button's background
        t = font.render(self.text, True, (255, 255, 255)) # Render the text
        screen.blit(t, t.get_rect(center=self.rect.center)) # Draw text in the center of the button

    def handle_event(self, event):
        """Checks if the button was clicked."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1: # If left mouse button was pressed
            if self.rect.collidepoint(event.pos): # And the mouse was over this button
                return self.action_val # Return the action value
        return False

# --- Input Field Class ---
class InputField(UIElement):
    """A box where the user can type text, like for username or password."""
    def __init__(self, rect, label, is_password=False):
        super().__init__(rect, (255, 255, 255))
        self.label = label # Text label next to the input box (e.g., "USER:")
        self.text = "" # Current text typed by the user
        self.active = False # True if this field is currently being typed into
        self.is_password = is_password # If true, display '*' instead of actual text

    def draw(self, screen, font):
        """Draws the label, the input box, and the user's text (or asterisks for password)."""
        # Highlight color if active, otherwise a dimmer color
        color = (255, 255, 0) if self.active else (150, 150, 150)
        # Display '*' for passwords, otherwise display actual text
        disp_text = "*" * len(self.text) if self.is_password else self.text
        
        # Draw the label (e.g., "USER:")
        label_img = font.render(f"{self.label}:", True, (200, 200, 200))
        screen.blit(label_img, (self.rect.x - 130, self.rect.y + 5)) # Position label to the left
        
        # Draw the input box background and border
        pygame.draw.rect(screen, (50, 50, 50), self.rect)
        pygame.draw.rect(screen, color, self.rect, 2) # Border color changes based on active state
        
        # Draw the actual text inside the input box
        text_img = font.render(disp_text, True, (255, 255, 255))
        screen.blit(text_img, (self.rect.x + 5, self.rect.y + 5))

    def handle_event(self, event):
        """Handles mouse clicks (to activate/deactivate) and keyboard input."""
        if event.type == pygame.MOUSEBUTTONDOWN:
            # Check if the mouse clicked on this input field
            self.active = self.rect.collidepoint(event.pos)
        if self.active and event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE: # If Backspace is pressed, remove last character
                self.text = self.text[:-1]
            else:
                # Add the typed character if it's a single character
                if len(event.unicode) == 1:
                    self.text += event.unicode
        return False

# --- Connection Manager Class ---
class ConnectionManager:
    """
    Handles all network communication with the server, including SSL setup,
    sending/receiving data, and managing the connection state.
    """
    def __init__(self, logger):
        self.logger = logger # Our logger instance
        # Setup SSL context for secure communication
        self.context = ssl.create_default_context()
        self.context.check_hostname = False # Disable hostname check for self-signed certs
        self.context.verify_mode = ssl.CERT_NONE # Disable certificate verification for self-signed certs
        self.my_id = None # Player ID assigned by the server
        self.client = None # The SSL-wrapped socket connection

    def _recv_all(self, n):
        """
        Helper function to ensure all 'n' bytes of a message are received.
        TCP can split messages, so this loops until the full message arrives.
        """
        data = b''
        while len(data) < n:
            try:
                packet = self.client.recv(n - len(data)) # Try to receive remaining bytes
                if not packet: # If no data, connection is likely closed
                    return None
                data += packet
            except:
                return None
        return data

    def get_leaderboard_data(self):
        """
        Connects to the server briefly to fetch the current leaderboard
        before the user logs in.
        """
        try:
            # Create a temporary socket just for this request
            temp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            ssl_sock = self.context.wrap_socket(temp_socket, server_hostname=SERVER)
            ssl_sock.connect((SERVER, PORT))
            
            # Send a special request for the leaderboard
            ssl_sock.sendall(pickle.dumps({"leaderboard_request": True}))
            
            # Receive the leaderboard data
            data = pickle.loads(ssl_sock.recv(4096))
            ssl_sock.close() # Close the temporary connection
            return data.get("leaderboard", [])
        except Exception as e:
            self.logger.log(f"Error fetching leaderboard: {e}")
            return []

    def attempt_login(self, username, password):
        """
        Connects to the server, sends login credentials, and processes the server's response.
        """
        try:
            # Create a new raw socket and wrap it in SSL
            raw_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client = self.context.wrap_socket(raw_socket, server_hostname=SERVER)
            self.client.connect((SERVER, PORT)) # Connect to the server
            
            # Hash the password securely before sending it
            hashed_pw = hashlib.sha256(password.encode()).hexdigest()
            
            # Send username and hashed password to the server
            self.client.sendall(pickle.dumps({"username": username, "password": hashed_pw}))
            
            # Receive the server's response (success/fail)
            resp_bytes = self.client.recv(4096)
            if not resp_bytes: return False
            resp = pickle.loads(resp_bytes)
            
            if resp.get("status") == "success":
                self.my_id = resp["id"] # Store the player ID assigned by the server
                return True
        except Exception as e:
            self.logger.log(f"Login attempt failed: {e}")
        return False

    def receive_data(self):
        """
        Receives a full message from the server, handling the length-prefix header.
        """
        try:
            # Read the 4-byte header to get the message length
            header = self._recv_all(4)
            if not header: return None
            length = struct.unpack(">I", header)[0] # Unpack the 4 bytes into an integer
            
            # Receive the full message data based on the length
            data = self._recv_all(length)
            if not data: return None
            
            return pickle.loads(data) # Convert bytes back to a Python object
        except:
            return None

# --- Game Renderer Class ---
class GameRenderer:
    """
    Handles all drawing operations on the Pygame screen.
    """
    def __init__(self, screen, font):
        self.screen = screen # The Pygame display surface
        self.font = font # The main font used for text

    def draw_leaderboard(self, leaderboard, x, y):
        """Draws the leaderboard (top 3 players) on the screen."""
        self.draw_text("LEADERBOARD", x, y, (255, 255, 0)) # Title
        for i, entry in enumerate(leaderboard):
            # Display rank, username, and score
            text = f"{i+1}.{entry['name']}:{entry['score']}"
            self.draw_text(text, x, y + 30 + (i * 30), (255, 255, 255))

    def draw_text(self, text, x, y, color=(255, 255, 255), centered=False):
        """Helper to draw text on the screen."""
        img = self.font.render(text, True, color)
        rect = img.get_rect()
        if centered: rect.center = (x, y)
        else: rect.topleft = (x, y)
        self.screen.blit(img, rect)

    def render_login(self, user_field, pass_field, login_btn, leaderboard):
        """Draws the login screen."""
        self.screen.fill((30, 30, 30))
        self.draw_text("MAZE LOGIN", WIDTH * TILE_SIZE // 2, 60, (0, 255, 255), centered=True)
        self.draw_leaderboard(leaderboard, WIDTH * TILE_SIZE - 200, 20)
        user_field.draw(self.screen, self.font)
        pass_field.draw(self.screen, self.font)
        login_btn.draw(self.screen, self.font)
        pygame.display.flip()

    def render_color_selection(self, options):
        """Draws the screen where players choose their icon color."""
        self.screen.fill((0, 0, 0))
        self.draw_text("CHOOSE YOUR COLOR", WIDTH * TILE_SIZE // 2, 100, (255, 255, 255), centered=True)
        for opt in options:
            pygame.draw.rect(self.screen, opt['color'], opt['rect'])
            pygame.draw.rect(self.screen, (255, 255, 255), opt['rect'], 2)
        pygame.display.flip()

    def render_winner(self, winner_name, leaderboard):
        """Draws the winner announcement screen."""
        self.screen.fill((0, 0, 0))
        mid_x = WIDTH * TILE_SIZE // 2
        mid_y = (HEIGHT * TILE_SIZE + CONTROLS_HEIGHT) // 2
        self.draw_text(f"THE WINNER IS", mid_x, mid_y - 80, (255, 255, 0), centered=True)
        self.draw_text(winner_name.upper(), mid_x, mid_y - 40, (255, 255, 255), centered=True)
        self.draw_leaderboard(leaderboard, mid_x - 80, mid_y + 10)
        pygame.display.flip()

    def render_game(self, current_map, scores, my_id, move_btns, player_icon, food_icon, poison_icon):
        """Draws the main game screen: maze, players, items, and UI."""
        self.screen.fill((20, 20, 20))
        if current_map:
            for y in range(HEIGHT):
                for x in range(WIDTH):
                    val = current_map[y][x]
                    rx, ry = x * TILE_SIZE, y * TILE_SIZE
                    
                    if val >= 10: # Player
                        pygame.draw.rect(self.screen, COLORS[1], (rx, ry, TILE_SIZE, TILE_SIZE))
                        if val == my_id: # YOU
                            self.screen.blit(player_icon, (rx, ry))
                        else: # OTHERS
                            pygame.draw.circle(self.screen, (255, 165, 0), (rx+TILE_SIZE//2, ry+TILE_SIZE//2), TILE_SIZE//2-2)
                    elif val == 2: # Food
                        pygame.draw.rect(self.screen, COLORS[1], (rx, ry, TILE_SIZE, TILE_SIZE))
                        self.screen.blit(food_icon, (rx, ry))
                    elif val == 3: # Poison
                        pygame.draw.rect(self.screen, COLORS[1], (rx, ry, TILE_SIZE, TILE_SIZE))
                        self.screen.blit(poison_icon, (rx, ry))
                    elif val == 9: # Exit (Blinking)
                        color = COLORS[9] if int(time.time()*2)%2==0 else COLORS[1]
                        pygame.draw.rect(self.screen, color, (rx, ry, TILE_SIZE, TILE_SIZE))
                    else: # Walls or empty path
                        pygame.draw.rect(self.screen, COLORS.get(val, (127, 127, 127)), (rx, ry, TILE_SIZE, TILE_SIZE))
            
            # Score and Buttons
            my_score = scores.get(my_id, 0)
            self.draw_text(f"SCORE: {my_score}", 10, HEIGHT * TILE_SIZE + 10, (0, 255, 255))
            for btn in move_btns: btn.draw(self.screen, self.font)
        pygame.display.flip()

# --- Main Maze Client Class ---
class MazeClient:
    def __init__(self):
        self.logger = Logger("client")
        pygame.init() # Must be called before loading fonts
        
        # Load the "Passion One" Google Font
        try:
            self.main_font = load_font("Passion One", size=24)
        except:
            self.main_font = pygame.font.SysFont("Arial", 24, bold=True)
            
        self.screen = pygame.display.set_mode((WIDTH * TILE_SIZE, (HEIGHT * TILE_SIZE) + CONTROLS_HEIGHT))
        self.conn = ConnectionManager(self.logger)
        self.renderer = GameRenderer(self.screen, self.main_font)
        
        self.running = True
        self.current_map, self.scores, self.leaderboard = None, {}, []
        self.winner_name = None
        self.player_icon, self.food_icon, self.poison_icon, self.icons = None, None, None, {}

    def load_assets(self):
        """Loads all image sprites from the assets folder."""
        # Load player sprites
        for color, file in {'blue': 'blue_player.png', 'green': 'green_player.png', 'pink': 'pink_player.png'}.items():
            try:
                img = pygame.image.load(os.path.join('assets', file)).convert_alpha()
                self.icons[color] = pygame.transform.scale(img, (TILE_SIZE, TILE_SIZE))
            except:
                fb = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
                pygame.draw.circle(fb, (255, 255, 0), (TILE_SIZE//2, TILE_SIZE//2), TILE_SIZE//2)
                self.icons[color] = fb
        # Load item sprites
        try:
            self.food_icon = pygame.transform.scale(pygame.image.load(os.path.join('assets', 'food.png')).convert_alpha(), (TILE_SIZE, TILE_SIZE))
            self.poison_icon = pygame.transform.scale(pygame.image.load(os.path.join('assets', 'poison.png')).convert_alpha(), (TILE_SIZE, TILE_SIZE))
        except:
            self.food_icon = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA); pygame.draw.circle(self.food_icon, (0, 255, 0), (TILE_SIZE//2, TILE_SIZE//2), TILE_SIZE//4)
            self.poison_icon = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA); pygame.draw.circle(self.poison_icon, (255, 0, 0), (TILE_SIZE//2, TILE_SIZE//2), TILE_SIZE//4)

    def login_loop(self):
        """Handles the Login screen interaction."""
        user_field = InputField((220, 200, 200, 40), "USER")
        pass_field = InputField((220, 260, 200, 40), "PASS", is_password=True)
        login_btn = Button((250, 340, 140, 50), "LOGIN", "DO_LOGIN")
        self.leaderboard = self.conn.get_leaderboard_data()
        
        while self.running:
            self.renderer.render_login(user_field, pass_field, login_btn, self.leaderboard)
            for event in pygame.event.get():
                if event.type == pygame.QUIT: self.running = False; return False
                user_field.handle_event(event)
                pass_field.handle_event(event)
                if login_btn.handle_event(event) == "DO_LOGIN":
                    if user_field.text and pass_field.text:
                        if self.conn.attempt_login(user_field.text, pass_field.text): return True
        return False

    def color_selection_loop(self):
        """Handles the 'Choose your color' screen."""
        self.load_assets()
        sq_size, gap = 60, 20
        start_x = (WIDTH * TILE_SIZE - (sq_size * 3 + gap * 2)) // 2
        y = (HEIGHT * TILE_SIZE) // 2
        opts = [{'color': (0, 0, 255), 'rect': pygame.Rect(start_x, y, sq_size, sq_size), 'id': 'blue'},
                {'color': (0, 255, 0), 'rect': pygame.Rect(start_x + sq_size + gap, y, sq_size, sq_size), 'id': 'green'},
                {'color': (255, 105, 180), 'rect': pygame.Rect(start_x + (sq_size + gap) * 2, y, sq_size, sq_size), 'id': 'pink'}]
        while self.running:
            self.renderer.render_color_selection(opts)
            for event in pygame.event.get():
                if event.type == pygame.QUIT: self.running = False; return
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for opt in opts:
                        if opt['rect'].collidepoint(event.pos):
                            self.player_icon = self.icons[opt['id']]
                            return
            time.sleep(0.01)

    def background_receiver(self):
        """Listens for map and score updates from the server in a separate thread."""
        while self.running:
            data = self.conn.receive_data()
            if data:
                if isinstance(data, dict) and "winner" in data:
                    self.winner_name = data["winner"]
                    self.leaderboard = data.get("leaderboard", self.leaderboard)
                elif isinstance(data, dict):
                    self.current_map, self.scores = data.get("map", self.current_map), data.get("scores", self.scores)
                    self.leaderboard = data.get("leaderboard", self.leaderboard)
            else: self.running = False

    def game_loop(self):
        """The main gameplay loop."""
        threading.Thread(target=self.background_receiver, daemon=True).start()
        cx, cy = (WIDTH * TILE_SIZE) // 2, (HEIGHT * TILE_SIZE) + 70
        move_btns = [Button((cx-30, cy-35, 60, 50), "U", "UP"), Button((cx-30, cy+25, 60, 50), "D", "DOWN"),
                Button((cx-100, cy+25, 60, 50), "L", "LEFT"), Button((cx+40, cy+25, 60, 50), "R", "RIGHT")]
        while self.running:
            if self.winner_name:
                self.renderer.render_winner(self.winner_name, self.leaderboard)
                time.sleep(2); self.winner_name = None; continue
            for event in pygame.event.get():
                if event.type == pygame.QUIT: self.running = False
                for btn in move_btns:
                    move = btn.handle_event(event)
                    if move: self.conn.client.sendall(move.encode())
            self.renderer.render_game(self.current_map, self.scores, self.conn.my_id, move_btns, self.player_icon, self.food_icon, self.poison_icon)
            time.sleep(0.01)

    def start(self):
        """The entry point for the whole client application."""
        if self.login_loop():
            self.color_selection_loop()
            if self.running: self.game_loop()
        pygame.quit()

if __name__ == "__main__":
    MazeClient().start()
