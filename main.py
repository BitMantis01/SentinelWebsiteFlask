from app import create_app, socketio

application = create_app()

if __name__ == '__main__':
    print("Starting Flask-SocketIO server...")
    socketio.run(application, host='127.0.0.1', port=5000, debug=True)
