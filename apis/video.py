from datetime import datetime, timedelta
from pytz import timezone
from flask_table import Table, Col, DatetimeCol, LinkCol
from flask import render_template, Blueprint, redirect, url_for, Response, request, abort, g

from pathlib import Path

import requests
import apis.google_auth
import logging
import os
import json
import math
import cv2

import sqlite3

logging.getLogger().setLevel(logging.INFO)

video_api = Blueprint('video_api', __name__, template_folder='templates')
local_tz = timezone('US/Eastern')

PAGE_SIZE = 96

class CrabitatTable(Table):
    prop = Col('Property')
    val = Col('Value')
    last_updated = DatetimeCol('Last Updated', datetime_format="yyyy.MM.dd h:mma")

class VideoTable(Table):
    timestamp = DatetimeCol('Timestamp', datetime_format="yyyy.MM.dd h:mma")
    #date = Col('Date')
    camera_name = Col('Camera')
    #compressed_length = Col('Length')
    #fps = Col('FPS')
    duration = Col('Duration')
    claw = Col('CLAW Score')
    #size = Col('Size')
    filename = LinkCol('Video', '.play_video', url_kwargs=dict(id='id'))


@video_api.before_request
def before_request():
    try:
        g.db_conn = sqlite3.connect("/media/onlycrabs/onlycrabs.db")
        g.db_conn.row_factory = sqlite3.Row
        g.db_cur = g.db_conn.cursor()
    except Exception as e:
        logging.exception(e)
        abort(503, "Database connection could be established.")

# close the connection after each request
@video_api.teardown_request
def teardown_request(exception):
    try:
        g.db_conn.commit()
        g.db_conn.close()
    except:
        pass

@video_api.route('/', methods=['GET'])
def onlycrabs_index():
    return render_template('index.html')

@video_api.route('/crabitat/status', methods=['GET'])
def rosie_config():
    global videos_table
    if apis.google_auth.is_logged_in():
        headers = {'Authorization': 'Bearer ' + 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiI4MjUyMGJiNjk1NWY0ZDI1OWVkZjdkOTE3ODQ3Zjc2NyIsImlhdCI6MTY5NjAwMzcwNCwiZXhwIjoyMDExMzYzNzA0fQ.ukYzVq8QM0ZEOaXO1U03H_MT3slFW-R1ECqDNIK4xr0', 'Content-Type': 'application/json'}
        res = requests.get(url="http://192.168.1.5:8123/api/states/sensor.wifi_temperature_humidity_sensor_humidity", headers=headers)
        humidity_res = json.loads(res.text)
        humidity = "{}{}".format(humidity_res["state"], humidity_res["attributes"]["unit_of_measurement"])
        h_lu = datetime.fromisoformat(humidity_res["last_updated"]).astimezone(local_tz)
        res = requests.get(url="http://192.168.1.5:8123/api/states/sensor.wifi_temperature_humidity_sensor_temperature", headers=headers)
        temperature_res = json.loads(res.text)
        temperature = "{}{}".format(temperature_res["state"], temperature_res["attributes"]["unit_of_measurement"])
        t_lu = datetime.fromisoformat(temperature_res["last_updated"]).astimezone(local_tz)
        res = requests.get(url="http://192.168.1.5:8123/api/states/switch.crab_tank_exhaust_fan", headers=headers)
        fan_res = json.loads(res.text)
        fan = "{}".format(fan_res["state"])
        f_lu = datetime.fromisoformat(fan_res["last_updated"]).astimezone(local_tz)
        res = requests.get(url="http://192.168.1.5:8123/api/states/switch.crab_tank_bubbler", headers=headers)
        bubbler_res = json.loads(res.text)
        bubbler = "{}".format(bubbler_res["state"])
        b_lu = datetime.fromisoformat(bubbler_res["last_updated"]).astimezone(local_tz)

        props = [
                {"prop": "Temperature", "val": temperature, "last_updated": t_lu},
                {"prop": "Humidity", "val": humidity, "last_updated": h_lu},
                {"prop": "Exhaust Fan", "val": fan, "last_updated": f_lu},
                {"prop": "Bubbler", "val": bubbler, "last_updated": b_lu}
        ]
        table = CrabitatTable(props, table_id='crabitat-table')
        return render_template('crabitat.html', table=table)

@video_api.route('/video/<id>/play', methods=['GET'])
def play_video(id):
    global videos_table
    if apis.google_auth.is_logged_in():
        row = g.db_cur.execute("SELECT date, filename FROM videos where id = ?", (id,)).fetchone()
        filename = row["filename"]
        folder = row["date"]
        frows = g.db_cur.execute("SELECT id, title, description, expires from featured WHERE video_id=?", (id,))
        featureds = [dict(row) for row in frows]
        if len(featureds) == 0:
            is_featured = False
            feature = {"title":"", "description":"", "expires":""}
        else:
            is_featured = True
            feature = featureds[0]
        return render_template('video.html', path="https://onlycrabs.raceconditions.net/videos/{}/{}".format(folder, filename), delete=url_for('.delete_video', id=id), id=id, video=row, is_featured=is_featured, feature=feature)

@video_api.route('/video/<id>/feature', methods=['POST'])
def feature_video(id):
    global videos_table
    payload = request.data
    feature = json.loads(payload)
    logging.info(feature)
    if apis.google_auth.is_logged_in():
        rows = g.db_cur.execute("SELECT id from featured WHERE video_id=?", (id,))
        featureds = [dict(row) for row in rows]
        if len(featureds) > 0:
            g.db_cur.execute("UPDATE featured set title=?, description=?, expires=? WHERE video_id=?", (feature["title"], feature["description"], feature["expires"], id))
        else:
            g.db_cur.execute("INSERT INTO featured (video_id, title, description, expires) VALUES (?, ?, ?, ?)", (id, feature["title"], feature["description"], feature["expires"]))
    return '', 200

@video_api.route('/video/<id>/delete', methods=['GET'])
def delete_video(id):
    global videos_table
    if apis.google_auth.is_logged_in():
        row = g.db_cur.execute("SELECT path, filename FROM videos where id = ?", (id,)).fetchone()
        filename = row["filename"]
        path = row["path"]
        delete_video(id, path, filename)
    return redirect(url_for(".video_gallery"))

@video_api.route('/video', methods=['POST'])
def save_video():
    global videos_table

    payload = request.data
    if apis.google_auth.is_logged_in():
        video = json.loads(payload)
        folder = video['path']
        filename = video['filename']
        video_path = "{}/{}".format(folder, filename)
        try:
            (thumb_filenames, frame_count, fps) = video_to_frames(video_path, folder, filename.replace('.mp4',''))
            logging.info("Successfully unpacked video with {} frames, {} fps, from file {}".format(frame_count, fps, filename))
        except:
            logging.exception("Failed generating thumbs from video.")
        return '', 200

@video_api.route('/video', methods=['GET'])
def list_videos():
    global videos_table, PAGE_SIZE
    page = request.args.get('page', default = 1, type = int)
    start = ((page - 1) * PAGE_SIZE)
    if apis.google_auth.is_logged_in():
        total_count = int(g.db_cur.execute("SELECT COUNT(id) from videos").fetchone()[0])
        rows = g.db_cur.execute("SELECT v.*, ROUND((va.contour_count * 1.0)/va.total_frame_count, 2) as claw from videos v join video_analytics va on v.id=va.video_id ORDER BY timestamp DESC LIMIT ? OFFSET ?", (PAGE_SIZE, start)).fetchall()
        ret = [dict(row) for row in rows]
        for video in ret:
            video["timestamp"] = datetime.fromisoformat(video["timestamp"])
            video['duration'] = str(timedelta(seconds=int(video['compressed_length'])))
            #video['size'] = convert_size(video['size'])
        table = VideoTable(ret, table_id='videos-table')
        return render_template('video_list.html', table=table, total_count=total_count, current = page, pages=range(1, int((total_count + PAGE_SIZE - 1)/PAGE_SIZE)))

@video_api.route('/video/gallery', methods=['GET'])
def video_gallery():
    global videos_table, PAGE_SIZE
    page = request.args.get('page', default = 1, type = int)
    start = ((page - 1) * PAGE_SIZE)
    if apis.google_auth.is_logged_in():
        total_count = int(g.db_cur.execute("SELECT COUNT(id) from videos").fetchone()[0])
        rows = g.db_cur.execute("SELECT * from videos ORDER BY timestamp DESC LIMIT ? OFFSET ?", (PAGE_SIZE, start)).fetchall()
        videos = [dict(row) for row in rows]
        for video in videos:
            video["timestamp"] = datetime.fromisoformat(video["timestamp"])
            video['duration'] = str(timedelta(seconds=int(video['compressed_length'])))
            basename = Path(video['filename']).stem
            thumbs = []
            for i in range(1, 5):
                thumbs.append('t_{}_{}.png'.format(i, basename))
            video['thumbs'] = thumbs #",".join(thumbs)
            video['folder'] = "/videos/{}/thumbs".format(video['date'])
        return render_template('video_gallery.html', videos=videos, total_count=total_count, current = page, pages=range(1, int((total_count + PAGE_SIZE - 1)/PAGE_SIZE)))

@video_api.route('/video/featured', methods=['GET'])
def featured_gallery():
    global videos_table
    if apis.google_auth.is_logged_in():
        rows = g.db_cur.execute("select * from featured inner join videos on featured.video_id = videos.id order by videos.timestamp;", ()).fetchall()
        videos = [dict(row) for row in rows]
        for video in videos:
            video["timestamp"] = datetime.fromisoformat(video["timestamp"])
            video['duration'] = str(timedelta(seconds=int(video['compressed_length'])))
            basename = Path(video['filename']).stem
            thumbs = []
            for i in range(1, 5):
                thumbs.append('t_{}_{}.png'.format(i, basename))
            video['thumbs'] = thumbs #",".join(thumbs)
            video['folder'] = "/videos/{}/thumbs".format(video['date'])
        return render_template('featured_gallery.html', videos=videos, total_count=len(videos), current=1, pages=range(1, 1))

def convert_size(size_bytes):
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, size_name[i])

def video_to_frames(video_filepath, folder, base_filename):
    Path("{}/thumbs".format(folder)).mkdir(parents=True, exist_ok=True)
    size = 320
    logging.info("Processing thumbs for video {}".format(video_filepath))
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
                logging.error("Failed writing frame id: {}".format(frame_id))
    return (frames, video_length, fps)

def delete_video(id, path, filename):
    video_filepath = Path("{}/{}".format(path, filename))
    basename = video_filepath.name.replace('.mp4','')
    video_filepath.unlink(missing_ok=True)
    for i in range(1, 5):
        Path("{}/t_{}_{}.png".format(path, i, basename)).unlink(missing_ok=True)
    g.db_cur.execute("DELETE FROM videos WHERE id=?", (id,))

def delete_videos_older_than(days):
    g.db_cur.execute("select * from videos where timestamp < date('now', '-30 hours') order by timestamp asc;").fetchall()
    videos = videos_table.order_by(r.desc('date')).filter(lambda v: v['date'] < (r.now() - (days * 24 * 60 * 60))).run(rdb_conn)
    for video in videos:
        delete_video_by_id(video['id'], rdb_conn)
