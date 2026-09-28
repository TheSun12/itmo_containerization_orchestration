from flask import Flask, request, jsonify
import threading
import time


app = Flask(__name__) 

memory_holder = []

@app.route('/health', methods=['GET'])
def health():
    return 'ok', 200

@app.route('/eat', methods=['GET'])
def eat():
    mb = int(request.args.get('mb', 10))
    chunk = ' ' * (mb * 1024 * 1024)
    memory_holder.append(chunk)
    return jsonify({'mb': mb, 'total_holder': len(memory_holder)})

@app.route('/burn', methods=['GET'])
def burn():

    def spin():
        while True:
            pass

    thread = threading.Thread(target=spin, daemon=True)
    thread.start()
    return jsonify({'status': 'burning one core'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)  #comment