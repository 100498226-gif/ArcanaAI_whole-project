# Wi-Fi Network Setup — Home Office

## Network Details

### Primary Network (5 GHz — recommended for work)

- **Network name (SSID):** HorizonHome_5G
- **Password:** Maragall2024#
- **Security:** WPA3-Personal
- **Frequency:** 5 GHz
- **Channel:** Auto (typically 36 or 100)
- **Best for:** Video calls, large file transfers, development work

### Secondary Network (2.4 GHz — for IoT devices)

- **Network name (SSID):** HorizonHome_2G
- **Password:** Maragall2024#
- **Security:** WPA2-Personal
- **Frequency:** 2.4 GHz
- **Best for:** Smart home devices, printers, older phones

### Guest Network

- **Network name (SSID):** HorizonHome_Guest
- **Password:** Guest2024!
- **Access:** Internet only (no LAN access)
- **Best for:** Visitors, client laptops

---

## Router Details

- **Model:** ASUS RT-AX88U
- **Firmware version:** 3.0.0.4.386_52597 (as of October 2024)
- **Admin panel:** http://192.168.1.1
- **Admin username:** admin
- **Admin password:** (stored in 1Password — entry: "ASUS Router Admin")
- **Router MAC address:** DC:FB:48:2A:91:4C

---

## Network Topology

```
Movistar ONT (fibre) → ASUS RT-AX88U → HorizonHome_5G / _2G / _Guest
                                      → TP-Link Powerline adapter (office room)
                                      → Synology NAS (192.168.1.20, Ethernet)
```

---

## Connected Devices (static IPs)

| Device | IP | MAC |
|---|---|---|
| MacBook Pro M3 (Wi-Fi) | 192.168.1.10 | DHCP (varies) |
| Synology NAS DS223j | 192.168.1.20 | 00:11:32:AB:CD:EF |
| HP LaserJet Pro M404n | 192.168.1.30 | A0:B1:C2:D3:E4:F5 |
| Apple TV 4K | 192.168.1.40 | DHCP |

---

## Internet Service

- **Provider:** Movistar (Telefónica)
- **Plan:** Fusión Fibra 600 Mb
- **Contracted speed:** 600 Mb/s download / 300 Mb/s upload
- **Real-world speed (tested):** ~580 Mb/s down / ~290 Mb/s up
- **Contract reference:** MOV-FIB-2024-8847201

---

## Troubleshooting

### Router not responding:
1. Power cycle: unplug for 30 seconds, plug back in
2. Wait 2 minutes for full boot
3. If admin panel unreachable, reset button (hold 10 seconds) restores factory defaults

### Slow speeds:
- Switch to 5GHz network if on 2.4GHz
- Check Movistar status: https://www.movistar.es/particulares/atencion-cliente/averias/
- Run speed test at fast.com or speedtest.net
