import socket
import threading
import random
import pickle
import sys
import os
import sqlite3
import ssl
import struct
import time
import hashlib
import secrets
from logger_util import Logger

WIDTH = 30
HEIGHT = 30
PORT = 5555
SERVER = "0.0.0.0" 

WALL, PATH, FOOD, POISON, EXIT = 0, 1, 2, 3, 9

class MazeServer:
    def __init__(self):
        self.logger = Logger("server")
        self.init_db()
        sys.setrecursionlimit(2000)
        self.map = None
        self.players = {} 
        self.clients = {} 
        self.next_id = 10 
        self.lock = threading.RLock()
        self.running = True
        
        self.target_player_count = 0
        self.game_started = False
        self.in_winner_phase = False
        self.players_ready_for_next = set()

    def init_db(self):
        conn = sqlite3.connect("maze_game.db")
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users 
                     (username TEXT PRIMARY KEY, password_hash TEXT, salt TEXT, score INTEGER)''')
        conn.commit()
        conn.close()

    def _hash_password(self, password, salt):
        salted_password = password + salt
        return hashlib.sha256(salted_password.encode()).hexdigest()

    def get_user_score(self, username, password_from_client):
        conn = sqlite3.connect("maze_game.db")
        c = conn.cursor()
        c.execute("SELECT password_hash, salt, score FROM users WHERE username=?", (username,))
        row = c.fetchone()
        if row:
            stored_hash, stored_salt, score = row
            if self._hash_password(password_from_client, stored_salt) == stored_hash:
                return score, True
            return 0, False
        salt = secrets.token_hex(16)
        password_hash = self._hash_password(password_from_client, salt)
        c.execute("INSERT INTO users VALUES (?, ?, ?, ?)", (username, password_hash, salt, 0))
        conn.commit()
        conn.close()
        return 0, True

    def save_score(self, username, score):
        conn = sqlite3.connect("maze_game.db")
        c = conn.cursor()
        c.execute("UPDATE users SET score=? WHERE username=?", (score, username))
        conn.commit()
        conn.close()

    def get_leaderboard(self):
        conn = sqlite3.connect("maze_game.db")
        c = conn.cursor()
        c.execute("SELECT username, score FROM users ORDER BY score DESC LIMIT 3")
        rows = c.fetchall()
        conn.close()
        board = []
        for i in range(3):
            if i < len(rows):
                board.append({"name": rows[i][0], "score": rows[i][1]})
            else:
                board.append({"name": "NONE", "score": 0})
        return board

    def generate_map(self):
        maze = [[WALL for _ in range(WIDTH)] for _ in range(HEIGHT)]
        def walk(x, y):
            maze[y][x] = PATH
            directions = [(0, 1), (0, -1), (1, 0), (-1, 0)]
            random.shuffle(directions)
            for dx, dy in directions:
                nx, ny = x + dx*2, y + dy*2
                if 0 < nx < WIDTH-1 and 0 < ny < HEIGHT-1 and maze[ny][nx] == WALL:
                    maze[y+dy][x+dx] = PATH
                    walk(nx, ny)
        walk(1, 1)
        while True:
            ex, ey = random.randint(1, WIDTH-2), random.randint(1, HEIGHT-2)
            if maze[ey][ex] == PATH: maze[ey][ex] = EXIT; break
        for _ in range(25):
            rx, ry = random.randint(1, WIDTH-2), random.randint(1, HEIGHT-2)
            if maze[ry][rx] == PATH: maze[ry][rx] = FOOD
        for _ in range(15):
            rx, ry = random.randint(1, WIDTH-2), random.randint(1, HEIGHT-2)
            if maze[ry][rx] == PATH: maze[ry][rx] = POISON
        return maze

    def broadcast_winner(self, winner_name):
        with self.lock:
            self.in_winner_phase = True
            self.players_ready_for_next.clear()
            state = {
                "status": "winner_screen",
                "winner": winner_name, 
                "leaderboard": self.get_leaderboard()
            }
            data = pickle.dumps(state)
            length_header = struct.pack(">I", len(data))
            for pid, conn in list(self.clients.items()):
                try: conn.sendall(length_header + data)
                except: self.remove_player(pid)

    def check_and_reset(self):
        with self.lock:
            current_count = len(self.players)
            ready_count = len(self.players_ready_for_next)
            
            # Start next level if:
            # 1. At least 2 players are in the game
            # 2. Everyone in the current game has signaled they are ready
            if current_count >= 2 and ready_count >= current_count:
                self.logger.log(f"Resetting level for {current_count} players.")
                self.reset_level()

    def reset_level(self):
        with self.lock:
            self.in_winner_phase = False
            self.players_ready_for_next.clear()
            self.map = self.generate_map()
            for pid in self.players:
                rx, ry = 0, 0
                while True:
                    rx, ry = random.randint(1, WIDTH-2), random.randint(1, HEIGHT-2)
                    if self.map[ry][rx] == PATH: break
                self.players[pid]["pos"] = (rx, ry)
            self.broadcast_state()

    def broadcast_state(self):
        with self.lock:
            if not self.game_started:
                state = {"status": "waiting", "current": len(self.players), "target": self.target_player_count, "leaderboard": self.get_leaderboard()}
            elif self.in_winner_phase:
                return 
            else:
                state = {
                    "map": [row[:] for row in self.map],
                    "scores": {pid: pdata["score"] for pid, pdata in self.players.items()},
                    "names": {pid: pdata["name"] for pid, pdata in self.players.items()},
                    "leaderboard": self.get_leaderboard()
                }
                for pid, pdata in self.players.items():
                    px, py = pdata["pos"]
                    state["map"][py][px] = pid

            data = pickle.dumps(state)
            length_header = struct.pack(">I", len(data))
            for pid, conn in list(self.clients.items()):
                try: conn.sendall(length_header + data)
                except: self.remove_player(pid)

    def remove_player(self, pid):
        with self.lock:
            self.players.pop(pid, None)
            self.clients.pop(pid, None)
            self.players_ready_for_next.discard(pid)
            if not self.players:
                self.game_started = False
                self.target_player_count = 0
                self.map = None
                self.in_winner_phase = False

    def handle_client(self, conn, player_id, addr):
        username = "Unknown"
        try:
            auth_raw = conn.recv(2048)
            if not auth_raw: return
            auth_data = pickle.loads(auth_raw)
            if "leaderboard_request" in auth_data:
                conn.sendall(pickle.dumps({"leaderboard": self.get_leaderboard()}))
                auth_raw = conn.recv(2048)
                if not auth_raw: return
                auth_data = pickle.loads(auth_raw)

            username, password = auth_data["username"], auth_data["password"]
            score, success = self.get_user_score(username, password)
            if not success:
                conn.sendall(pickle.dumps({"status": "fail"}))
                return
            
            is_host = (len(self.players) == 0)
            conn.sendall(pickle.dumps({"status": "success", "id": player_id, "is_host": is_host}))
            
            if is_host:
                count_raw = conn.recv(1024)
                count_data = pickle.loads(count_raw)
                self.target_player_count = count_data.get("player_count", 2)

            with self.lock:
                self.players[player_id] = {"pos": (0,0), "score": score, "name": username}
                self.clients[player_id] = conn
                if self.in_winner_phase:
                    self.players_ready_for_next.add(player_id)
            
            with self.lock:
                if len(self.players) >= self.target_player_count and not self.game_started:
                    self.game_started = True
                    self.reset_level()
                elif self.in_winner_phase:
                    self.check_and_reset()
                else:
                    self.broadcast_state()

            while self.running:
                msg = conn.recv(1024).decode()
                if not msg: break
                
                if msg == "NEXT_LEVEL_READY":
                    with self.lock:
                        self.players_ready_for_next.add(player_id)
                        self.check_and_reset()
                    continue

                if not self.game_started or self.in_winner_phase: continue

                with self.lock:
                    p = self.players.get(player_id)
                    if not p: break
                    nx, ny = p["pos"][0], p["pos"][1]
                    if msg == "UP": ny -= 1
                    elif msg == "DOWN": ny += 1
                    elif msg == "LEFT": nx -= 1
                    elif msg == "RIGHT": nx += 1
                    
                    if 0 <= nx < WIDTH and 0 <= ny < HEIGHT and self.map[ny][nx] != WALL:
                        cell = self.map[ny][nx]
                        if cell == EXIT:
                            p["score"] += 50
                            self.save_score(username, p['score'])
                            self.broadcast_winner(username)
                        else:
                            p["pos"] = (nx, ny)
                            if cell == FOOD: p["score"] += 10; self.map[ny][nx] = PATH; self.save_score(username, p['score'])
                            elif cell == POISON: p["score"] -= 20; self.map[ny][nx] = PATH; self.save_score(username, p['score'])
                            self.broadcast_state()
        except: pass
        finally:
            with self.lock: self.remove_player(player_id)
            if not self.in_winner_phase:
                self.broadcast_state()
            else:
                self.check_and_reset()
            conn.close()

    def start(self):
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(certfile="server.pem")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((SERVER, PORT))
        sock.listen()
        self.logger.log(f"SSL Server Active on {PORT}")
        threading.Thread(target=lambda: (input(), os._exit(0)), daemon=True).start()
        while self.running:
            try:
                raw, addr = sock.accept()
                threading.Thread(target=self.handle_client, args=(context.wrap_socket(raw, server_side=True), self.next_id, addr), daemon=True).start()
                self.next_id += 1
            except: pass

if __name__ == "__main__":
    MazeServer().start()
