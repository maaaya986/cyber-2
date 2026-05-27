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
import secrets # Used for generating unique random "salts"
from logger_util import Logger

# Standard 30x30 Maze Dimensions
WIDTH = 30
HEIGHT = 30
PORT = 5555
SERVER = "0.0.0.0" # Allows connections from any computer on the local network

# Tile types used in our map grid
WALL, PATH, FOOD, POISON, EXIT = 0, 1, 2, 3, 9

class MazeServer:
    def __init__(self):
        self.logger = Logger("server")
        self.init_db() # Setup SQL database for user accounts
        sys.setrecursionlimit(2000) # Prevents "stack overflow" during maze creation
        self.map = self.generate_map() # Create a fresh maze on startup
        
        # Dictionary of dictionaries to store active player data:
        # { player_id: {"pos": (x, y), "score": 0, "name": "user"} }
        self.players = {} 
        
        # Stores the actual network connections: { player_id: ssl_socket }
        self.clients = {} 
        
        self.next_id = 10 # IDs for players start at 10
        
        # Use RLock (Re-entrant Lock) to safely update data across multiple player threads
        self.lock = threading.RLock()
        self.running = True

    def init_db(self):
        """Sets up the SQLite database to store users and scores."""
        conn = sqlite3.connect("maze_game.db")
        c = conn.cursor()
        # 'salt' stores a random string used to make password hashing more secure
        c.execute('''CREATE TABLE IF NOT EXISTS users 
                     (username TEXT PRIMARY KEY, password_hash TEXT, salt TEXT, score INTEGER)''')
        conn.commit()
        conn.close()

    def _hash_password(self, password, salt):
        """Combines a password with a salt and returns a SHA-256 fingerprint."""
        salted_password = password + salt
        return hashlib.sha256(salted_password.encode()).hexdigest()

    def get_user_score(self, username, password_from_client):
        """Verifies a user's password or creates a new account if they don't exist."""
        conn = sqlite3.connect("maze_game.db")
        c = conn.cursor()
        c.execute("SELECT password_hash, salt, score FROM users WHERE username=?", (username,))
        row = c.fetchone()
        
        if row:
            stored_hash, stored_salt, score = row
            # To check the password, we hash the incoming text with the user's specific salt
            if self._hash_password(password_from_client, stored_salt) == stored_hash:
                return score, True
            return 0, False
        
        # If user is new: Generate a unique random 32-character string (salt)
        salt = secrets.token_hex(16)
        password_hash = self._hash_password(password_from_client, salt)
        c.execute("INSERT INTO users VALUES (?, ?, ?, ?)", (username, password_hash, salt, 0))
        conn.commit()
        conn.close()
        return 0, True

    def save_score(self, username, score):
        """Updates the user's permanent score in the database."""
        conn = sqlite3.connect("maze_game.db")
        c = conn.cursor()
        c.execute("UPDATE users SET score=? WHERE username=?", (score, username))
        conn.commit()
        conn.close()

    def get_leaderboard(self):
        """Retrieves the top 3 players from the database."""
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
        """Algorithm to generate a random 30x30 maze where every path is reachable."""
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
        # Place the Exit tile
        while True:
            ex, ey = random.randint(1, WIDTH-2), random.randint(1, HEIGHT-2)
            if maze[ey][ex] == PATH: maze[ey][ex] = EXIT; break
        # Scatter Food and Poison
        for _ in range(25):
            rx, ry = random.randint(1, WIDTH-2), random.randint(1, HEIGHT-2)
            if maze[ry][rx] == PATH: maze[ry][rx] = FOOD
        for _ in range(15):
            rx, ry = random.randint(1, WIDTH-2), random.randint(1, HEIGHT-2)
            if maze[ry][rx] == PATH: maze[ry][rx] = POISON
        return maze

    def broadcast_winner(self, winner_name):
        """Notifies all players that someone won, pauses, then resets the level."""
        self.logger.log(f"Winner sequence for: {winner_name}")
        state = {"winner": winner_name, "leaderboard": self.get_leaderboard()}
        data = pickle.dumps(state)
        # Standard "Message Envelope": 4 bytes for length, then the data
        length_header = struct.pack(">I", len(data))
        with self.lock:
            for pid, conn in list(self.clients.items()):
                try: conn.sendall(length_header + data)
                except: self.remove_player(pid)
        time.sleep(2.1) # Let players see the winner screen before teleporting
        self.reset_level()

    def reset_level(self):
        """Wipes the old maze and builds a new one for the next round."""
        with self.lock:
            self.map = self.generate_map()
            for pid in self.players:
                rx, ry = 0, 0
                while True:
                    rx, ry = random.randint(1, WIDTH-2), random.randint(1, HEIGHT-2)
                    if self.map[ry][rx] == PATH: break
                self.players[pid]["pos"] = (rx, ry)
            self.broadcast_state()

    def broadcast_state(self):
        """Sends the current world (map, scores, leaderboard) to every player."""
        with self.lock:
            state = {
                "map": [row[:] for row in self.map],
                "scores": {pid: pdata["score"] for pid, pdata in self.players.items()},
                "names": {pid: pdata["name"] for pid, pdata in self.players.items()},
                "leaderboard": self.get_leaderboard()
            }
            # Put the players on the map by using their ID as the tile value
            for pid, pdata in self.players.items():
                px, py = pdata["pos"]
                state["map"][py][px] = pid
            data = pickle.dumps(state)
            length_header = struct.pack(">I", len(data))
            for pid, conn in list(self.clients.items()):
                try: conn.sendall(length_header + data)
                except: self.remove_player(pid)

    def remove_player(self, pid):
        """Cleans up player data when someone leaves."""
        self.players.pop(pid, None)
        self.clients.pop(pid, None)

    def handle_client(self, conn, player_id, addr):
        """Main loop that handles one specific player's connection."""
        try:
            # 1. AUTHENTICATION: Receive username and hashed password
            auth_raw = conn.recv(2048)
            if not auth_raw: return
            auth_data = pickle.loads(auth_raw)
            
            # If client just wants the leaderboard before logging in
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
            
            conn.sendall(pickle.dumps({"status": "success", "id": player_id}))
            
            # 2. SETUP: Find a start spot and save the player
            with self.lock:
                while True:
                    rx, ry = random.randint(1, WIDTH-2), random.randint(1, HEIGHT-2)
                    if self.map[ry][rx] == PATH: break
                self.players[player_id] = {"pos": (rx, ry), "score": score, "name": username}
                self.clients[player_id] = conn
            
            self.broadcast_state()
            
            # 3. INTERACTION: Wait for move commands ("UP", "DOWN", etc.)
            while self.running:
                msg = conn.recv(1024).decode()
                if not msg: break # Connection closed
                with self.lock:
                    p = self.players.get(player_id)
                    if not p: break
                    nx, ny = p["pos"][0], p["pos"][1]
                    if msg == "UP": ny -= 1
                    elif msg == "DOWN": ny += 1
                    elif msg == "LEFT": nx -= 1
                    elif msg == "RIGHT": nx += 1
                    
                    # Prevent walking through walls
                    if 0 <= nx < WIDTH and 0 <= ny < HEIGHT and self.map[ny][nx] != WALL:
                        cell = self.map[ny][nx]
                        if cell == EXIT:
                            p["score"] += 50
                            self.save_score(username, p['score'])
                            # Start winner sequence (broadcast winner then reset)
                            threading.Thread(target=self.broadcast_winner, args=(username,), daemon=True).start()
                        else:
                            p["pos"] = (nx, ny)
                            if cell == FOOD: 
                                p["score"] += 10
                                self.map[ny][nx] = PATH # Item consumed
                                self.save_score(username, p['score'])
                            elif cell == POISON: 
                                p["score"] -= 20
                                self.map[ny][nx] = PATH # Item consumed
                                self.save_score(username, p['score'])
                            self.broadcast_state()
        except: pass
        finally:
            # Clean up and notify others that this player left
            with self.lock: self.remove_player(player_id)
            self.broadcast_state()
            conn.close()

    def start(self):
        """Initializes the SSL security tunnel and starts the server."""
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(certfile="server.pem") # Uses the file from generate_cert.py
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((SERVER, PORT))
        sock.listen()
        self.logger.log(f"SSL Server Active on Port {PORT}")
        
        # Background thread to allow closing server by pressing enter
        threading.Thread(target=lambda: (input(), os._exit(0)), daemon=True).start()
        
        while self.running:
            try:
                raw, addr = sock.accept()
                # Wrap each connection in the SSL security layer
                threading.Thread(target=self.handle_client, args=(context.wrap_socket(raw, server_side=True), self.next_id, addr), daemon=True).start()
                self.next_id += 1
            except: pass

if __name__ == "__main__":
    MazeServer().start()
