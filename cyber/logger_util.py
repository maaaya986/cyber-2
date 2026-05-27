import os
import datetime

class Logger:
    """A helper class to record everything that happens in the game to a text file."""
    
    def __init__(self, prefix):
        """
        Sets up the logger.
        prefix: 'client' or 'server' to identify where the log is coming from.
        """
        # Get the unique ID of the running program (Process ID)
        self.process_id = os.getpid()
        
        # Create a filename like 'server_1234.txt'
        self.filename = f"{prefix}_{self.process_id}.txt"
        
        # Write the first line to start the file
        self.log(f"Logger initialized for {prefix} (PID: {self.process_id})")

    def log(self, message):
        """Takes a message, adds a timestamp, and saves it to the file."""
        # Get current date and time (Year-Month-Day Hour:Minute:Second)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Combine timestamp and message
        log_entry = f"[{timestamp}] {message}"
        
        # Print it to the black console window so we can see it live
        print(log_entry)
        
        try:
            # Open the file in 'append' mode ('a') so we don't overwrite previous logs
            with open(self.filename, "a") as f:
                f.write(log_entry + "\n")
        except Exception as e:
            # If something goes wrong with the file, at least tell the console
            print(f"Error writing to log file: {e}")
