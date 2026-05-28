import os
import json
import base64
import hashlib

CONFIG_FILE = 'config.json'

DEFAULT_CONFIG = {
    'port': 8080,
    'folder': os.path.expanduser('~'),
    'password_hash': '',
    'enabled': False,
    'max_upload_size': 1024,
    'max_upload_unit': 'MB'
}

def encrypt_password(password):
    if not password:
        return ''
    base64_encoded = base64.b64encode(password.encode('utf-8')).decode('utf-8')
    md5_hash = hashlib.md5(base64_encoded.encode('utf-8')).hexdigest()
    return md5_hash

def verify_password(input_password, stored_hash):
    if not input_password or not stored_hash:
        return input_password == stored_hash
    base64_encoded = base64.b64encode(input_password.encode('utf-8')).decode('utf-8')
    input_hash = hashlib.md5(base64_encoded.encode('utf-8')).hexdigest()
    return input_hash == stored_hash

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                if 'password' in config and 'password_hash' not in config:
                    config['password_hash'] = config['password']
                    del config['password']
                return config
        except:
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()

def save_config(config):
    config_to_save = config.copy()
    if 'password' in config_to_save:
        password = config_to_save.pop('password')
        if password:
            config_to_save['password_hash'] = encrypt_password(password)
        else:
            config_to_save['password_hash'] = ''
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_to_save, f, indent=4)