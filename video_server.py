from flask import Flask

from apis.video import video_api
from apis.google_auth import google_api
from apis.stream import stream_api

app = Flask(__name__)
app.register_blueprint(video_api)
app.register_blueprint(stream_api)
app.register_blueprint(google_api)
app.secret_key = 'aspdoihasdfoihasdfasdf345adf'

app.run(host='0.0.0.0', port=8085, debug=True, use_reloader=True)
