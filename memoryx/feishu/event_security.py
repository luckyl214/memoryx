# memoryx/feishu/event_security.py
"""
飞书事件安全：验证 Token + 签名校验 + AES 解密。

飞书事件订阅安全机制：
  1. URL Verification: 飞书发送 challenge 请求验证回调 URL
  2. Verification Token: 自定义 token 校验请求来源
  3. Event Encryption: AES-256-CBC 加密事件内容

参考：https://open.feishu.cn/document/ukTMukTMukTM/ucTM5YjL3ETO24yNlz0M
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any


def verify_challenge(payload: dict, verification_token: str) -> dict:
    """
    验证飞书 URL Verification 请求。

    飞书会发送 type=url_verification 的事件，携带 token 和 challenge。
    需要返回 {"challenge": <challenge>}。
    """
    if payload.get("type") != "url_verification":
        return {}

    token = payload.get("token")
    challenge = payload.get("challenge")

    if not token or not challenge:
        raise ValueError("missing token or challenge in url_verification")

    if token != verification_token:
        raise ValueError(f"verification token mismatch: expected {verification_token}, got {token}")

    return {"challenge": challenge}


def verify_signature(
    payload: dict,
    app_id: str,
    app_secret: str,
    timestamp: str,
    nonce: str,
    signature: str,
) -> bool:
    """
    验证飞书事件签名。

    签名算法：
      sign = HMAC-SHA256(app_secret, timestamp + nonce + app_id + event_body)

    参考：https://open.feishu.cn/document/ukTMukTMukTM/ucTM5YjL3ETO24yNlz0M#sign
    """
    event_body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    sign_str = timestamp + nonce + app_id + event_body

    expected = hmac.new(
        app_secret.encode("utf-8"),
        sign_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def decrypt_event(
    encrypted_content: str,
    app_id: str,
    app_secret: str,
    encrypt_key: str | None = None,
) -> dict:
    """
    解密飞书加密事件。

    飞书事件加密使用 AES-256-CBC。
    需要先获取 encrypt_key（通过 tenant_access_token 或配置）。

    参考：https://open.feishu.cn/document/ukTMukTMukTM/ucTM5YjL3ETO24yNlz0M#encrypt
    """
    import cryptography
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend

    # 获取 encrypt_key（实际应从飞书 API 获取或配置）
    if not encrypt_key:
        encrypt_key = os.getenv("FEISHU_ENCRYPT_KEY")

    if not encrypt_key:
        raise ValueError("FEISHU_ENCRYPT_KEY required for event decryption")

    # 解密
    key = base64.b64decode(encrypt_key)
    # 飞书加密的 IV 固定为 16 个 0
    iv = b"\x00" * 16

    encrypted_data = base64.b64decode(encrypted_content)

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted = decryptor.update(encrypted_data) + decryptor.finalize()

    # 去除 PKCS7 padding
    padding_len = decrypted[-1]
    decrypted = decrypted[:-padding_len]

    return json.loads(decrypted.decode("utf-8"))


def parse_event_request(body: bytes, app_id: str, app_secret: str) -> dict:
    """
    解析飞书事件请求（含签名验证和加密解密）。

    返回解密/验证后的事件 payload。
    """
    payload = json.loads(body.decode("utf-8"))

    # 1. URL Verification
    if payload.get("type") == "url_verification":
        return payload

    # 2. 签名验证
    header = payload.get("header", {})
    timestamp = header.get("timestamp")
    nonce = header.get("nonce")
    signature = header.get("signature")

    if timestamp and nonce and signature:
        if not verify_signature(payload, app_id, app_secret, timestamp, nonce, signature):
            raise ValueError("event signature verification failed")

    # 3. 解密（如果加密）
    event = payload.get("event", {})
    if event.get("encrypt"):
        encrypt_key = os.getenv("FEISHU_ENCRYPT_KEY")
        decrypted = decrypt_event(event["encrypt"], app_id, app_secret, encrypt_key)
        payload["event"] = decrypted

    return payload
