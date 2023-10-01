from datetime import datetime, timedelta
from pytz import timezone

from flask import render_template, Blueprint, redirect, url_for, Response, request

from pathlib import Path

import logging
import os
import json
import math
import cv2

import argparse
import sqlite3

logging.getLogger().setLevel(logging.INFO)


class VideoManager(object):
    def __get_list_from_db(self, where=""):
        self.db_conn = sqlite3.connect("/media/onlycrabs/onlycrabs.db")
        self.db_conn.row_factory = sqlite3.Row
        self.db_cur = self.db_conn.cursor()

        rows = self.db_cur.execute("SELECT * FROM videos {} order by timestamp desc".format(where))
        videos = [dict(row) for row in rows]

        self.db_conn.close()
        return videos

    def __execute_db_query(self, query, q_tuple, return_id=False):
        self.db_conn = sqlite3.connect("/media/onlycrabs/onlycrabs.db")
        self.db_conn.row_factory = sqlite3.Row
        self.db_cur = self.db_conn.cursor()

        self.db_cur.execute(query, q_tuple)
        lr_id = None
        if return_id:
            lr_id = self.db_cur.lastrowid
        logging.info("Query affected {} rows.".format(self.db_cur.rowcount))
        self.db_conn.commit()
        self.db_conn.close()

        return lr_id

    def __video_exists(self, video_filename):
        self.db_conn = sqlite3.connect("/media/onlycrabs/onlycrabs.db")
        self.db_conn.row_factory = sqlite3.Row
        self.db_cur = self.db_conn.cursor()

        rows = self.db_cur.execute("SELECT id FROM videos WHERE filename=?", (video_filename,))
        videos = [dict(row) for row in rows]
        self.db_conn.close()

        if len(videos) > 1:
            logging.error("More than one row found for filename")
            return videos[0]['id']
        elif (len(videos) == 1):
            return videos[0]['id']
        else:
            return False

    def __dump_schema(self, table):
        c = sqlite3.connect("/media/onlycrabs/onlycrabs.db")
        c.execute("PRAGMA table_info('{}')".format(table))
        for i in a:
            print(i)
        c.close()

    def __create_videos_table(self):
        __execute_db_query("CREATE TABLE videos (id INTEGER PRIMARY KEY, date INTEGER, timestamp TEXT, path TEXT, filename TEXT, fps INTEGER, fps_factor INTEGER, original_length INTEGER, compressed_length INTEGER, resolution_x INTEGER, resolution_y INTEGER, camera_name TEXT, size TEXT, frame_count INTEGER)", ())

    def __create_feature_table(self):
        __execute_db_query("CREATE TABLE featured (id INTEGER PRIMARY KEY, title TEXT, description TEXT, expires TEXT, video_id INTEGER)", ())

    def __create_analytics_table(self):
        __execute_db_query("CREATE TABLE video_analytics (id INTEGER PRIMARY KEY, video_id INTEGER, total_frame_count INTEGER, motion_frame_count INTEGER, contour_count INTEGER, contour_area_sum INTEGER)", ())

    def convert_size(self, size_bytes):
        if size_bytes == 0:
            return "0B"
        size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return "%s %s" % (s, size_name[i])

    def list_all_videos(self):
        videos = self.__get_list_from_db()
        for video in videos:
            print(video)

    def sync_db_from_filesystem(self):
        videos = self.__get_list_from_db()

        for video in videos:
            video_path = "{}/{}".format(video["path"], video["filename"])
            if os.path.exists(video_path):
                size = os.path.getsize(video_path)
                logging.info("updating video size raw {} and formatted {}for path {}".format(size, self.convert_size(size), video_path))
                #__execute_db_query("UPDATE videos SET size=? where id=?", (self.convert_size(size), video["id"]))
            else:
                logging.info("deleting video {} with id {}".format(video_path, video["id"]))
                #__execute_db_query("DELETE FROM videos where id=?", (video["id"],))

    def update_video_size_for_folder(self, folder):
        videos = Path(folder).glob("*.mp4")

        for video in videos:
            size = self.convert_size(os.path.getsize(str(video)))
            self.__execute_db_query("UPDATE videos SET size=? where filename=?", (size, video.name))

    def find_missing_db_records(self, folder):
        videos = Path(folder).glob("*.mp4")

        for video in videos:
            if not self.__video_exists(video.name):
                logging.info("Video record not found for: {}".format(str(video)))

    def __remove_video(self, path):
        video = Path(path)
        video.unlink()
        self.__execute_db_query("DELETE FROM videos WHERE filename=?", (video.name,))

    def sync_filesystem_to_db(self, folder):
        Path("{}/thumbs".format(folder)).mkdir(parents=True, exist_ok=True)
        videos = Path(folder).glob("*.mp4")

        success_count = 0
        failure_count = 0
        deleted_count = 0
        for video in videos:
            try:
                fps_factor = 5
                video_filepath = str(video)
                size = os.path.getsize(video_filepath)

                if size == 262:
                    self.__remove_video(video_filepath)
                    deleted_count += 1
                    continue

                capture = cv2.VideoCapture(video_filepath)
                capture_fps = int(capture.get(cv2.CAP_PROP_FPS))
                resolution_x = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
                resolution_y = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
                frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

                if capture_fps == 0 or frame_count < 250:
                    self.__remove_video(video_filepath)
                    deleted_count += 1
                    continue

                compressed_length = int(frame_count / capture_fps)
                original_frame_count = math.ceil(fps_factor / 2) * frame_count
                original_fps = (capture_fps * 2) / fps_factor
                original_length = original_frame_count / original_fps
                stream_name = 'crab-cam-1'
                date = int(video.parent.name)
                timestamp = datetime.strptime(video.name, "motion_at_%Y%m%d_%H%M%S%Z.mp4")
                res_x = 1920
                res_y = 1080
    
                exists = self.__video_exists(video.name)
                if exists:
                    logging.info("UPDATE videos SET frame_count={}, original_length={}, compressed_length={}, size={} where id={}".format(frame_count, original_length, compressed_length, self.convert_size(size), exists))
                    self.__execute_db_query("UPDATE videos SET frame_count=?, original_length=?, compressed_length=?, size=? where id=?", (frame_count, original_length, compressed_length, self.convert_size(size), exists))
                else:
                    logging.info("INSERT INTO videos (date, timestamp, path, filename, fps, fps_factor, original_length, compressed_length, resolution_x, resolution_y, camera_name, size, frame_count) VALUES ({}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {})".format(date, timestamp, video_filepath, video.name, capture_fps, fps_factor, original_length, compressed_length, res_x, res_y, stream_name, self.convert_size(size), frame_count))
                    self.__execute_db_query("INSERT INTO videos (date, timestamp, path, filename, fps, fps_factor, original_length, compressed_length, resolution_x, resolution_y, camera_name, size, frame_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (date, timestamp, video_filepath, video.name, capture_fps, fps_factor, original_length, compressed_length, res_x, res_y, stream_name, self.convert_size(size), frame_count))
                success_count +=1
            except:
                logging.exception("Failed video {} with size {}".format(video.name, size))
                failure_count +=1

        logging.info("TOTAL: {}\r\nDELETED: {}\r\nFAILED: {}\r\nSUCCESS: {}".format(deleted_count + success_count + failure_count, deleted_count, failure_count, success_count))
 
    def __video_to_frames(self, video_filepath, folder, base_filename):
        size = 320
        cap = cv2.VideoCapture(video_filepath)
        video_length = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) - 1
        fps = cap.get(cv2.CAP_PROP_FPS)      # OpenCV2 version 2 used "CV_CAP_PROP_FPS"
        frames = []
        if cap.isOpened() and video_length > 0:
            frame_ids = []
            if video_length >= 100:
                frame_ids = [1,
                             round(video_length * 0.22),
                             round(video_length * 0.45),
                             round(video_length * 0.67),
                             round(video_length * 0.9)]
                logging.info("PATH: {}".format(video_filepath))
                logging.info("FRAME COUNT: {}".format(video_length))
                logging.info("FRAME IDS: {}".format(", ".join("'{0}'".format(n) for n in frame_ids)))
            else:
                logging.error("Less than 100 frames detected, deleting file {}".format(video_filepath))
                Path(video_filepath).unlink()
            count = 0
            last_thumb = None
            for frame_id in frame_ids:
                logging.debug("Trying frame id: {}".format(frame_id))
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_id)
                success = None
                for i in range((frame_id+1), min(frame_id+50, video_length)):
                    success, image = cap.read()
                    if success or last_thumb is not None:
                        break
                    else:
                        logging.info("Failed frame {} in range of {}:{}".format(i, (frame_id+1), min(frame_id+50, video_length)))
                        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_id + (i))
                if success:
                    count += 1
                    thumb_filename = "t_{}_{}.png".format(count, base_filename)
                    logging.debug("Writing frame {} to file '{}'".format(str(frame_id), thumb_filename))
                    frames.append(thumb_filename)
                    height, width, channels = image.shape
                    r = (size + 0.0) / width
                    max_size = (size, int(height * r))
                    max_size = (320, 180)
                    thumb = cv2.resize(image, max_size, interpolation=cv2.INTER_AREA)
                    cv2.imwrite("{}/thumbs/{}".format(folder, thumb_filename), thumb)
                    last_thumb = thumb
                else:
                    if last_thumb is not None:
                        count += 1
                        thumb_filename = "t_{}_{}.png".format(count, base_filename)
                        frames.append(thumb_filename)
                        cv2.imwrite("{}/thumbs/{}".format(folder, thumb_filename), last_thumb)
                    logging.error("Failed writing frame id: {}, wrote previous thumb.".format(frame_id))
        return (frames, video_length, fps)
    
    def add_thumbs_file(self, video_filepath):
        folder = str(Path(video_filepath).parent)
        Path("{}/thumbs".format(folder)).mkdir(parents=True, exist_ok=True)
        base_filename = Path(video_filepath).name.replace('.mp4','')
    
        (thumb_filenames, frame_count, fps) = self.__video_to_frames(video_filepath, folder, base_filename)
        print(", ".join(thumb_filenames))
    
    def add_thumbs_directory(self, folder):
        Path("{}/thumbs".format(folder)).mkdir(parents=True, exist_ok=True)
        videos = Path(folder).glob("*.mp4")

        for video in videos:
            try:
                (thumb_filenames, frame_count, fps) = self.__video_to_frames(str(video), folder, video.name.replace('.mp4', ''))
                print(", ".join(thumb_filenames))
            except:
                logging.exception("Failed processing video '{}'".format(video.name))

actions = [
        "add_thumbs_file",
        "atf",
        "add_thumbs_directory",
        "atd",
        "sync_db",
        "sdb",
        "sync_fs",
        "sfs",
        "list_db",
        "ldb",
        "update_size_directory",
        "usd",
        "diff_fs_to_db",
        "fsd"
]

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Utility for managing OnlyCrabs.')
    parser.add_argument("action", help="Action to execute")
    parser.add_argument("--path", help="Folder path for the video", default="/media/onlycrabs")
    parser.add_argument("--filename", help="Name of the video or stream source", default=None)
    parser.add_argument("--cam-name", help="Name of camera for this process", default="crab-cam-1")
    parser.add_argument("--web-port", help="Port to run the web server on", type=int, default=8081)
    #parser.add_argument("--flag", help="Store Flag", action='store_true')
    args = parser.parse_args()
    vm = VideoManager()

    if args.action in [actions[0], actions[1]]:
        vm.add_thumbs_file(args.filename)
    elif args.action in [actions[2], actions[3]]:
        vm.add_thumbs_directory(args.path)
    elif args.action in [actions[4], actions[5]]:
        vm.sync_db_from_filesystem()
    elif args.action in [actions[6], actions[7]]:
        vm.sync_filesystem_to_db(args.path)
    elif args.action in [actions[8], actions[9]]:
        vm.list_all_videos()
    elif args.action in [actions[10], actions[11]]:
        vm.update_video_size_for_folder(args.path)
    elif args.action in [actions[12], actions[13]]:
        vm.find_missing_db_records(args.path)
    else:
        print("Invalid action provided, options are: {}".format(", ".join(actions)))
