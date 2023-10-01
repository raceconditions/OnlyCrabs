# CarSpeed Version 2.0

# import the necessary packages
from pathlib import Path
from pytz import timezone
import time
import math
import datetime
import cv2
import pytz
import logging 
import sys
import os
import requests
import threading
import json
import sqlite3
import argparse
from multiprocessing import Queue

logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
rootLogger = logging.getLogger()
rootLogger.setLevel(logging.DEBUG)
logPath = "/media/onlycrabs"
fileName = "motion"
media_dir = "/media/onlycrabs/"

fileHandler = logging.FileHandler("{0}/{1}.log".format(logPath, fileName))
fileHandler.setFormatter(logFormatter)
rootLogger.addHandler(fileHandler)

consoleHandler = logging.StreamHandler(sys.stdout)
consoleHandler.setFormatter(logFormatter)
rootLogger.addHandler(consoleHandler)

# the following enumerated values are used to make the program more readable
WAITING = 0
TRACKING = 1
BASING = 2
ANALYSIS_SCALE_FACTOR = 2
NO_MOTION_WAIT_TIME = 60
MIN_SAVE_DURATION = 5

class StreamRecorder(object):

    # define timezones
    EASTERN = timezone('US/Eastern')
    UTC = pytz.utc
    THRESHOLD = 64
    MIN_AREA = 1000
    MAX_AREA = 100000
    BLURSIZE = (15,15)
    SHOW_BOUNDS = True
     
    def __init__(self, video_path, stream_name):
        self.video_path = video_path
        self.stream_name = stream_name
        self.state = WAITING
        self.initial_x = 0
        self.last_x = 0
        self.last_base_readjust = None
        self.last_motion = None
        self.last_message = None
        self.base_image = None
        self.secs = 0.0
        self.capture_fps = 0
        self.record_fps_factor = 5
        self.record_fps = 0
        self.is_recording = False
        self.video_out = None
        self.video_frame_count = 0
        self.total_frame_count = 0
        self.video_filepath = None
        self.recording_start_time = None
        self.contour_area_sum = 0
        self.contour_count = 0
        self.motion_frame_count = 0

    def convert_size(self, size_bytes):
        if size_bytes == 0:
            return "0B"
        size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return "%s %s" % (s, size_name[i])
        
    # calculate elapsed seconds
    def secs_diff(self, endTime, begTime):
        diff = (endTime - begTime).total_seconds()
        return diff

    def insert_video_record(self, date, timestamp, path, filename, fps, fps_factor, recording_length, compressed_length, res_x, res_y, size, frame_count):
        self.db_conn = sqlite3.connect(media_dir + "onlycrabs.db")
        cur = self.db_conn.cursor()
        cur.execute("""
            INSERT INTO videos (date, timestamp, path, filename, fps, fps_factor, original_length, compressed_length, resolution_x, resolution_y, camera_name, size, frame_count) VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (date, timestamp, path, filename, fps, fps_factor, recording_length, compressed_length, res_x, res_y, self.stream_name, size, frame_count))
        lr_id = cur.lastrowid
        self.db_conn.commit()
        self.db_conn.close()

        return lr_id

    def insert_analytics_record(self, video_id, contour_count, contour_area_sum, motion_frame_count, total_frame_count):
        self.db_conn = sqlite3.connect(media_dir + "onlycrabs.db")
        cur = self.db_conn.cursor()
        cur.execute("""
            INSERT INTO video_analytics (video_id, total_frame_count, motion_frame_count, contour_count, contour_area_sum) VALUES
            (?, ?, ?, ?, ?)
        """, (video_id, total_frame_count, motion_frame_count, contour_count, contour_area_sum))
        self.db_conn.commit()
        self.db_conn.close()

    def start_recording(self):
        rootLogger.info("############### STARTING RECORDING ###############")
        currenttimestamp = datetime.datetime.now(self.UTC).astimezone(self.EASTERN)
        dateFolder = media_dir + currenttimestamp.strftime("%Y%m%d") + "/"
        imageFilename = "motion_at_" + currenttimestamp.strftime("%Y%m%d_%H%M%S%Z") + ".mp4"
        self.video_filepath = dateFolder + imageFilename

        if not os.path.exists(dateFolder):
            os.makedirs(dateFolder)

        #codec = cv2.VideoWriter_fourcc(*'mp4v')
        codec = cv2.VideoWriter_fourcc(*'avc1')
        resolution = (int(self.resolution_x), int(self.resolution_y))
        #combined with frame modulo to reduce file size
        self.record_fps = (int(self.capture_fps) * self.record_fps_factor) / 2

        rootLogger.info("Filepath: " + self.video_filepath)
        rootLogger.info("FPS: " + str(self.record_fps))
        rootLogger.info("Codec: " + self.decode_fourcc(codec))
        rootLogger.info("Resolution: " + str(resolution))

        self.video_out = cv2.VideoWriter(self.video_filepath, codec, self.record_fps, resolution)
        self.is_recording = True
        self.recording_start_time = currenttimestamp

    def save_image(self, image):
        if self.is_recording:
            self.total_frame_count = self.total_frame_count + 1
            if self.total_frame_count % math.ceil(self.record_fps_factor / 2) == 0:
                self.video_frame_count = self.video_frame_count + 1
                self.video_out.write(image)

    def stop_recording(self):
        if self.video_frame_count > 0:
            rootLogger.info("Stopping recording, wrote %s frames from %s total frames", self.video_frame_count, self.total_frame_count)

        try:
            if self.video_out:
                self.video_out.release()
            else:
                rootLogger.error("No video out object")
        except:
            rootLogger.exception("Unable to release video")

        compressed_length = int(self.video_frame_count / self.record_fps)
        if compressed_length < MIN_SAVE_DURATION:
            rootLogger.warning("Video shorter than {} seconds, discarding.".format(MIN_SAVE_DURATION))
            Path(self.video_filepath).unlink()
        else:
            recording_length = int(self.secs_diff(datetime.datetime.now(self.UTC).astimezone(self.EASTERN), self.recording_start_time))
            path = str(Path(self.video_filepath).parent)
            filename = Path(self.video_filepath).name
            size = self.convert_size(os.path.getsize(self.video_filepath))
            video_id = self.insert_video_record(self.recording_start_time.strftime("%Y%m%d"), self.recording_start_time, path, filename, self.record_fps, self.record_fps_factor, recording_length, compressed_length, self.resolution_x, self.resolution_y, size, self.video_frame_count)
            self.insert_analytics_record(video_id, self.contour_count, self.contour_area_sum, self.motion_frame_count, self.total_frame_count)
            thumbs_thread = threading.Thread(target = self.notify_video_server, args = (path, filename))
            thumbs_thread.start()

        self.total_frame_count = 0
        self.video_frame_count = 0
        self.motion_frame_count = 0
        self.contour_area_sum = 0
        self.contour_count = 0
        self.is_recording = False

    def notify_video_server(self, path, filename):
        payload = {'path': path, 'filename': filename}
        requests.post(url="http://localhost:8085/video",data=json.dumps(payload))

    def decode_fourcc(self, fourcc_prop):
        return int(fourcc_prop).to_bytes(4, byteorder=sys.byteorder).decode()

    #def __start_capture(self):
    def start_capture(self):
        # Open video file
        self.capture = cv2.VideoCapture(self.video_path)
        self.capture_fps = int(self.capture.get(cv2.CAP_PROP_FPS))
        self.resolution_x = self.capture.get(cv2.CAP_PROP_FRAME_WIDTH)
        self.resolution_y = self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
        rootLogger.info("############## STARTING LIVE STREAM ##############")
   
        rootLogger.info("CV_CAP_PROP_FRAME_WIDTH: '{}'".format(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
        rootLogger.info("CV_CAP_PROP_FRAME_HEIGHT : '{}'".format(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        rootLogger.info("CAP_PROP_FPS : '{}'".format(self.capture.get(cv2.CAP_PROP_FPS)))
        rootLogger.info("CAP_PROP_POS_MSEC : '{}'".format(self.capture.get(cv2.CAP_PROP_POS_MSEC)))
        rootLogger.info("CAP_PROP_FRAME_COUNT  : '{}'".format(self.capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        rootLogger.info("CAP_PROP_BRIGHTNESS : '{}'".format(self.capture.get(cv2.CAP_PROP_BRIGHTNESS)))
        rootLogger.info("CAP_PROP_CONTRAST : '{}'".format(self.capture.get(cv2.CAP_PROP_CONTRAST)))
        rootLogger.info("CAP_PROP_SATURATION : '{}'".format(self.capture.get(cv2.CAP_PROP_SATURATION)))
        rootLogger.info("CAP_PROP_HUE : '{}'".format(self.capture.get(cv2.CAP_PROP_HUE)))
        rootLogger.info("CAP_PROP_GAIN  : '{}'".format(self.capture.get(cv2.CAP_PROP_GAIN)))
        rootLogger.info("CAP_PROP_CONVERT_RGB : '{}'".format(self.capture.get(cv2.CAP_PROP_CONVERT_RGB)))
        rootLogger.info("CAP_PROP_CONVERT_RGB : '{}'".format(self.capture.get(cv2.CAP_PROP_CONVERT_RGB)))
        rootLogger.info("CAP_PROP_FOURCC : '{}'".format(self.decode_fourcc(self.capture.get(cv2.CAP_PROP_FOURCC))))

        rootLogger.info("Detected capture with dimensions %s x %s", self.resolution_x, self.resolution_y)
        if self.resolution_x == 0.0 or self.resolution_y == 0.0:
            rootLogger.info("Frame detected as empty, trying again later...")
            return False
    
        while(self.capture.isOpened()):
            try:
                ret, frame = self.capture.read()
                self.process_frame(frame)
            except Exception:
                logging.exception("Failure processing frame.")
                return False;
    
        # Clean up
        self.capture.release()
        return True
    

    def start_stream(self):
        self.stream_thread = threading.Thread(target = self.__start_capture)
        self.stream_thread.daemon = True
        self.stream_thread.start()

    def stop_stream(self):
        self.capture.release()
        self.stream_thread.join()

    def process_frame(self, bgr_frame):
        timestamp = datetime.datetime.now()
        image = bgr_frame

        #track frame processing rate
        self.last_timestamp = timestamp.timestamp()

        gray = cv2.resize(image,(int(self.resolution_x/ANALYSIS_SCALE_FACTOR),int(self.resolution_y/ANALYSIS_SCALE_FACTOR)))
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, self.BLURSIZE, 0)

        if self.base_image is None or self.secs_diff(timestamp, self.last_base_readjust) > 300:
            self.base_image = gray.copy().astype("float")
            self.last_base_readjust = timestamp
            self.state = BASING

        frameDelta = cv2.absdiff(gray, cv2.convertScaleAbs(self.base_image))
        thresh = cv2.threshold(frameDelta, self.THRESHOLD, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)
        (cnts, _) = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)

        # look for motion 
        motion_found = False
        biggest_area = 0

        # examine the contours, looking for the largest one
        if self.state != BASING:
            for c in cnts:
                (x1, y1, w1, h1) = cv2.boundingRect(c)
                # get an approximate area of the contour
                found_area = w1*h1
                # find the largest bounding rectangle
                if (self.MIN_AREA < found_area < self.MAX_AREA):
                    if (found_area > biggest_area):
                        biggest_area = found_area
                        motion_found = True
                    if self.is_recording:
                        self.contour_count += 1
                        self.contour_area_sum += found_area

        if motion_found:
            self.motion_frame_count += 1
            self.last_motion = timestamp
            if not self.is_recording:
                self.start_recording()

            if self.is_recording:       
                try:
                    #save_thread = threading.Thread(target = self.save_image, args=[image])
                    #save_thread.start()
                    self.save_image(image)
                except Exception as e:
                    print("thread exception:", e)
        else:
            if self.state != WAITING:
                self.state = WAITING

        #wait for 60 seconds of no motion before closing video
        if self.is_recording and self.last_motion is not None and self.secs_diff(timestamp, self.last_motion) > NO_MOTION_WAIT_TIME:            
            self.stop_recording()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Process mpjpg video file to change fps.')
    parser.add_argument("video_path", help="URL of the video file to process")
    parser.add_argument("video_name", help="Name of the stream source")
    args = parser.parse_args()
    sr = StreamRecorder(args.video_path, args.video_name)
    
    ret = sr.start_capture()
    if ret == False:
        rootLogger.info("Stream capture failed, retrying...")
        Path("stream.now").touch()
        time.sleep(5)
        for n in range(5):
            rootLogger.info("*** Stream capture retry " + str(n))
            sr.start_capture()
            time.sleep(5)
