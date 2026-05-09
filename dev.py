import sys
import time
import subprocess
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class RestartHandler(FileSystemEventHandler):
    def __init__(self, command):
        self.command = command
        self.process = None
        self.restart()

    def restart(self):
        if self.process:
            print("\n[Dev] File changed, restarting...")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        
        print(f"[Dev] Starting: {' '.join(self.command)}")
        self.process = subprocess.Popen(self.command)

    def on_modified(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(".py") or event.src_path.endswith(".css"):
            self.restart()

if __name__ == "__main__":
    path = "."
    command = [sys.executable, "comic.py"]
    
    event_handler = RestartHandler(command)
    observer = Observer()
    observer.schedule(event_handler, path, recursive=True)
    observer.start()
    
    print("[Dev] Watching for changes in .py and .css files...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        if event_handler.process:
            event_handler.process.terminate()
    observer.join()
