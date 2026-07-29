from app import create_app
from app import socketio

app = create_app()

if __name__ == '__main__':
    socketio.run(app, host='127.0.0.1', port=1904, debug=False)