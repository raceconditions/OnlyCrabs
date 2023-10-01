import json

from flask import render_template, Blueprint, redirect, url_for, Response
import apis.google_auth

import time
import logging
from threading import Condition
import threading
from flask import Flask, render_template, Response
from pathlib import Path

logging.getLogger().setLevel(logging.INFO)

stream_api = Blueprint('stream_api', __name__, template_folder='templates')

#@stream_api.route('/')
#@stream_api.route('/index.html')
#def index():
#    if apis.google_auth.is_logged_in():
#        return render_template("index.html")
#
#    return redirect(url_for('google_auth.login'))

@stream_api.route('/stream/crab-cam-1')
def crab_cam_1():
    title = "Crab Cam 1"
    stream = "https://onlycrabs.raceconditions.net/hls/onlycrabs1.m3u8"
    return render_template("stream.html", title=title, stream=stream)

@stream_api.route('/stream/crab-cam-2')
def crab_cam_2():
    title = "Crab Cam 2"
    stream = "https://onlycrabs.raceconditions.net/hls/onlycrabs2.m3u8"
    return render_template("stream.html", title=title, stream=stream)

@stream_api.route('/stream/restart')
def restart():
    if apis.google_auth.is_logged_in():
        thread = threading.Thread(target = __restart)
        thread.start()
        return render_template("restart.html")

    return redirect(url_for('google_auth.login'))

def __restart():
    time.sleep(1)
    Path("stream.now").touch()
