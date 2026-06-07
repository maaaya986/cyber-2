import pygame # Library for making games and graphics
import socket # Library for network communication
import pickle # Library for converting Python objects to bytes and back
import threading # Library for running multiple tasks at once
import time # Library for time-related functions
import hashlib # Library for password hashing
import ssl # Library for secure communication
import struct # Library for packing message headers
import os # Library for file paths
from logger_util import Logger # Custom logging
from pyfonts import load_font # Google Fonts loader

# --- Config ---
WIDTH, HEIGHT = 30, 30
TILE_SIZE = 20
PORT, SERVER = 5555, "127.0.0.1"
CONTROLS_HEIGHT = 150
MOVE_DELAY = 0.15 # Seconds between moves when holding a key

COLORS = {
    0: (7, 168, 124), 1: (200, 200, 200), 2: (0, 255, 0),
    3: (255, 0, 0), 9: (0, 0, 255)
}

class UIElement:
    def __init__(self, rect, color):
        self.rect = pygame.Rect(rect)
        self.color = color
    def draw(self, screen, font): pass
    def handle_event(self, event): return False

class Button(UIElement):
    def __init__(self, rect, text, action_val):
        super().__init__(rect, (100, 100, 100))
        self.text, self.action_val = text, action_val
    def draw(self, screen, font):
        pygame.draw.rect(screen, self.color, self.rect, border_radius=8)
        t = font.render(self.text, True, (255, 255, 255))
        screen.blit(t, t.get_rect(center=self.rect.center))
    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos): return self.action_val
        return False

class InputField(UIElement):
    def __init__(self, rect, label, is_password=False):
        super().__init__(rect, (255, 255, 255))
        self.label, self.text = label, ""
        self.active, self.is_password = False, is_password
    def draw(self, screen, font):
        color = (255, 255, 0) if self.active else (150, 150, 150)
        disp = "*" * len(self.text) if self.is_password else self.text
        screen.blit(font.render(f"{self.label}:", True, (200, 200, 200)), (self.rect.x - 130, self.rect.y + 5))
        pygame.draw.rect(screen, (50, 50, 50), self.rect)
        pygame.draw.rect(screen, color, self.rect, 2)
        screen.blit(font.render(disp, True, (255, 255, 255)), (self.rect.x + 5, self.rect.y + 5))
    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN: self.active = self.rect.collidepoint(event.pos)
        if self.active and event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE: self.text = self.text[:-1]
            elif len(event.unicode) == 1: self.text += event.unicode
        return False

class ConnectionManager:
    def __init__(self, logger):
        self.logger, self.my_id, self.client, self.is_host = logger, None, None, False
        self.context = ssl.create_default_context()
        self.context.check_hostname, self.context.verify_mode = False, ssl.CERT_NONE

    def _recv_all(self, n):
        data = b''
        while len(data) < n:
            packet = self.client.recv(n - len(data))
            if not packet: return None
            data += packet
        return data

    def get_leaderboard_data(self):
        try:
            s = self.context.wrap_socket(socket.socket(), server_hostname=SERVER)
            s.connect((SERVER, PORT))
            s.sendall(pickle.dumps({"leaderboard_request": True}))
            d = pickle.loads(s.recv(4096)); s.close()
            return d.get("leaderboard", [])
        except: return []

    def attempt_login(self, user, pw):
        try:
            self.client = self.context.wrap_socket(socket.socket(), server_hostname=SERVER)
            self.client.connect((SERVER, PORT))
            self.client.sendall(pickle.dumps({"username": user, "password": hashlib.sha256(pw.encode()).hexdigest()}))
            resp = pickle.loads(self.client.recv(1024))
            if resp.get("status") == "success":
                self.my_id, self.is_host = resp["id"], resp.get("is_host", False)
                return True
        except: pass
        return False

    def select_player_count(self, count):
        try: self.client.sendall(pickle.dumps({"player_count": count}))
        except: pass

    def send_move(self, move):
        try: self.client.sendall(move.encode())
        except: pass

    def receive_data(self):
        try:
            h = self._recv_all(4)
            if not h: return None
            return pickle.loads(self._recv_all(struct.unpack(">I", h)[0]))
        except: return None

class GameRenderer:
    def __init__(self, screen, font):
        self.screen, self.font = screen, font
    def draw_txt(self, t, x, y, c=(255, 255, 0), center=False):
        img = self.font.render(t, True, c)
        r = img.get_rect(center=(x, y)) if center else img.get_rect(topleft=(x, y))
        self.screen.blit(img, r)
    def render_login(self, u, p, b, lb):
        self.screen.fill((30, 30, 30))
        self.draw_txt("LOGIN", WIDTH*TILE_SIZE//2, 60, center=True)
        self.draw_txt("LEADERBOARD", WIDTH*TILE_SIZE-200, 20)
        for i, e in enumerate(lb): self.draw_txt(f"{i+1}.{e['name']}:{e['score']}", WIDTH*TILE_SIZE-200, 50+i*30, (255,255,255))
        u.draw(self.screen, self.font); p.draw(self.screen, self.font); b.draw(self.screen, self.font)
        pygame.display.flip()
    def render_selection(self, btns):
        self.screen.fill((0, 0, 0))
        self.draw_txt("HOW MANY PLAYERS?", WIDTH*TILE_SIZE//2, 100, center=True)
        for b in btns: b.draw(self.screen, self.font)
        pygame.display.flip()
    def render_waiting(self, current, target):
        self.screen.fill((0, 0, 0))
        self.draw_txt("WAITING ROOM", WIDTH*TILE_SIZE//2, 100, center=True)
        self.draw_txt(f"CONNECTED: {current} / {target}", WIDTH*TILE_SIZE//2, 200, (255,255,255), center=True)
        pygame.display.flip()
    def render_color(self, opts):
        self.screen.fill((0, 0, 0))
        self.draw_txt("CHOOSE YOUR COLOR", WIDTH*TILE_SIZE//2, 100, (255,255,255), center=True)
        for o in opts:
            pygame.draw.rect(self.screen, o['color'], o['rect'])
            pygame.draw.rect(self.screen, (255,255,255), o['rect'], 2)
        pygame.display.flip()
    def render_winner(self, name, lb, next_btn, waiting):
        self.screen.fill((0, 0, 0))
        mx, my = WIDTH*TILE_SIZE//2, (HEIGHT*TILE_SIZE+CONTROLS_HEIGHT)//2
        self.draw_txt("THE WINNER IS", mx, my-80, (255, 255, 0), True)
        self.draw_txt(name.upper(), mx, my-40, (255, 255, 255), True)
        for i, e in enumerate(lb): self.draw_txt(f"{i+1}.{e['name']}:{e['score']}", mx-80, my+10+i*30, (255,255,255))
        if waiting:
            self.draw_txt("WAITING FOR OTHER PLAYERS...", mx, my+130, (0, 255, 255), center=True)
        else:
            next_btn.draw(self.screen, self.font)
        pygame.display.flip()
    def render_game(self, m, s, mid, p_i, f_i, ps_i):
        self.screen.fill((20, 20, 20))
        if m:
            for y in range(HEIGHT):
                for x in range(WIDTH):
                    v, rx, ry = m[y][x], x*TILE_SIZE, y*TILE_SIZE
                    if v >= 10:
                        pygame.draw.rect(self.screen, COLORS[1], (rx, ry, TILE_SIZE, TILE_SIZE))
                        if v == mid: self.screen.blit(p_i, (rx, ry))
                        else: pygame.draw.circle(self.screen, (255, 165, 0), (rx+TILE_SIZE//2, ry+TILE_SIZE//2), TILE_SIZE//2-2)
                    elif v in [2, 3]:
                        pygame.draw.rect(self.screen, COLORS[1], (rx, ry, TILE_SIZE, TILE_SIZE))
                        self.screen.blit(f_i if v==2 else ps_i, (rx, ry))
                    elif v == 9: pygame.draw.rect(self.screen, COLORS[9] if int(time.time()*2)%2==0 else COLORS[1], (rx, ry, TILE_SIZE, TILE_SIZE))
                    else: pygame.draw.rect(self.screen, COLORS.get(v, (127, 127, 127)), (rx, ry, TILE_SIZE, TILE_SIZE))
            self.draw_txt(f"SCORE: {s.get(mid, 0)}", 10, HEIGHT*TILE_SIZE+10, (0, 255, 255))
        pygame.display.flip()

class MazeClient:
    def __init__(self):
        self.logger = Logger("client"); pygame.init()
        try: self.font = load_font("Passion One", size=24)
        except: self.font = pygame.font.SysFont("Arial", 24, bold=True)
        self.screen = pygame.display.set_mode((WIDTH * TILE_SIZE, (HEIGHT * TILE_SIZE) + CONTROLS_HEIGHT))
        self.conn, self.renderer = ConnectionManager(self.logger), GameRenderer(self.screen, self.font)
        self.running, self.map, self.scores, self.lb, self.winner = True, None, {}, [], None
        self.p_i, self.f_i, self.ps_i, self.icons, self.wait_info = None, None, None, {}, None
        self.waiting_for_next = False
        self.last_move_time = 0

    def load_assets(self):
        for c, f in {'blue': 'blue_player.png', 'green': 'green_player.png', 'pink': 'pink_player.png'}.items():
            try: self.icons[c] = pygame.transform.scale(pygame.image.load(os.path.join('assets', f)).convert_alpha(), (TILE_SIZE, TILE_SIZE))
            except:
                s = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA); pygame.draw.circle(s, (255, 255, 0), (TILE_SIZE//2, TILE_SIZE//2), TILE_SIZE//2); self.icons[c] = s
        try:
            self.f_i = pygame.transform.scale(pygame.image.load(os.path.join('assets', 'food.png')).convert_alpha(), (TILE_SIZE, TILE_SIZE))
            self.ps_i = pygame.transform.scale(pygame.image.load(os.path.join('assets', 'poison.png')).convert_alpha(), (TILE_SIZE, TILE_SIZE))
        except:
            self.f_i = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA); pygame.draw.circle(self.f_i, (0, 255, 0), (TILE_SIZE//2, TILE_SIZE//2), TILE_SIZE//4)
            self.ps_i = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA); pygame.draw.circle(self.ps_i, (255, 0, 0), (TILE_SIZE//2, TILE_SIZE//2), TILE_SIZE//4)

    def login_loop(self):
        u, p = InputField((220, 200, 200, 40), "USER"), InputField((220, 260, 200, 40), "PASS", True)
        b, self.lb = Button((250, 340, 140, 50), "LOGIN", "L"), self.conn.get_leaderboard_data()
        while self.running:
            self.renderer.render_login(u, p, b, self.lb)
            for e in pygame.event.get():
                if e.type == pygame.QUIT: self.running = False; return False
                u.handle_event(e); p.handle_event(e)
                if b.handle_event(e) == "L" and u.text and p.text:
                    if self.conn.attempt_login(u.text, p.text): return True
        return False

    def player_count_loop(self):
        btns = [Button((100, 200, 100, 100), "2", 2), Button((250, 200, 100, 100), "3", 3), Button((400, 200, 100, 100), "4", 4)]
        while self.running:
            self.renderer.render_selection(btns)
            for e in pygame.event.get():
                if e.type == pygame.QUIT: self.running = False; return
                for b in btns:
                    val = b.handle_event(e)
                    if val: self.conn.select_player_count(val); return
            time.sleep(0.01)

    def color_loop(self):
        self.load_assets(); sz, g = 60, 20; x = (WIDTH*TILE_SIZE-(sz*3+g*2))//2; y = (HEIGHT*TILE_SIZE)//2
        opts = [{'color': (0,0,255), 'rect': pygame.Rect(x, y, sz, sz), 'id': 'blue'},
                {'color': (0,255,0), 'rect': pygame.Rect(x+sz+g, y, sz, sz), 'id': 'green'},
                {'color': (255,105,180), 'rect': pygame.Rect(x+(sz+g)*2, y, sz, sz), 'id': 'pink'}]
        while self.running:
            self.renderer.render_color(opts)
            for e in pygame.event.get():
                if e.type == pygame.QUIT: self.running = False; return
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    for o in opts:
                        if o['rect'].collidepoint(e.pos): self.p_i = self.icons[o['id']]; return
            time.sleep(0.01)

    def receiver(self):
        while self.running:
            d = self.conn.receive_data()
            if d:
                if d.get("status") == "waiting": self.wait_info = (d["current"], d["target"])
                elif d.get("status") == "winner_screen": self.winner, self.lb = d["winner"], d.get("leaderboard", self.lb)
                elif "winner" in d: self.winner, self.lb = d["winner"], d.get("leaderboard", self.lb)
                else: 
                    self.wait_info, self.winner = None, None
                    self.waiting_for_next = False
                    self.map, self.scores, self.lb = d.get("map", self.map), d.get("scores", self.scores), d.get("leaderboard", self.lb)
            else: self.running = False

    def game_loop(self):
        threading.Thread(target=self.receiver, daemon=True).start()
        next_btn = Button((WIDTH*TILE_SIZE//2 - 100, (HEIGHT*TILE_SIZE+CONTROLS_HEIGHT)//2 + 100, 200, 50), "NEXT LEVEL", "READY")
        
        while self.running:
            if self.wait_info:
                self.renderer.render_waiting(self.wait_info[0], self.wait_info[1])
                for e in pygame.event.get(): 
                    if e.type == pygame.QUIT: self.running = False
                continue
            
            if self.winner:
                self.renderer.render_winner(self.winner, self.lb, next_btn, self.waiting_for_next)
                for e in pygame.event.get():
                    if e.type == pygame.QUIT: self.running = False
                    if not self.waiting_for_next:
                        if next_btn.handle_event(e) == "READY":
                            self.conn.send_move("NEXT_LEVEL_READY")
                            self.waiting_for_next = True
                continue

            for e in pygame.event.get():
                if e.type == pygame.QUIT: self.running = False

            keys = pygame.key.get_pressed()
            current_time = time.time()
            if current_time - self.last_move_time > MOVE_DELAY:
                move = None
                if keys[pygame.K_UP]: move = "UP"
                elif keys[pygame.K_DOWN]: move = "DOWN"
                elif keys[pygame.K_LEFT]: move = "LEFT"
                elif keys[pygame.K_RIGHT]: move = "RIGHT"
                
                if move:
                    self.conn.send_move(move)
                    self.last_move_time = current_time

            self.renderer.render_game(self.map, self.scores, self.conn.my_id, self.p_i, self.f_i, self.ps_i)
            time.sleep(0.01)

    def start(self):
        if self.login_loop():
            if self.conn.is_host: self.player_count_loop()
            self.color_loop()
            if self.running: self.game_loop()
        pygame.quit()

if __name__ == "__main__":
    MazeClient().start()
