# users/fields.py
import base64
import json
from django.db import models
from django.conf import settings
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from Crypto.Util.Padding import pad, unpad

class EncryptedCharField(models.TextField): # Use TextField for flexibility with Base64 encoded data
    """
    A custom Django model field that encrypts and decrypts string data
    using AES-256 GCM mode. Data is stored as Base64 encoded JSON.

    The encryption key is retrieved from settings.ENCRYPTION_KEY.
    """
    def __init__(self, *args, **kwargs):
        # Ensure max_length is handled by the underlying TextField if needed,
        # but encryption will change length, so it's more about database column type.
        super().__init__(*args, **kwargs)
        # self.key is already bytes from settings.ENCRYPTION_KEY = base64.b64decode(...)
        self.key = settings.ENCRYPTION_KEY 
        if len(self.key) not in [16, 24, 32]:
            raise ValueError("ENCRYPTION_KEY must be 16, 24, or 32 bytes for AES.")

    def from_db_value(self, value, expression, connection):
        """
        Converts the database value (encrypted string) back to a Python object (decrypted string).
        """
        if value is None:
            return value
        try:
            # Decode Base64 and load JSON
            decoded = base64.b64decode(value)
            encrypted_data = json.loads(decoded.decode('utf-8'))

            nonce = base64.b64decode(encrypted_data['nonce'])
            ciphertext = base64.b64decode(encrypted_data['ciphertext'])
            tag = base64.b64decode(encrypted_data['tag'])

            cipher = AES.new(self.key, AES.MODE_GCM, nonce=nonce)
            decrypted_bytes = cipher.decrypt_and_verify(ciphertext, tag)
            return decrypted_bytes.decode('utf-8')
        except Exception as e:
            
            print(f"Decryption error for field: {e}")
            return None 

    def get_prep_value(self, value):
        """
        Converts the Python object (plain string) to a database-ready format (encrypted string).
        """
        if value is None:
            return value
        
        # Ensure value is string before encryption
        value_bytes = str(value).encode('utf-8')

        cipher = AES.new(self.key, AES.MODE_GCM)
        nonce = cipher.nonce # GCM generates a unique nonce for each encryption
        ciphertext, tag = cipher.encrypt_and_digest(value_bytes)

        # Store nonce, ciphertext, and tag as Base64 encoded JSON
        encrypted_data = {
            'nonce': base64.b64encode(nonce).decode('utf-8'),
            'ciphertext': base64.b64encode(ciphertext).decode('utf-8'),
            'tag': base64.b64encode(tag).decode('utf-8')
        }
        return base64.b64encode(json.dumps(encrypted_data).encode('utf-8')).decode('utf-8')

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        return name, path, args, kwargs

    # For lookups, we'll need to override get_prep_lookup if direct lookups are ever needed
    # but for AES-GCM, direct lookups on encrypted data are not possible.
    # For now, we'll assume lookups are done after decryption in Python.
