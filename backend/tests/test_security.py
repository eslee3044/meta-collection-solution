from app.security import create_token, decode_token, decrypt_json, encrypt_json, hash_password, verify_password


def test_password_hash_and_token_round_trip():
    encoded = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong", encoded)
    assert decode_token(create_token(42)) == 42


def test_secret_encryption_round_trip():
    value = {"password": "not-plain-text", "private_key": "key material"}
    encrypted = encrypt_json(value)
    assert "not-plain-text" not in encrypted
    assert decrypt_json(encrypted) == value

