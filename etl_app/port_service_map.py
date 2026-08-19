"""
Mapping dstport -> (service_name, service_category).

Dipakai sebagai daftar "port yang dikenal" oleh feature_engineering.py
untuk menentukan kategori APP (semua port dikenal selain DNS & WEB).
Port yang tidak terdaftar di sini otomatis dianggap tidak dikenal
(masuk kategori OTHER di feature engineering) -- BUKAN error.

Silakan tambah baris baru kapan pun sesuai kebutuhan lingkungan.
"""

# port -> (service_name, service_category)
PORT_SERVICE_MAP: dict[int, tuple[str, str]] = {
    # --- Web ---
    80:    ("HTTP", "Web Service"),
    443:   ("HTTPS", "Web Service"),
    8080:  ("HTTP Alt / Proxy", "Web Service"),
    8443:  ("HTTPS Alt", "Web Service"),

    # --- DNS ---
    53:    ("DNS", "DNS Service"),
    853:   ("DNS over TLS", "DNS Service"),
    5353:  ("mDNS", "DNS Service"),

    # --- Remote Access ---
    22:    ("SSH", "Remote Access"),
    23:    ("Telnet", "Remote Access"),
    3389:  ("RDP", "Remote Access"),
    5900:  ("VNC", "Remote Access"),
    3283:  ("Apple Remote Desktop", "Remote Access"),

    # --- Database ---
    3306:  ("MySQL", "Database"),
    5432:  ("PostgreSQL", "Database"),
    1433:  ("MS SQL Server", "Database"),
    1521:  ("Oracle DB", "Database"),
    27017: ("MongoDB", "Database"),
    6379:  ("Redis", "Database"),

    # --- Mail ---
    25:    ("SMTP", "Mail Service"),
    110:   ("POP3", "Mail Service"),
    143:   ("IMAP", "Mail Service"),
    465:   ("SMTPS", "Mail Service"),
    587:   ("SMTP Submission", "Mail Service"),
    993:   ("IMAPS", "Mail Service"),
    995:   ("POP3S", "Mail Service"),

    # --- Chat / Messaging ---
    5222:  ("XMPP", "Chat Service"),
    5223:  ("Apple Push (APNs)", "Chat Service"),
    5228:  ("Google Play Services", "Mobile/App Service"),

    # --- Voice / Video ---
    3478:  ("STUN/TURN", "Voice/Video Service"),
    19302: ("Google STUN/WebRTC", "Voice/Video Service"),
    5060:  ("SIP", "Voice/Video Service"),
    5061:  ("SIP TLS", "Voice/Video Service"),

    # --- VPN ---
    1194:  ("OpenVPN", "VPN"),
    1701:  ("L2TP", "VPN"),
    1723:  ("PPTP", "VPN"),
    500:   ("IPsec/IKE", "VPN"),
    4500:  ("IPsec NAT-T", "VPN"),
    51820: ("WireGuard", "VPN"),

    # --- Infrastruktur / Manajemen Jaringan ---
    123:   ("NTP", "Infrastructure Service"),
    67:    ("DHCP Server", "Infrastructure Service"),
    68:    ("DHCP Client", "Infrastructure Service"),
    161:   ("SNMP", "Network Management"),
    162:   ("SNMP Trap", "Network Management"),
    2002:  ("Cisco SCCP", "Network Management"),
    514:   ("Syslog", "Network Management"),

    # --- Industrial / OT ---
    61850: ("IEC 61850 (MMS)", "Industrial/OT"),
    502:   ("Modbus TCP", "Industrial/OT"),
    20000: ("DNP3", "Industrial/OT"),

    # --- OS / Update Service ---
    7680:  ("Windows Delivery Optimization", "OS/Update Service"),

    # --- File Sharing ---
    20:    ("FTP Data", "File Sharing"),
    21:    ("FTP Control", "File Sharing"),
    445:   ("SMB", "File Sharing"),
    2049:  ("NFS", "File Sharing"),
    873:   ("rsync", "File Sharing"),

    # --- Direktori / Autentikasi ---
    88:    ("Kerberos", "Directory/Auth Service"),
    389:   ("LDAP", "Directory/Auth Service"),
    636:   ("LDAPS", "Directory/Auth Service"),
    1812:  ("RADIUS Auth", "Directory/Auth Service"),
    1813:  ("RADIUS Acct", "Directory/Auth Service"),
}


def map_port(port: int | None) -> tuple[str, str]:
    """Petakan satu dstport ke (service_name, service_category).
    Port None/NaN atau tidak dikenal -> ("Unknown Service", "Unknown Category").

    Catatan: fungsi ini sekadar helper lookup nama service detail (kalau
    dibutuhkan untuk keperluan lain/debug). Feature Engineering sendiri
    TIDAK memakai nama service detail ini -- lihat feature_engineering.py,
    yang hanya mengelompokkan port jadi 4 kategori (dns/web/app/other)."""
    if port is None:
        return ("Unknown Service", "Unknown Category")
    try:
        p = int(port)
    except (ValueError, TypeError):
        return ("Unknown Service", "Unknown Category")
    return PORT_SERVICE_MAP.get(p, ("Unknown Service", "Unknown Category"))
