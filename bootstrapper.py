import sys
import time
import os
import subprocess
import signal
import logging

from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers import SchedulerNotRunningError

scheduler = BackgroundScheduler()
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("apscheduler").setLevel(logging.ERROR)

LOG_DIRECTORY = "/media/onlycrabs"

class Server:
    def __init__(self, key, cmd):
        global LOG_DIRECTORY
        self.key = key
        self.cmd = cmd
        self.log_location = "{0}/log_{1}.txt".format(LOG_DIRECTORY, key)
        self.log = None
        self.proc = None

    def start(self):
        if os.path.exists(self.log_location):
            os.remove(self.log_location)

        self.log = open(self.log_location, "w")
        self.proc = subprocess.Popen(self.cmd, stderr=subprocess.STDOUT, stdout=self.log)

    def stop(self):
        os.kill(self.proc.pid, signal.SIGTERM)
        os.kill(self.proc.pid, signal.SIGTERM)
        self.log.close()

    def check(self):
        result = self.proc.poll()
        if result is not None:
            logging.info("server {0} process exited with error code: {1}".format(self.key, result))
            self.proc.wait()
            self.proc = subprocess.Popen(self.cmd, stderr=subprocess.STDOUT, stdout=self.log)

class GracefulKiller:
    kill_now = False
    def __init__(self):
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)
  
    def exit_gracefully(self, signum, frame):
        global servers

        logging.info("Received signal " + signal.Signals(signum).name + " from container, cleaning up...")
        for key, server in servers.items():
            server.stop()

        try:
            scheduler.shutdown()
        except SchedulerNotRunningError:
            pass

        exit()

class FileWatcher:
    def __init__(self, src_path):
        self.__src_path = src_path
        self.__event_handler = FilesEventHandler()
        self.__event_observer = Observer()

    def run(self):
        self.start()
        logging.info("Starting FileWatcher with source path %s", src_path)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def start(self):
        self.__schedule()
        self.__event_observer.start()

    def stop(self):
        self.__event_observer.stop()
        self.__event_observer.join()

    def __schedule(self):
        self.__event_observer.schedule(
            self.__event_handler,
            self.__src_path,
            recursive=True
        )

class FilesEventHandler(PatternMatchingEventHandler):
    FILE_PATTERN = ["*.now"]

    def __init__(self):
        super().__init__(patterns=self.FILE_PATTERN)

    def on_any_event(self, event):
        self.process(event)

    def process(self, event):
        filename, ext = os.path.splitext(os.path.basename(event.src_path))
        logging.info("Received %s event", filename)
        if filename == 'restart':
            restart_process()
        if filename == 'stream':
            restart_stream()

def restart_stream():
    logging.info("Restarting docker stream")
    subprocess.Popen(["docker-compose", "restart"], cwd="/home/raceconditions/docker-compose/wyze-bridge")

def restart_process():
    global servers
    for key, server in servers.items():
        server.stop()
        time.sleep(1)
        server.stop()
        time.sleep(2)
        server.start()

def check_process():
    global servers
    for key, server in servers.items():
        server.check()

servers = {}
#servers['a'] = Server('a', ['python3', 'stream_recorder.py', 'https://onlycrabs.raceconditions.net/hls/onlycrabs1.m3u8', 'crab-cam-1']) # > /media/images/log_a.txt 2>&1' &
servers['b'] = Server('b', ['python3', 'stream_recorder.py', 'https://onlycrabs.raceconditions.net/hls/onlycrabs2.m3u8', 'crab-cam-2']) # > /media/images/log_b.txt 2>&1' &
servers['v'] = Server('v', ['python3', 'video_server.py'])

if __name__ == "__main__":
    for key, server in servers.items():
        logging.info("Starting server {0}".format(key))
        server.start()
    src_path = sys.argv[1] if len(sys.argv) > 1 else '.'
    scheduler.add_job(check_process, 'interval', seconds=15)
    scheduler.start()
    killer = GracefulKiller()
    FileWatcher(src_path).run()
    logging.info("Graceful shutdown complete, exiting.")

