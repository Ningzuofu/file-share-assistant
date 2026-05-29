import os
import json
import base64
import hashlib
import re

CONFIG_FILE = 'config.json'

MD5_PATTERN = re.compile(r'^[0-9a-f]{32}$')

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
    if not stored_hash:
        return not input_password
    if not input_password:
        return False
    base64_encoded = base64.b64encode(input_password.encode('utf-8')).decode('utf-8')
    input_hash = hashlib.md5(base64_encoded.encode('utf-8')).hexdigest()
    return input_hash == stored_hash

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                if 'password' in config:
                    raw_password = config.pop('password')
                    if raw_password and 'password_hash' not in config:
                        config['password_hash'] = encrypt_password(raw_password)
                    elif raw_password and config.get('password_hash') == raw_password:
                        config['password_hash'] = encrypt_password(raw_password)
                raw_hash = config.get('password_hash', '')
                if raw_hash and not MD5_PATTERN.match(raw_hash):
                    config['password_hash'] = encrypt_password(raw_hash)
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