#!/usr/bin/env python3
"""
DuckDNS Dynamic IP Auto-Updater
Tự động phát hiện IP Public và cập nhật lên domain DuckDNS
"""

import os
import sys
import time
import urllib.request
import logging
from pathlib import Path
from dotenv import load_dotenv

# Reconfigure stdout for utf-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# Load environment
base_dir = Path(__file__).resolve().parent.parent
load_dotenv(base_dir / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("duckdns_updater")

def get_public_ip() -> str:
    """Lấy địa chỉ Public IPv4 hiện tại"""
    services = [
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
        "https://icanhazip.com",
        "https://checkip.amazonaws.com"
    ]
    for url in services:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                ip = resp.read().decode("utf-8").strip()
                if ip and len(ip.split(".")) == 4:
                    return ip
        except Exception:
            continue
    raise RuntimeError("Không thể lấy Public IP từ các dịch vụ kiểm tra IP.")

def update_duckdns(domain: str, token: str, ip: str) -> bool:
    """Gọi API DuckDNS để cập nhật IP cho domain"""
    # Clean domain (e.g. truyendichviet.duckdns.org -> truyendichviet)
    clean_domain = domain.replace(".duckdns.org", "").strip()
    url = f"https://www.duckdns.org/update?domains={clean_domain}&token={token}&ip={ip}"
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TruyenDichViet-DuckDNS-Updater/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8").strip()
            if "OK" in body:
                logger.info(f"✓ Cập nhật DuckDNS thành công: {clean_domain}.duckdns.org -> {ip}")
                return True
            else:
                logger.error(f"✕ Cập nhật DuckDNS thất bại: Phản hồi từ server: '{body}'")
                return False
    except Exception as e:
        logger.error(f"✕ Lỗi kết nối đến DuckDNS: {e}")
        return False

def main():
    domain = os.getenv("DUCKDNS_DOMAIN", "truyendichviet")
    token = os.getenv("DUCKDNS_TOKEN", "")

    if not token:
        logger.warning("DUCKDNS_TOKEN chưa được cấu hình trong file .env")
        logger.info("Hướng dẫn: Lấy Token tại https://www.duckdns.org và thêm vào file .env:")
        logger.info("DUCKDNS_DOMAIN=truyendichviet")
        logger.info("DUCKDNS_TOKEN=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
        
        # Vẫn in IP public hiện tại để hỗ trợ người dùng
        try:
            ip = get_public_ip()
            logger.info(f"Địa chỉ Public IP hiện tại của bạn là: {ip}")
        except Exception as e:
            logger.error(f"Lỗi: {e}")
        return

    try:
        ip = get_public_ip()
        logger.info(f"Đã phát hiện Public IP: {ip}")
        update_duckdns(domain=domain, token=token, ip=ip)
    except Exception as e:
        logger.error(f"Lỗi quy trình DuckDNS: {e}")

if __name__ == "__main__":
    main()
