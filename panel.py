#!/usr/bin/env python3
"""
NEXUS PANEL - Advanced VPS Management Panel
Run: python3 panel.py
Access: http://YOUR_IP:5555
Login: admin / admin
"""

from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit
import psutil, subprocess, os, json, time, platform, socket, threading, shutil, glob, re
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = 'nexus-panel-secret-key-change-me'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ─── Config Store ────────────────────────────────────────────────────────────
CONFIG_FILE = os.path.expanduser("~/.nexus_panel_config.json")

DEFAULT_CONFIG = {
    "panel_name": "NEXUS",
    "theme": "dark",
    "accent": "#00d4ff",
    "accent2": "#7c3aed",
    "bg_color": "#080b14",
    "card_color": "#0d1117",
    "text_color": "#e2e8f0",
    "font": "JetBrains Mono",
    "border_radius": "12px",
    "animations": True,
    "glass_effect": True,
    "particles": True,
    "glow_effect": True,
    "sidebar_style": "icons+text",
    "card_style": "3d",
    "chart_style": "gradient",
    "refresh_rate": 2,
    "saved_commands": [
        {"name": "System Info", "cmd": "uname -a"},
        {"name": "Disk Usage", "cmd": "df -h"},
        {"name": "Running Processes", "cmd": "ps aux --sort=-%cpu | head -20"},
        {"name": "Network Stats", "cmd": "ss -tulpn"},
        {"name": "Memory Info", "cmd": "free -h"},
        {"name": "CPU Info", "cmd": "lscpu"},
        {"name": "Uptime", "cmd": "uptime -p"},
        {"name": "Who is logged in", "cmd": "who"},
        {"name": "Last logins", "cmd": "last -n 10"},
        {"name": "Open ports", "cmd": "netstat -tlnp 2>/dev/null || ss -tlnp"},
    ],
    "blocked_cmds": ["rm -rf /", "mkfs", "dd if=/dev/zero of=/dev/"],
    "username": "admin",
    "password": "admin",
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
                # merge with defaults for any missing keys
                for k, v in DEFAULT_CONFIG.items():
                    if k not in cfg:
                        cfg[k] = v
                return cfg
        except:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)

config = load_config()

# ─── Auth ────────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect('/')
        return f(*args, **kwargs)
    return decorated

# ─── System Stats ─────────────────────────────────────────────────────────────
def get_full_stats():
    cpu = psutil.cpu_percent(interval=0.1)
    cpu_per_core = psutil.cpu_percent(interval=0.1, percpu=True)
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk_parts = []
    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disk_parts.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": usage.percent
            })
        except: pass
    net = psutil.net_io_counters()
    net_ifaces = {}
    for iface, stats in psutil.net_if_stats().items():
        addrs = psutil.net_if_addrs().get(iface, [])
        ipv4 = next((a.address for a in addrs if a.family == socket.AF_INET), "N/A")
        net_ifaces[iface] = {"speed": stats.speed, "isup": stats.isup, "ip": ipv4}
    temps = {}
    try:
        t = psutil.sensors_temperatures()
        if t:
            for k, v in t.items():
                temps[k] = [{"label": s.label or k, "current": s.current, "high": s.high} for s in v]
    except: pass
    battery = None
    try:
        b = psutil.sensors_battery()
        if b:
            battery = {"percent": b.percent, "power_plugged": b.power_plugged}
    except: pass
    procs = []
    for p in sorted(psutil.process_iter(['pid','name','cpu_percent','memory_percent','status','username']),
                    key=lambda x: x.info.get('cpu_percent') or 0, reverse=True)[:20]:
        try:
            procs.append(p.info)
        except: pass
    boot_time = psutil.boot_time()
    uptime_sec = time.time() - boot_time
    uptime_str = str(timedelta(seconds=int(uptime_sec)))
    return {
        "ts": datetime.now().strftime("%H:%M:%S"),
        "cpu": cpu,
        "cpu_cores": len(cpu_per_core),
        "cpu_per_core": cpu_per_core,
        "cpu_freq": psutil.cpu_freq()._asdict() if psutil.cpu_freq() else {},
        "mem_total": mem.total,
        "mem_used": mem.used,
        "mem_free": mem.available,
        "mem_percent": mem.percent,
        "mem_cached": mem.cached if hasattr(mem,'cached') else 0,
        "swap_total": swap.total,
        "swap_used": swap.used,
        "swap_percent": swap.percent,
        "disks": disk_parts,
        "net_sent": net.bytes_sent,
        "net_recv": net.bytes_recv,
        "net_pkts_sent": net.packets_sent,
        "net_pkts_recv": net.packets_recv,
        "net_ifaces": net_ifaces,
        "temps": temps,
        "battery": battery,
        "processes": procs,
        "uptime": uptime_str,
        "boot_time": datetime.fromtimestamp(boot_time).strftime("%Y-%m-%d %H:%M:%S"),
        "hostname": socket.gethostname(),
        "os": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version()[:80],
        "arch": platform.machine(),
        "python": platform.python_version(),
        "cpu_model": platform.processor() or "Unknown",
        "load_avg": list(os.getloadavg()) if hasattr(os,'getloadavg') else [0,0,0],
        "users": [u._asdict() for u in psutil.users()],
    }

def fmt_bytes(b):
    for u in ['B','KB','MB','GB','TB']:
        if b < 1024: return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} PB"

# ─── Background broadcaster ──────────────────────────────────────────────────
def stats_broadcaster():
    while True:
        try:
            stats = get_full_stats()
            socketio.emit('stats_update', stats)
        except Exception as e:
            pass
        time.sleep(config.get('refresh_rate', 2))

threading.Thread(target=stats_broadcaster, daemon=True).start()

# ─── Routes ──────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    if session.get('logged_in'):
        return redirect('/panel')
    return render_template_string(LOGIN_HTML, config=config)

@app.route('/login', methods=['POST'])
def login():
    cfg = load_config()
    u = request.form.get('username','')
    p = request.form.get('password','')
    if u == cfg['username'] and p == cfg['password']:
        session['logged_in'] = True
        session['user'] = u
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Invalid credentials"}), 401

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

@app.route('/panel')
@login_required
def panel():
    global config
    config = load_config()
    return render_template_string(PANEL_HTML, config=config)

@app.route('/api/stats')
@login_required
def api_stats():
    return jsonify(get_full_stats())

@app.route('/api/exec', methods=['POST'])
@login_required
def api_exec():
    cmd = request.json.get('cmd','').strip()
    if not cmd:
        return jsonify({"output": "", "error": "No command"})
    cfg = load_config()
    for blocked in cfg.get('blocked_cmds', []):
        if blocked in cmd:
            return jsonify({"output": "", "error": f"Command blocked for safety: {blocked}"})
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30,
            cwd=os.path.expanduser("~")
        )
        out = result.stdout or ""
        err = result.stderr or ""
        return jsonify({"output": out, "error": err, "returncode": result.returncode})
    except subprocess.TimeoutExpired:
        return jsonify({"output": "", "error": "Command timed out (30s limit)"})
    except Exception as e:
        return jsonify({"output": "", "error": str(e)})

@app.route('/api/config', methods=['GET','POST'])
@login_required
def api_config():
    global config
    if request.method == 'POST':
        updates = request.json or {}
        config = load_config()
        config.update(updates)
        save_config(config)
        return jsonify({"ok": True})
    return jsonify(load_config())

@app.route('/api/files', methods=['GET'])
@login_required
def api_files():
    path = request.args.get('path', os.path.expanduser('~'))
    try:
        entries = []
        for item in sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name)):
            try:
                stat = item.stat()
                entries.append({
                    "name": item.name,
                    "path": item.path,
                    "is_dir": item.is_dir(),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    "perms": oct(stat.st_mode)[-3:]
                })
            except: pass
        return jsonify({"ok": True, "path": path, "entries": entries, "parent": str(os.path.dirname(path))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route('/api/file/read', methods=['GET'])
@login_required
def api_file_read():
    path = request.args.get('path','')
    try:
        with open(path, 'r', errors='replace') as f:
            return jsonify({"ok": True, "content": f.read(100000)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route('/api/file/write', methods=['POST'])
@login_required
def api_file_write():
    data = request.json or {}
    try:
        with open(data['path'], 'w') as f:
            f.write(data.get('content',''))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route('/api/services', methods=['GET'])
@login_required
def api_services():
    try:
        result = subprocess.run("systemctl list-units --type=service --no-pager --plain 2>/dev/null | head -40",
                                shell=True, capture_output=True, text=True)
        return jsonify({"ok": True, "output": result.stdout})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route('/api/service/<action>/<name>', methods=['POST'])
@login_required
def api_service_action(action, name):
    if action not in ['start','stop','restart','status']:
        return jsonify({"ok": False, "error": "Invalid action"})
    try:
        result = subprocess.run(f"systemctl {action} {name} 2>&1",
                                shell=True, capture_output=True, text=True)
        return jsonify({"ok": True, "output": result.stdout + result.stderr})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route('/api/cron', methods=['GET'])
@login_required
def api_cron():
    try:
        result = subprocess.run("crontab -l 2>/dev/null", shell=True, capture_output=True, text=True)
        return jsonify({"ok": True, "output": result.stdout or "(no crontab)"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route('/api/logs/<name>', methods=['GET'])
@login_required
def api_logs(name):
    log_files = {
        "syslog": "/var/log/syslog",
        "auth": "/var/log/auth.log",
        "kern": "/var/log/kern.log",
        "nginx": "/var/log/nginx/access.log",
        "apache": "/var/log/apache2/access.log",
        "mysql": "/var/log/mysql/error.log",
    }
    path = log_files.get(name)
    if not path or not os.path.exists(path):
        try:
            result = subprocess.run(f"journalctl -n 100 --no-pager 2>/dev/null",
                                    shell=True, capture_output=True, text=True)
            return jsonify({"ok": True, "content": result.stdout})
        except:
            return jsonify({"ok": False, "error": "Log not found"})
    try:
        result = subprocess.run(f"tail -n 100 {path}", shell=True, capture_output=True, text=True)
        return jsonify({"ok": True, "content": result.stdout})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

# ─────────────────────────────────────────────────────────────────────────────
# HTML TEMPLATES
# ─────────────────────────────────────────────────────────────────────────────

LOGIN_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ config.panel_name }} Panel - Login</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Orbitron:wght@400;700;900&display=swap" rel="stylesheet">
<style>
:root {
  --accent: {{ config.accent }};
  --accent2: {{ config.accent2 }};
  --bg: {{ config.bg_color }};
  --card: {{ config.card_color }};
  --text: {{ config.text_color }};
}
*{margin:0;padding:0;box-sizing:border-box;}
body{
  min-height:100vh;background:var(--bg);
  font-family:'JetBrains Mono',monospace;
  display:flex;align-items:center;justify-content:center;
  overflow:hidden;color:var(--text);
}
canvas#bg{position:fixed;top:0;left:0;width:100%;height:100%;z-index:0;}
.login-wrap{position:relative;z-index:10;width:420px;}
.logo{text-align:center;margin-bottom:40px;}
.logo h1{
  font-family:'Orbitron',monospace;font-size:3rem;font-weight:900;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  text-shadow:none;letter-spacing:4px;
}
.logo p{color:#666;font-size:.75rem;letter-spacing:3px;margin-top:4px;}
.card{
  background:rgba(13,17,23,.85);backdrop-filter:blur(20px);
  border:1px solid rgba(0,212,255,.15);border-radius:20px;
  padding:40px;box-shadow:0 0 60px rgba(0,212,255,.08),0 20px 60px rgba(0,0,0,.5);
}
.field{margin-bottom:24px;}
.field label{display:block;font-size:.7rem;letter-spacing:2px;color:var(--accent);margin-bottom:8px;text-transform:uppercase;}
.field input{
  width:100%;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.1);
  border-radius:10px;padding:14px 16px;color:var(--text);font-family:inherit;
  font-size:.9rem;transition:all .3s;outline:none;
}
.field input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(0,212,255,.1);}
.btn-login{
  width:100%;background:linear-gradient(135deg,var(--accent),var(--accent2));
  border:none;border-radius:10px;padding:15px;color:#fff;
  font-family:'Orbitron',monospace;font-size:.85rem;font-weight:700;
  letter-spacing:2px;cursor:pointer;transition:all .3s;text-transform:uppercase;
  position:relative;overflow:hidden;
}
.btn-login:hover{transform:translateY(-2px);box-shadow:0 10px 30px rgba(0,212,255,.3);}
.btn-login:active{transform:translateY(0);}
.error{
  background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);
  border-radius:8px;padding:10px 14px;color:#f87171;font-size:.8rem;
  margin-bottom:20px;display:none;
}
.scan-line{
  position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,transparent,var(--accent),transparent);
  animation:scan 3s linear infinite;
}
@keyframes scan{0%{top:0}100%{top:100%}}
.corner{position:absolute;width:12px;height:12px;border-color:var(--accent);border-style:solid;}
.corner.tl{top:-1px;left:-1px;border-width:2px 0 0 2px;border-radius:4px 0 0 0;}
.corner.tr{top:-1px;right:-1px;border-width:2px 2px 0 0;border-radius:0 4px 0 0;}
.corner.bl{bottom:-1px;left:-1px;border-width:0 0 2px 2px;border-radius:0 0 0 4px;}
.corner.br{bottom:-1px;right:-1px;border-width:0 2px 2px 0;border-radius:0 0 4px 0;}
.status-dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--accent);margin-right:8px;animation:pulse 2s infinite;}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(1.3)}}
</style>
</head>
<body>
<canvas id="bg"></canvas>
<div class="login-wrap">
  <div class="logo">
    <h1>{{ config.panel_name }}</h1>
    <p><span class="status-dot"></span>VPS CONTROL PANEL</p>
  </div>
  <div class="card" style="position:relative;">
    <div class="scan-line"></div>
    <div class="corner tl"></div><div class="corner tr"></div>
    <div class="corner bl"></div><div class="corner br"></div>
    <div class="error" id="err"></div>
    <div class="field">
      <label>Username</label>
      <input type="text" id="uname" placeholder="Enter username" autocomplete="off">
    </div>
    <div class="field">
      <label>Password</label>
      <input type="password" id="pass" placeholder="Enter password">
    </div>
    <button class="btn-login" onclick="doLogin()">AUTHENTICATE</button>
  </div>
</div>
<script>
const C=document.getElementById('bg'),ctx=C.getContext('2d');
let W,H,particles=[];
function resize(){W=C.width=innerWidth;H=C.height=innerHeight;}
resize();window.onresize=resize;
for(let i=0;i<120;i++)particles.push({x:Math.random()*3000,y:Math.random()*3000,vx:(Math.random()-.5)*.3,vy:(Math.random()-.5)*.3,r:Math.random()*1.5+.5,a:Math.random()});
function draw(){
  ctx.clearRect(0,0,W,H);
  particles.forEach(p=>{
    p.x+=p.vx;p.y+=p.vy;
    if(p.x<0)p.x=W;if(p.x>W)p.x=0;
    if(p.y<0)p.y=H;if(p.y>H)p.y=0;
    ctx.beginPath();ctx.arc(p.x,p.y,p.r,0,Math.PI*2);
    ctx.fillStyle=`rgba(0,212,255,${p.a*.4})`;ctx.fill();
  });
  particles.forEach((p,i)=>{
    particles.slice(i+1).forEach(q=>{
      const d=Math.hypot(p.x-q.x,p.y-q.y);
      if(d<120){ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(q.x,q.y);
      ctx.strokeStyle=`rgba(0,212,255,${(1-d/120)*.15})`;ctx.lineWidth=.5;ctx.stroke();}
    });
  });
  requestAnimationFrame(draw);
}
draw();
async function doLogin(){
  const u=document.getElementById('uname').value;
  const p=document.getElementById('pass').value;
  const r=await fetch('/login',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:`username=${encodeURIComponent(u)}&password=${encodeURIComponent(p)}`});
  const d=await r.json();
  if(d.ok){window.location='/panel';}
  else{const e=document.getElementById('err');e.textContent=d.error;e.style.display='block';}
}
document.addEventListener('keydown',e=>{if(e.key==='Enter')doLogin();});
</script>
</body></html>"""

# ─── Panel HTML (massive) ─────────────────────────────────────────────────────
PANEL_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ config.panel_name }} Panel</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Orbitron:wght@400;700;900&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
:root {
  --accent: {{ config.accent }};
  --accent2: {{ config.accent2 }};
  --bg: {{ config.bg_color }};
  --card: {{ config.card_color }};
  --text: {{ config.text_color }};
  --border: rgba(255,255,255,.07);
  --sidebar-w: 240px;
  --radius: {{ config.border_radius }};
}
*{margin:0;padding:0;box-sizing:border-box;scrollbar-width:thin;scrollbar-color:var(--accent) transparent;}
::-webkit-scrollbar{width:4px;height:4px;}
::-webkit-scrollbar-thumb{background:var(--accent);border-radius:2px;}
body{background:var(--bg);color:var(--text);font-family:'JetBrains Mono',monospace;display:flex;min-height:100vh;overflow:hidden;}

/* SIDEBAR */
.sidebar{
  width:var(--sidebar-w);min-height:100vh;background:var(--card);
  border-right:1px solid var(--border);display:flex;flex-direction:column;
  position:fixed;left:0;top:0;bottom:0;z-index:100;
  transition:width .3s;
}
.sidebar.collapsed{width:64px;}
.sidebar-logo{
  padding:20px 16px;border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:12px;
}
.sidebar-logo h2{font-family:'Orbitron',monospace;font-size:1.1rem;font-weight:900;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  white-space:nowrap;}
.logo-icon{width:32px;height:32px;background:linear-gradient(135deg,var(--accent),var(--accent2));
  border-radius:8px;display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:1rem;}
.nav{flex:1;padding:12px 8px;overflow-y:auto;}
.nav-item{
  display:flex;align-items:center;gap:12px;padding:10px 12px;
  border-radius:10px;cursor:pointer;transition:all .2s;margin-bottom:2px;
  color:#94a3b8;font-size:.78rem;letter-spacing:.5px;white-space:nowrap;
}
.nav-item:hover{background:rgba(255,255,255,.05);color:var(--text);}
.nav-item.active{background:linear-gradient(135deg,rgba(0,212,255,.15),rgba(124,58,237,.15));color:var(--accent);border:1px solid rgba(0,212,255,.2);}
.nav-icon{font-size:1.1rem;flex-shrink:0;width:20px;text-align:center;}
.nav-label{overflow:hidden;white-space:nowrap;}
.sidebar-footer{padding:12px 8px;border-top:1px solid var(--border);}
.user-badge{
  display:flex;align-items:center;gap:10px;padding:10px 12px;
  background:rgba(255,255,255,.03);border-radius:10px;
}
.user-avatar{width:28px;height:28px;background:linear-gradient(135deg,var(--accent),var(--accent2));
  border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:.8rem;flex-shrink:0;}
.user-name{font-size:.75rem;white-space:nowrap;}
.collapse-btn{position:absolute;right:-12px;top:50%;transform:translateY(-50%);
  width:24px;height:24px;background:var(--card);border:1px solid var(--border);
  border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;
  font-size:.7rem;color:var(--accent);}

/* MAIN */
.main{margin-left:var(--sidebar-w);flex:1;display:flex;flex-direction:column;min-height:100vh;transition:margin-left .3s;}
.main.collapsed{margin-left:64px;}
.topbar{
  height:56px;background:var(--card);border-bottom:1px solid var(--border);
  display:flex;align-items:center;padding:0 24px;gap:16px;
  position:sticky;top:0;z-index:50;
}
.topbar-title{font-family:'Orbitron',monospace;font-size:.9rem;font-weight:700;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.topbar-right{margin-left:auto;display:flex;align-items:center;gap:12px;}
.live-badge{
  display:flex;align-items:center;gap:6px;font-size:.7rem;color:#4ade80;
  background:rgba(74,222,128,.1);border:1px solid rgba(74,222,128,.2);
  padding:4px 10px;border-radius:20px;
}
.live-dot{width:6px;height:6px;border-radius:50%;background:#4ade80;animation:pulse 2s infinite;}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.logout-btn{padding:6px 14px;background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.2);
  color:#f87171;border-radius:8px;cursor:pointer;font-size:.72rem;font-family:inherit;transition:all .2s;}
.logout-btn:hover{background:rgba(239,68,68,.2);}

/* CONTENT */
.content{flex:1;padding:24px;overflow-y:auto;height:calc(100vh - 56px);}
.tab-pane{display:none;animation:fadeIn .3s;}
.tab-pane.active{display:block;}
@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}

/* CARDS */
.grid{display:grid;gap:16px;}
.g2{grid-template-columns:repeat(2,1fr);}
.g3{grid-template-columns:repeat(3,1fr);}
.g4{grid-template-columns:repeat(4,1fr);}
.g6{grid-template-columns:repeat(6,1fr);}
@media(max-width:1200px){.g4{grid-template-columns:repeat(2,1fr)}.g6{grid-template-columns:repeat(3,1fr)}}
@media(max-width:800px){.g2,.g3,.g4,.g6{grid-template-columns:1fr}}
.card{
  background:var(--card);border:1px solid var(--border);
  border-radius:var(--radius);padding:20px;
  transition:transform .2s,box-shadow .2s;position:relative;overflow:hidden;
}
.card:hover{transform:translateY(-2px);box-shadow:0 8px 32px rgba(0,0,0,.3);}
.card-glow::before{
  content:'';position:absolute;top:0;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,var(--accent),transparent);
}
.card-title{font-size:.65rem;letter-spacing:2px;color:#94a3b8;text-transform:uppercase;margin-bottom:12px;display:flex;align-items:center;gap:8px;}
.stat-value{font-size:2rem;font-weight:700;font-family:'Orbitron',monospace;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.stat-sub{font-size:.72rem;color:#64748b;margin-top:4px;}

/* PROGRESS BAR */
.progress-wrap{margin-top:12px;}
.progress-label{display:flex;justify-content:space-between;font-size:.7rem;color:#94a3b8;margin-bottom:6px;}
.progress-bar{height:6px;background:rgba(255,255,255,.06);border-radius:3px;overflow:hidden;}
.progress-fill{height:100%;border-radius:3px;transition:width .8s cubic-bezier(.4,0,.2,1);
  background:linear-gradient(90deg,var(--accent),var(--accent2));}
.progress-fill.warn{background:linear-gradient(90deg,#f59e0b,#ef4444);}
.progress-fill.danger{background:linear-gradient(90deg,#ef4444,#dc2626);}

/* TERMINAL */
.terminal{
  background:#050810;border:1px solid rgba(0,212,255,.15);
  border-radius:var(--radius);overflow:hidden;
}
.term-toolbar{
  background:#0a0e1a;padding:10px 16px;border-bottom:1px solid rgba(0,212,255,.1);
  display:flex;align-items:center;gap:10px;
}
.term-dot{width:12px;height:12px;border-radius:50%;}
.term-output{
  height:420px;overflow-y:auto;padding:16px;font-size:.8rem;
  line-height:1.7;color:#a8d8a8;
}
.term-output .line{margin-bottom:2px;}
.term-output .line.err{color:#f87171;}
.term-output .line.cmd{color:var(--accent);}
.term-output .line.sys{color:#64748b;}
.term-input-wrap{
  display:flex;align-items:center;padding:10px 16px;
  border-top:1px solid rgba(0,212,255,.1);background:#050810;gap:8px;
}
.term-prompt{color:var(--accent);font-size:.8rem;white-space:nowrap;}
.term-input{
  flex:1;background:transparent;border:none;outline:none;
  color:#a8d8a8;font-family:'JetBrains Mono',monospace;font-size:.8rem;
}
.btn{
  padding:8px 16px;background:linear-gradient(135deg,var(--accent),var(--accent2));
  border:none;border-radius:8px;color:#fff;font-family:inherit;
  font-size:.75rem;cursor:pointer;transition:all .2s;letter-spacing:.5px;
}
.btn:hover{opacity:.85;transform:translateY(-1px);}
.btn.secondary{background:rgba(255,255,255,.06);border:1px solid var(--border);color:var(--text);}
.btn.danger{background:rgba(239,68,68,.2);border:1px solid rgba(239,68,68,.3);color:#f87171;}
.btn.success{background:rgba(74,222,128,.15);border:1px solid rgba(74,222,128,.25);color:#4ade80;}

/* SAVED COMMANDS */
.cmd-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;margin-top:12px;}
.cmd-chip{
  padding:8px 12px;background:rgba(255,255,255,.04);border:1px solid var(--border);
  border-radius:8px;cursor:pointer;font-size:.72rem;transition:all .2s;display:flex;
  align-items:center;justify-content:space-between;gap:8px;
}
.cmd-chip:hover{border-color:var(--accent);color:var(--accent);background:rgba(0,212,255,.05);}
.cmd-chip-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}

/* TABLE */
table{width:100%;border-collapse:collapse;font-size:.75rem;}
th{padding:10px 12px;text-align:left;color:#64748b;border-bottom:1px solid var(--border);font-weight:500;letter-spacing:1px;font-size:.65rem;text-transform:uppercase;}
td{padding:10px 12px;border-bottom:1px solid rgba(255,255,255,.03);color:#cbd5e1;}
tr:hover td{background:rgba(255,255,255,.02);}
.badge{
  display:inline-flex;align-items:center;padding:2px 8px;border-radius:20px;font-size:.65rem;
}
.badge.green{background:rgba(74,222,128,.1);color:#4ade80;border:1px solid rgba(74,222,128,.2);}
.badge.red{background:rgba(239,68,68,.1);color:#f87171;border:1px solid rgba(239,68,68,.2);}
.badge.yellow{background:rgba(251,191,36,.1);color:#fbbf24;border:1px solid rgba(251,191,36,.2);}
.badge.blue{background:rgba(96,165,250,.1);color:#60a5fa;border:1px solid rgba(96,165,250,.2);}

/* SETTINGS */
.settings-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;}
.setting-row{display:flex;align-items:center;justify-content:space-between;padding:12px 0;border-bottom:1px solid var(--border);}
.setting-row:last-child{border-bottom:none;}
.setting-label{font-size:.78rem;color:var(--text);}
.setting-desc{font-size:.65rem;color:#64748b;margin-top:2px;}
input[type="color"]{width:40px;height:28px;border:none;border-radius:6px;cursor:pointer;background:transparent;padding:0;}
input[type="range"]{accent-color:var(--accent);}
input[type="text"],input[type="number"],select,textarea{
  background:rgba(255,255,255,.04);border:1px solid var(--border);
  border-radius:8px;padding:8px 12px;color:var(--text);
  font-family:inherit;font-size:.78rem;outline:none;transition:border-color .2s;
}
input[type="text"]:focus,select:focus,textarea:focus{border-color:var(--accent);}
select option{background:var(--card);}
.toggle{position:relative;width:44px;height:24px;}
.toggle input{opacity:0;width:0;height:0;}
.toggle-slider{
  position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;
  background:rgba(255,255,255,.1);border-radius:12px;transition:.3s;
}
.toggle-slider:before{
  content:'';position:absolute;height:18px;width:18px;left:3px;bottom:3px;
  background:#fff;border-radius:50%;transition:.3s;
}
.toggle input:checked+.toggle-slider{background:var(--accent);}
.toggle input:checked+.toggle-slider:before{transform:translateX(20px);}

/* CHARTS */
.chart-wrap{position:relative;height:200px;}
.section-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;}
.section-title{font-family:'Orbitron',monospace;font-size:.85rem;color:var(--accent);}
.divider{height:1px;background:var(--border);margin:20px 0;}

/* FILE MANAGER */
.file-toolbar{display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap;}
.path-bar{flex:1;background:rgba(255,255,255,.04);border:1px solid var(--border);
  border-radius:8px;padding:6px 12px;font-size:.75rem;color:#94a3b8;min-width:200px;}
.file-table td .icon{margin-right:6px;}

/* NOTIFICATIONS */
.toast-wrap{position:fixed;bottom:24px;right:24px;z-index:9999;display:flex;flex-direction:column;gap:8px;}
.toast{
  background:var(--card);border:1px solid var(--border);border-radius:10px;
  padding:12px 16px;font-size:.78rem;min-width:240px;max-width:320px;
  box-shadow:0 8px 32px rgba(0,0,0,.4);animation:slideIn .3s;display:flex;align-items:center;gap:10px;
}
.toast.success{border-left:3px solid #4ade80;}
.toast.error{border-left:3px solid #f87171;}
.toast.info{border-left:3px solid var(--accent);}
@keyframes slideIn{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}

/* LOADING */
.spinner{width:20px;height:20px;border:2px solid rgba(0,212,255,.2);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite;display:inline-block;}
@keyframes spin{to{transform:rotate(360deg)}}

/* WIDGET GRID (gauge-like) */
.gauge-wrap{display:flex;align-items:center;justify-content:center;flex-direction:column;padding:10px 0;}
.mini-stat{text-align:center;}
.mini-stat .val{font-size:1.4rem;font-weight:700;font-family:'Orbitron',monospace;color:var(--accent);}
.mini-stat .lbl{font-size:.6rem;color:#64748b;letter-spacing:1px;text-transform:uppercase;}
.tag{display:inline-flex;align-items:center;padding:2px 8px;background:rgba(0,212,255,.08);
  border:1px solid rgba(0,212,255,.15);border-radius:4px;font-size:.65rem;color:var(--accent);margin:2px;}
</style>
</head>
<body>

<!-- SIDEBAR -->
<div class="sidebar" id="sidebar">
  <div class="sidebar-logo">
    <div class="logo-icon">⚡</div>
    <h2 id="panel-name-logo">{{ config.panel_name }}</h2>
  </div>
  <nav class="nav" id="nav">
    <div class="nav-item active" onclick="showTab('dashboard')">
      <span class="nav-icon">📊</span><span class="nav-label">Dashboard</span>
    </div>
    <div class="nav-item" onclick="showTab('terminal')">
      <span class="nav-icon">💻</span><span class="nav-label">Terminal</span>
    </div>
    <div class="nav-item" onclick="showTab('processes')">
      <span class="nav-icon">⚙️</span><span class="nav-label">Processes</span>
    </div>
    <div class="nav-item" onclick="showTab('network')">
      <span class="nav-icon">🌐</span><span class="nav-label">Network</span>
    </div>
    <div class="nav-item" onclick="showTab('files')">
      <span class="nav-icon">📁</span><span class="nav-label">File Manager</span>
    </div>
    <div class="nav-item" onclick="showTab('services')">
      <span class="nav-icon">🔧</span><span class="nav-label">Services</span>
    </div>
    <div class="nav-item" onclick="showTab('logs')">
      <span class="nav-icon">📋</span><span class="nav-label">Logs</span>
    </div>
    <div class="nav-item" onclick="showTab('cron')">
      <span class="nav-icon">⏰</span><span class="nav-label">Cron Jobs</span>
    </div>
    <div class="nav-item" onclick="showTab('settings')">
      <span class="nav-icon">🎨</span><span class="nav-label">Settings</span>
    </div>
  </nav>
  <div class="sidebar-footer">
    <div class="user-badge">
      <div class="user-avatar">👤</div>
      <div>
        <div class="user-name" style="font-size:.75rem">admin</div>
        <div style="font-size:.6rem;color:#64748b">Administrator</div>
      </div>
    </div>
  </div>
</div>

<!-- MAIN -->
<div class="main" id="main">
  <div class="topbar">
    <button onclick="toggleSidebar()" style="background:none;border:none;color:#94a3b8;cursor:pointer;font-size:1.2rem;padding:4px;">☰</button>
    <span class="topbar-title" id="topbar-title">DASHBOARD</span>
    <div class="topbar-right">
      <div class="live-badge"><div class="live-dot"></div>LIVE</div>
      <span id="topbar-time" style="font-size:.72rem;color:#64748b;"></span>
      <a href="/logout" class="logout-btn">LOGOUT</a>
    </div>
  </div>

  <div class="content">

    <!-- ═══ DASHBOARD ═══ -->
    <div class="tab-pane active" id="tab-dashboard">
      <!-- Row 1: key stats -->
      <div class="grid g4" style="margin-bottom:16px;">
        <div class="card card-glow">
          <div class="card-title">🖥️ CPU Usage</div>
          <div class="stat-value" id="cpu-val">0%</div>
          <div class="stat-sub" id="cpu-model">Loading...</div>
          <div class="progress-wrap">
            <div class="progress-bar"><div class="progress-fill" id="cpu-bar" style="width:0%"></div></div>
          </div>
        </div>
        <div class="card card-glow">
          <div class="card-title">🧠 Memory</div>
          <div class="stat-value" id="mem-val">0%</div>
          <div class="stat-sub" id="mem-sub">Loading...</div>
          <div class="progress-wrap">
            <div class="progress-bar"><div class="progress-fill" id="mem-bar" style="width:0%"></div></div>
          </div>
        </div>
        <div class="card card-glow">
          <div class="card-title">💾 Disk</div>
          <div class="stat-value" id="disk-val">0%</div>
          <div class="stat-sub" id="disk-sub">Loading...</div>
          <div class="progress-wrap">
            <div class="progress-bar"><div class="progress-fill" id="disk-bar" style="width:0%"></div></div>
          </div>
        </div>
        <div class="card card-glow">
          <div class="card-title">🔄 Swap</div>
          <div class="stat-value" id="swap-val">0%</div>
          <div class="stat-sub" id="swap-sub">Loading...</div>
          <div class="progress-wrap">
            <div class="progress-bar"><div class="progress-fill" id="swap-bar" style="width:0%"></div></div>
          </div>
        </div>
      </div>

      <!-- Row 2: info cards -->
      <div class="grid g6" style="margin-bottom:16px;">
        <div class="card"><div class="card-title">⏱️ Uptime</div><div style="font-size:.9rem;font-weight:600;color:var(--accent)" id="uptime-val">—</div></div>
        <div class="card"><div class="card-title">🖥️ Hostname</div><div style="font-size:.9rem;font-weight:600;color:var(--text)" id="hostname-val">—</div></div>
        <div class="card"><div class="card-title">🐧 OS</div><div style="font-size:.85rem;font-weight:600;color:var(--text)" id="os-val">—</div></div>
        <div class="card"><div class="card-title">⚙️ Arch</div><div style="font-size:.9rem;font-weight:600;color:var(--text)" id="arch-val">—</div></div>
        <div class="card"><div class="card-title">📶 Load Avg</div><div style="font-size:.85rem;font-weight:600;color:var(--accent)" id="load-val">—</div></div>
        <div class="card"><div class="card-title">👥 Users</div><div style="font-size:.9rem;font-weight:600;color:var(--text)" id="users-val">—</div></div>
      </div>

      <!-- Row 3: charts -->
      <div class="grid g2" style="margin-bottom:16px;">
        <div class="card">
          <div class="card-title">📈 CPU History (60s)</div>
          <div class="chart-wrap"><canvas id="cpuChart"></canvas></div>
        </div>
        <div class="card">
          <div class="card-title">📈 Memory History (60s)</div>
          <div class="chart-wrap"><canvas id="memChart"></canvas></div>
        </div>
      </div>

      <!-- Row 4: net + per-core -->
      <div class="grid g2" style="margin-bottom:16px;">
        <div class="card">
          <div class="card-title">🌐 Network I/O</div>
          <div class="chart-wrap"><canvas id="netChart"></canvas></div>
        </div>
        <div class="card">
          <div class="card-title">🔲 Per-Core CPU</div>
          <div id="per-core-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(80px,1fr));gap:8px;margin-top:8px;"></div>
        </div>
      </div>

      <!-- Row 5: disks table -->
      <div class="card" style="margin-bottom:16px;">
        <div class="card-title">💽 Disk Partitions</div>
        <table id="disk-table">
          <thead><tr><th>Device</th><th>Mount</th><th>FS</th><th>Total</th><th>Used</th><th>Free</th><th>Usage</th></tr></thead>
          <tbody id="disk-tbody"></tbody>
        </table>
      </div>

      <!-- Row 6: system info tags -->
      <div class="card">
        <div class="card-title">🏷️ System Tags</div>
        <div id="sys-tags" style="margin-top:8px;"></div>
      </div>
    </div>

    <!-- ═══ TERMINAL ═══ -->
    <div class="tab-pane" id="tab-terminal">
      <div class="section-header">
        <span class="section-title">TERMINAL</span>
        <div style="display:flex;gap:8px;">
          <button class="btn secondary" onclick="clearTerm()">Clear</button>
          <button class="btn secondary" onclick="addCmdDialog()">+ Save Command</button>
        </div>
      </div>
      <div class="terminal">
        <div class="term-toolbar">
          <div class="term-dot" style="background:#ff5f57"></div>
          <div class="term-dot" style="background:#ffbd2e"></div>
          <div class="term-dot" style="background:#28c840"></div>
          <span style="font-size:.7rem;color:#64748b;margin-left:8px;">bash — nexus terminal</span>
        </div>
        <div class="term-output" id="term-out">
          <div class="line sys">Welcome to Nexus Panel Terminal</div>
          <div class="line sys">Type commands below. Dangerous commands are blocked.</div>
          <div class="line sys">─────────────────────────────</div>
        </div>
        <div class="term-input-wrap">
          <span class="term-prompt" id="term-prompt">root@vps:~$</span>
          <input class="term-input" id="term-in" placeholder="type a command..." autocomplete="off" spellcheck="false">
          <button class="btn" onclick="runCmd()">RUN</button>
        </div>
      </div>

      <div style="margin-top:20px;">
        <div class="section-header">
          <span class="section-title" style="font-size:.75rem;">SAVED COMMANDS</span>
          <input type="text" id="cmd-search" placeholder="Search..." style="width:200px;" oninput="filterCmds()">
        </div>
        <div class="cmd-grid" id="cmd-grid"></div>
      </div>
    </div>

    <!-- ═══ PROCESSES ═══ -->
    <div class="tab-pane" id="tab-processes">
      <div class="section-header">
        <span class="section-title">PROCESSES</span>
        <div style="display:flex;gap:8px;align-items:center;">
          <input type="text" id="proc-search" placeholder="Search process..." style="width:200px;" oninput="filterProcs()">
          <button class="btn secondary" onclick="refreshProcs()">🔄 Refresh</button>
        </div>
      </div>
      <div class="card">
        <table id="proc-table">
          <thead><tr><th>PID</th><th>Name</th><th>CPU%</th><th>MEM%</th><th>Status</th><th>User</th><th>Action</th></tr></thead>
          <tbody id="proc-tbody"></tbody>
        </table>
      </div>
    </div>

    <!-- ═══ NETWORK ═══ -->
    <div class="tab-pane" id="tab-network">
      <div class="section-header"><span class="section-title">NETWORK</span></div>
      <div class="grid g4" style="margin-bottom:16px;" id="net-cards"></div>
      <div class="card" style="margin-bottom:16px;">
        <div class="card-title">📡 Interfaces</div>
        <table>
          <thead><tr><th>Interface</th><th>IP</th><th>Speed</th><th>Status</th></tr></thead>
          <tbody id="iface-tbody"></tbody>
        </table>
      </div>
      <div class="card">
        <div class="card-title">🔌 Open Ports (quick scan)</div>
        <div id="ports-output" style="font-size:.75rem;color:#94a3b8;">
          <button class="btn" onclick="scanPorts()">Scan Open Ports</button>
        </div>
      </div>
    </div>

    <!-- ═══ FILE MANAGER ═══ -->
    <div class="tab-pane" id="tab-files">
      <div class="section-header"><span class="section-title">FILE MANAGER</span></div>
      <div class="card">
        <div class="file-toolbar">
          <span style="font-size:.72rem;color:#64748b;">Path:</span>
          <div class="path-bar" id="cur-path">~</div>
          <button class="btn secondary" onclick="goUp()">⬆ Up</button>
          <button class="btn secondary" onclick="loadFiles(document.getElementById('cur-path').textContent)">🔄</button>
          <button class="btn" onclick="newFileDialog()">+ File</button>
          <button class="btn secondary" onclick="newFolderDialog()">+ Folder</button>
        </div>
        <table>
          <thead><tr><th>Name</th><th>Size</th><th>Modified</th><th>Perms</th><th>Actions</th></tr></thead>
          <tbody id="file-tbody"></tbody>
        </table>
      </div>
    </div>

    <!-- ═══ SERVICES ═══ -->
    <div class="tab-pane" id="tab-services">
      <div class="section-header">
        <span class="section-title">SERVICES</span>
        <button class="btn secondary" onclick="loadServices()">🔄 Refresh</button>
      </div>
      <div class="card">
        <pre id="services-output" style="font-size:.72rem;color:#94a3b8;white-space:pre-wrap;max-height:500px;overflow-y:auto;">Loading...</pre>
      </div>
    </div>

    <!-- ═══ LOGS ═══ -->
    <div class="tab-pane" id="tab-logs">
      <div class="section-header">
        <span class="section-title">LOGS</span>
        <div style="display:flex;gap:8px;">
          <select id="log-select" onchange="loadLog(this.value)">
            <option value="syslog">Syslog</option>
            <option value="auth">Auth Log</option>
            <option value="kern">Kern Log</option>
            <option value="nginx">Nginx</option>
            <option value="apache">Apache</option>
          </select>
          <button class="btn secondary" onclick="loadLog(document.getElementById('log-select').value)">🔄</button>
        </div>
      </div>
      <div class="card">
        <pre id="log-output" style="font-size:.7rem;color:#94a3b8;white-space:pre-wrap;max-height:500px;overflow-y:auto;line-height:1.6;">Select a log file above...</pre>
      </div>
    </div>

    <!-- ═══ CRON ═══ -->
    <div class="tab-pane" id="tab-cron">
      <div class="section-header">
        <span class="section-title">CRON JOBS</span>
        <button class="btn secondary" onclick="loadCron()">🔄 Refresh</button>
      </div>
      <div class="card">
        <pre id="cron-output" style="font-size:.75rem;color:#94a3b8;white-space:pre-wrap;">Loading...</pre>
      </div>
      <div style="margin-top:16px;" class="card">
        <div class="card-title">➕ Add Cron Job</div>
        <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap;">
          <input type="text" id="cron-expr" placeholder="* * * * *" style="width:160px;">
          <input type="text" id="cron-cmd" placeholder="command to run" style="flex:1;min-width:200px;">
          <button class="btn" onclick="addCron()">Add</button>
        </div>
        <div style="font-size:.65rem;color:#64748b;margin-top:8px;">Format: minute hour day month weekday</div>
      </div>
    </div>

    <!-- ═══ SETTINGS ═══ -->
    <div class="tab-pane" id="tab-settings">
      <div class="section-header">
        <span class="section-title">PANEL SETTINGS</span>
        <button class="btn" onclick="saveSettings()">💾 Save All</button>
      </div>
      <div class="settings-grid">

        <!-- Identity -->
        <div class="card">
          <div class="card-title">🏷️ Identity</div>
          <div class="setting-row">
            <div><div class="setting-label">Panel Name</div></div>
            <input type="text" id="s-name" value="{{ config.panel_name }}" style="width:140px;">
          </div>
          <div class="setting-row">
            <div><div class="setting-label">Username</div></div>
            <input type="text" id="s-user" value="{{ config.username }}" style="width:140px;">
          </div>
          <div class="setting-row">
            <div><div class="setting-label">Password</div></div>
            <input type="password" id="s-pass" placeholder="(unchanged)" style="width:140px;">
          </div>
        </div>

        <!-- Colors -->
        <div class="card">
          <div class="card-title">🎨 Colors</div>
          <div class="setting-row">
            <div><div class="setting-label">Accent Color</div></div>
            <input type="color" id="s-accent" value="{{ config.accent }}">
          </div>
          <div class="setting-row">
            <div><div class="setting-label">Accent 2</div></div>
            <input type="color" id="s-accent2" value="{{ config.accent2 }}">
          </div>
          <div class="setting-row">
            <div><div class="setting-label">Background</div></div>
            <input type="color" id="s-bg" value="{{ config.bg_color }}">
          </div>
          <div class="setting-row">
            <div><div class="setting-label">Card Color</div></div>
            <input type="color" id="s-card" value="{{ config.card_color }}">
          </div>
          <div class="setting-row">
            <div><div class="setting-label">Text Color</div></div>
            <input type="color" id="s-text" value="{{ config.text_color }}">
          </div>
        </div>

        <!-- Fonts & Layout -->
        <div class="card">
          <div class="card-title">✍️ Typography</div>
          <div class="setting-row">
            <div><div class="setting-label">Font</div></div>
            <select id="s-font" style="width:170px;">
              <option value="JetBrains Mono" {{ 'selected' if config.font=='JetBrains Mono' }}>JetBrains Mono</option>
              <option value="Fira Code" {{ 'selected' if config.font=='Fira Code' }}>Fira Code</option>
              <option value="Share Tech Mono" {{ 'selected' if config.font=='Share Tech Mono' }}>Share Tech Mono</option>
              <option value="Courier New" {{ 'selected' if config.font=='Courier New' }}>Courier New</option>
              <option value="monospace" {{ 'selected' if config.font=='monospace' }}>System Mono</option>
            </select>
          </div>
          <div class="setting-row">
            <div><div class="setting-label">Border Radius</div></div>
            <select id="s-radius" style="width:120px;">
              <option value="4px" {{ 'selected' if config.border_radius=='4px' }}>Sharp</option>
              <option value="8px" {{ 'selected' if config.border_radius=='8px' }}>Rounded</option>
              <option value="12px" {{ 'selected' if config.border_radius=='12px' }}>Soft</option>
              <option value="20px" {{ 'selected' if config.border_radius=='20px' }}>Pill</option>
            </select>
          </div>
        </div>

        <!-- Effects -->
        <div class="card">
          <div class="card-title">✨ Effects</div>
          <div class="setting-row">
            <div><div class="setting-label">Animations</div></div>
            <label class="toggle"><input type="checkbox" id="s-anim" {{ 'checked' if config.animations }}><span class="toggle-slider"></span></label>
          </div>
          <div class="setting-row">
            <div><div class="setting-label">Glass Effect</div></div>
            <label class="toggle"><input type="checkbox" id="s-glass" {{ 'checked' if config.glass_effect }}><span class="toggle-slider"></span></label>
          </div>
          <div class="setting-row">
            <div><div class="setting-label">Glow Effect</div></div>
            <label class="toggle"><input type="checkbox" id="s-glow" {{ 'checked' if config.glow_effect }}><span class="toggle-slider"></span></label>
          </div>
        </div>

        <!-- Performance -->
        <div class="card">
          <div class="card-title">⚡ Performance</div>
          <div class="setting-row">
            <div><div class="setting-label">Refresh Rate</div><div class="setting-desc">seconds between updates</div></div>
            <input type="number" id="s-refresh" value="{{ config.refresh_rate }}" min="1" max="60" style="width:80px;">
          </div>
        </div>

        <!-- Presets -->
        <div class="card">
          <div class="card-title">🎭 Theme Presets</div>
          <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:8px;">
            <button class="btn secondary" onclick="applyPreset('cyber')">🔵 Cyber</button>
            <button class="btn secondary" onclick="applyPreset('matrix')">🟢 Matrix</button>
            <button class="btn secondary" onclick="applyPreset('crimson')">🔴 Crimson</button>
            <button class="btn secondary" onclick="applyPreset('purple')">🟣 Purple</button>
            <button class="btn secondary" onclick="applyPreset('gold')">🟡 Gold</button>
            <button class="btn secondary" onclick="applyPreset('pink')">🩷 Pink</button>
            <button class="btn secondary" onclick="applyPreset('mono')">⚫ Mono</button>
            <button class="btn secondary" onclick="applyPreset('light')">☀️ Light</button>
          </div>
        </div>

      </div>
    </div>

  </div><!-- /content -->
</div><!-- /main -->

<div class="toast-wrap" id="toasts"></div>

<!-- Add Command Dialog -->
<div id="cmd-dialog" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:200;display:none;align-items:center;justify-content:center;">
  <div class="card" style="width:400px;max-width:90vw;position:relative;">
    <div class="card-title">➕ Save Command</div>
    <div style="margin-top:12px;">
      <div style="margin-bottom:10px;"><label style="font-size:.7rem;color:#94a3b8;display:block;margin-bottom:4px;">Name</label><input type="text" id="new-cmd-name" style="width:100%;" placeholder="e.g. Check Nginx"></div>
      <div><label style="font-size:.7rem;color:#94a3b8;display:block;margin-bottom:4px;">Command</label><input type="text" id="new-cmd-val" style="width:100%;" placeholder="e.g. systemctl status nginx"></div>
    </div>
    <div style="display:flex;gap:8px;margin-top:16px;justify-content:flex-end;">
      <button class="btn secondary" onclick="closeCmdDialog()">Cancel</button>
      <button class="btn" onclick="saveNewCmd()">Save</button>
    </div>
  </div>
</div>

<script>
// ─── State ─────────────────────────────────────────────────────────────────
let lastStats = {};
let cpuHistory = new Array(60).fill(0);
let memHistory = new Array(60).fill(0);
let netSentPrev = 0, netRecvPrev = 0;
let netSentH = new Array(60).fill(0), netRecvH = new Array(60).fill(0);
let cmdHistory = [], cmdIdx = -1;
let currentPath = '';

// ─── Socket ────────────────────────────────────────────────────────────────
const socket = io();
socket.on('stats_update', updateStats);

// ─── Charts ────────────────────────────────────────────────────────────────
function makeChart(id, label1, label2, color1, color2) {
  const ctx = document.getElementById(id);
  if (!ctx) return null;
  return new Chart(ctx, {
    type: 'line',
    data: {
      labels: new Array(60).fill(''),
      datasets: [
        { label: label1, data: new Array(60).fill(0), borderColor: color1, backgroundColor: color1+'22', borderWidth: 2, pointRadius: 0, fill: true, tension: .4 },
        ...(label2 ? [{ label: label2, data: new Array(60).fill(0), borderColor: color2, backgroundColor: color2+'22', borderWidth: 2, pointRadius: 0, fill: true, tension: .4 }] : [])
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: { legend: { display: !!label2, labels: { color: '#94a3b8', font: { size: 10 } } } },
      scales: {
        x: { display: false },
        y: { min: 0, max: id.includes('cpu') || id.includes('mem') ? 100 : undefined,
             grid: { color: 'rgba(255,255,255,.04)' },
             ticks: { color: '#64748b', font: { size: 10 }, callback: v => id.includes('net') ? fmtSpeed(v) : v+'%' } }
      }
    }
  });
}

const cpuChart = makeChart('cpuChart', 'CPU %', null, getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#00d4ff');
const memChart = makeChart('memChart', 'MEM %', null, '#7c3aed');
const netChart = makeChart('netChart', 'Upload', 'Download', '#f59e0b', '#06b6d4');

function fmtSpeed(b) {
  if (b < 1024) return b + ' B/s';
  if (b < 1048576) return (b/1024).toFixed(1) + ' KB/s';
  return (b/1048576).toFixed(1) + ' MB/s';
}

// ─── Stats Update ─────────────────────────────────────────────────────────
function updateStats(s) {
  lastStats = s;

  // CPU
  const cpuPct = s.cpu || 0;
  document.getElementById('cpu-val').textContent = cpuPct.toFixed(1) + '%';
  document.getElementById('cpu-model').textContent = (s.cpu_model || 'Unknown').slice(0, 40);
  setBar('cpu-bar', cpuPct);

  // Memory
  const memPct = s.mem_percent || 0;
  document.getElementById('mem-val').textContent = memPct.toFixed(1) + '%';
  document.getElementById('mem-sub').textContent = `${fmtBytes(s.mem_used)} / ${fmtBytes(s.mem_total)}`;
  setBar('mem-bar', memPct);

  // Swap
  const swapPct = s.swap_percent || 0;
  document.getElementById('swap-val').textContent = swapPct.toFixed(1) + '%';
  document.getElementById('swap-sub').textContent = `${fmtBytes(s.swap_used)} / ${fmtBytes(s.swap_total)}`;
  setBar('swap-bar', swapPct);

  // Disk (first partition)
  if (s.disks && s.disks.length) {
    const d = s.disks[0];
    document.getElementById('disk-val').textContent = d.percent.toFixed(1) + '%';
    document.getElementById('disk-sub').textContent = `${fmtBytes(d.used)} / ${fmtBytes(d.total)}`;
    setBar('disk-bar', d.percent);
  }

  // Info
  document.getElementById('uptime-val').textContent = s.uptime || '—';
  document.getElementById('hostname-val').textContent = s.hostname || '—';
  document.getElementById('os-val').textContent = (s.os || '') + ' ' + (s.os_release || '');
  document.getElementById('arch-val').textContent = s.arch || '—';
  document.getElementById('load-val').textContent = s.load_avg ? s.load_avg.map(x=>x.toFixed(2)).join(' ') : '—';
  document.getElementById('users-val').textContent = s.users ? s.users.length : '0';

  // Histories
  cpuHistory.push(cpuPct); cpuHistory.shift();
  memHistory.push(memPct); memHistory.shift();

  if (cpuChart) { cpuChart.data.datasets[0].data = [...cpuHistory]; cpuChart.update('none'); }
  if (memChart) { memChart.data.datasets[0].data = [...memHistory]; memChart.update('none'); }

  // Network
  const sentDelta = Math.max(0, (s.net_sent - netSentPrev));
  const recvDelta = Math.max(0, (s.net_recv - netRecvPrev));
  if (netSentPrev > 0) {
    netSentH.push(sentDelta); netSentH.shift();
    netRecvH.push(recvDelta); netRecvH.shift();
  }
  netSentPrev = s.net_sent; netRecvPrev = s.net_recv;
  if (netChart) {
    netChart.data.datasets[0].data = [...netSentH];
    netChart.data.datasets[1].data = [...netRecvH];
    netChart.update('none');
  }

  // Net cards
  const nc = document.getElementById('net-cards');
  if (nc) nc.innerHTML = `
    <div class="card card-glow"><div class="card-title">📤 Total Sent</div><div class="stat-value" style="font-size:1.3rem;">${fmtBytes(s.net_sent)}</div></div>
    <div class="card card-glow"><div class="card-title">📥 Total Recv</div><div class="stat-value" style="font-size:1.3rem;">${fmtBytes(s.net_recv)}</div></div>
    <div class="card card-glow"><div class="card-title">📦 Pkts Sent</div><div class="stat-value" style="font-size:1.3rem;">${s.net_pkts_sent?.toLocaleString()}</div></div>
    <div class="card card-glow"><div class="card-title">📦 Pkts Recv</div><div class="stat-value" style="font-size:1.3rem;">${s.net_pkts_recv?.toLocaleString()}</div></div>
  `;

  // Interfaces
  const iBody = document.getElementById('iface-tbody');
  if (iBody && s.net_ifaces) {
    iBody.innerHTML = Object.entries(s.net_ifaces).map(([k,v]) =>
      `<tr><td>${k}</td><td>${v.ip}</td><td>${v.speed} Mbps</td><td><span class="badge ${v.isup?'green':'red'}">${v.isup?'UP':'DOWN'}</span></td></tr>`
    ).join('');
  }

  // Per-core
  const pcg = document.getElementById('per-core-grid');
  if (pcg && s.cpu_per_core) {
    pcg.innerHTML = s.cpu_per_core.map((p,i) => `
      <div style="text-align:center;">
        <div style="font-size:.6rem;color:#64748b;margin-bottom:4px;">Core ${i}</div>
        <div style="font-size:.9rem;font-weight:700;color:var(--accent)">${p.toFixed(0)}%</div>
        <div class="progress-bar" style="margin-top:4px;"><div class="progress-fill ${p>80?'danger':p>60?'warn':''}" style="width:${p}%"></div></div>
      </div>
    `).join('');
  }

  // Disk table
  const dt = document.getElementById('disk-tbody');
  if (dt && s.disks) {
    dt.innerHTML = s.disks.map(d => `
      <tr>
        <td>${d.device}</td><td>${d.mountpoint}</td><td><span class="badge blue">${d.fstype}</span></td>
        <td>${fmtBytes(d.total)}</td><td>${fmtBytes(d.used)}</td><td>${fmtBytes(d.free)}</td>
        <td>
          <div style="display:flex;align-items:center;gap:8px;">
            <div class="progress-bar" style="width:80px;"><div class="progress-fill ${d.percent>80?'danger':d.percent>60?'warn':''}" style="width:${d.percent}%"></div></div>
            <span style="font-size:.7rem;">${d.percent.toFixed(1)}%</span>
          </div>
        </td>
      </tr>
    `).join('');
  }

  // Process table
  const pb = document.getElementById('proc-tbody');
  if (pb && s.processes) {
    const term = document.getElementById('proc-search')?.value.toLowerCase() || '';
    pb.innerHTML = s.processes.filter(p => !term || (p.name||'').toLowerCase().includes(term)).map(p => `
      <tr>
        <td>${p.pid}</td>
        <td style="font-weight:500;">${p.name||'?'}</td>
        <td><span style="color:${p.cpu_percent>50?'#f87171':p.cpu_percent>20?'#fbbf24':'#4ade80'}">${(p.cpu_percent||0).toFixed(1)}%</span></td>
        <td>${(p.memory_percent||0).toFixed(1)}%</td>
        <td><span class="badge ${p.status==='running'?'green':'yellow'}">${p.status||'?'}</span></td>
        <td>${p.username||'?'}</td>
        <td><button class="btn danger" style="padding:3px 8px;font-size:.65rem;" onclick="killProc(${p.pid})">Kill</button></td>
      </tr>
    `).join('');
  }

  // Sys tags
  const st = document.getElementById('sys-tags');
  if (st) st.innerHTML = [
    `OS: ${s.os} ${s.os_release}`, `Python: ${s.python}`, `Arch: ${s.arch}`,
    `Boot: ${s.boot_time}`, `Cores: ${s.cpu_cores}`,
    s.cpu_freq?.current ? `CPU Freq: ${s.cpu_freq.current?.toFixed(0)} MHz` : '',
    `MEM Cached: ${fmtBytes(s.mem_cached||0)}`,
  ].filter(Boolean).map(t => `<span class="tag">${t}</span>`).join('');

  // Terminal prompt
  document.getElementById('term-prompt').textContent = `${s.hostname||'vps'}:~$`;
}

function setBar(id, pct) {
  const el = document.getElementById(id);
  if (!el) return;
  el.style.width = pct + '%';
  el.className = 'progress-fill' + (pct > 90 ? ' danger' : pct > 70 ? ' warn' : '');
}

function fmtBytes(b) {
  if (!b) return '0 B';
  const u = ['B','KB','MB','GB','TB'];
  let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return b.toFixed(1) + ' ' + u[i];
}

// ─── Tabs ──────────────────────────────────────────────────────────────────
const tabTitles = {
  dashboard:'DASHBOARD',terminal:'TERMINAL',processes:'PROCESSES',
  network:'NETWORK',files:'FILE MANAGER',services:'SERVICES',
  logs:'LOGS',cron:'CRON JOBS',settings:'SETTINGS'
};

function showTab(name) {
  document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-'+name)?.classList.add('active');
  event?.currentTarget?.classList.add('active');
  document.getElementById('topbar-title').textContent = tabTitles[name] || name.toUpperCase();
  if (name === 'terminal') renderCmdGrid();
  if (name === 'services') loadServices();
  if (name === 'cron') loadCron();
  if (name === 'files' && !currentPath) loadFiles(null);
  if (name === 'logs') loadLog('syslog');
}

function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('collapsed');
  document.getElementById('main').classList.toggle('collapsed');
}

// ─── Terminal ──────────────────────────────────────────────────────────────
async function runCmd(cmdOverride) {
  const inp = document.getElementById('term-in');
  const cmd = cmdOverride || inp.value.trim();
  if (!cmd) return;
  if (!cmdOverride) { inp.value = ''; cmdHistory.unshift(cmd); cmdIdx = -1; }
  addTermLine('$ ' + cmd, 'cmd');
  const r = await fetch('/api/exec', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd})});
  const d = await r.json();
  if (d.output) d.output.split('\n').forEach(l => addTermLine(l));
  if (d.error) d.error.split('\n').filter(Boolean).forEach(l => addTermLine(l, 'err'));
}

function addTermLine(text, cls='') {
  const out = document.getElementById('term-out');
  const div = document.createElement('div');
  div.className = 'line ' + cls;
  div.textContent = text;
  out.appendChild(div);
  out.scrollTop = out.scrollHeight;
}

function clearTerm() {
  document.getElementById('term-out').innerHTML = '<div class="line sys">Terminal cleared.</div>';
}

document.getElementById('term-in').addEventListener('keydown', e => {
  if (e.key === 'Enter') runCmd();
  else if (e.key === 'ArrowUp') { cmdIdx = Math.min(cmdIdx+1, cmdHistory.length-1); e.target.value = cmdHistory[cmdIdx]||''; }
  else if (e.key === 'ArrowDown') { cmdIdx = Math.max(cmdIdx-1, -1); e.target.value = cmdIdx < 0 ? '' : cmdHistory[cmdIdx]; }
});

// ─── Saved Commands ────────────────────────────────────────────────────────
let savedCmds = [];
async function loadSavedCmds() {
  const r = await fetch('/api/config');
  const cfg = await r.json();
  savedCmds = cfg.saved_commands || [];
  renderCmdGrid();
}

function renderCmdGrid(filter='') {
  const g = document.getElementById('cmd-grid');
  if (!g) return;
  const cmds = filter ? savedCmds.filter(c => c.name.toLowerCase().includes(filter) || c.cmd.toLowerCase().includes(filter)) : savedCmds;
  g.innerHTML = cmds.map((c,i) => `
    <div class="cmd-chip" title="${c.cmd}">
      <span class="cmd-chip-name" onclick="runCmd('${c.cmd.replace(/'/g,"\\'")}')">⚡ ${c.name}</span>
      <span onclick="deleteCmd(${i})" style="color:#f87171;opacity:.5;cursor:pointer;" title="Delete">✕</span>
    </div>
  `).join('');
}

function filterCmds() { renderCmdGrid(document.getElementById('cmd-search').value.toLowerCase()); }

function addCmdDialog() {
  const d = document.getElementById('cmd-dialog');
  d.style.display = 'flex';
}
function closeCmdDialog() {
  document.getElementById('cmd-dialog').style.display = 'none';
}

async function saveNewCmd() {
  const name = document.getElementById('new-cmd-name').value.trim();
  const cmd = document.getElementById('new-cmd-val').value.trim();
  if (!name || !cmd) return;
  savedCmds.push({name, cmd});
  await fetch('/api/config', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({saved_commands: savedCmds})});
  closeCmdDialog();
  renderCmdGrid();
  toast('Command saved!', 'success');
}

async function deleteCmd(i) {
  savedCmds.splice(i, 1);
  await fetch('/api/config', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({saved_commands: savedCmds})});
  renderCmdGrid();
}

// ─── Processes ─────────────────────────────────────────────────────────────
function filterProcs() { /* handled in updateStats */ }
function refreshProcs() { fetch('/api/stats').then(r=>r.json()).then(updateStats); }
async function killProc(pid) {
  if (!confirm(`Kill PID ${pid}?`)) return;
  const r = await fetch('/api/exec', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:`kill -9 ${pid}`})});
  const d = await r.json();
  toast(d.error || `Killed PID ${pid}`, d.error ? 'error' : 'success');
}

// ─── Services ──────────────────────────────────────────────────────────────
async function loadServices() {
  document.getElementById('services-output').textContent = 'Loading...';
  const r = await fetch('/api/services');
  const d = await r.json();
  document.getElementById('services-output').textContent = d.output || d.error;
}

// ─── Logs ──────────────────────────────────────────────────────────────────
async function loadLog(name) {
  document.getElementById('log-output').textContent = 'Loading...';
  const r = await fetch('/api/logs/' + name);
  const d = await r.json();
  document.getElementById('log-output').textContent = d.content || d.error;
}

// ─── Cron ──────────────────────────────────────────────────────────────────
async function loadCron() {
  const r = await fetch('/api/cron');
  const d = await r.json();
  document.getElementById('cron-output').textContent = d.output || d.error;
}

async function addCron() {
  const expr = document.getElementById('cron-expr').value.trim();
  const cmd = document.getElementById('cron-cmd').value.trim();
  if (!expr || !cmd) return;
  const r = await fetch('/api/exec', {method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({cmd:`(crontab -l 2>/dev/null; echo "${expr} ${cmd}") | crontab -`})});
  const d = await r.json();
  toast(d.error || 'Cron job added!', d.error ? 'error' : 'success');
  loadCron();
}

// ─── File Manager ──────────────────────────────────────────────────────────
async function loadFiles(path) {
  const p = path || document.getElementById('cur-path').textContent || '~';
  const r = await fetch('/api/files?path=' + encodeURIComponent(p));
  const d = await r.json();
  if (!d.ok) { toast(d.error, 'error'); return; }
  currentPath = d.path;
  document.getElementById('cur-path').textContent = d.path;
  const tb = document.getElementById('file-tbody');
  tb.innerHTML = d.entries.map(e => `
    <tr>
      <td>${e.is_dir ? '📁' : '📄'} <span style="cursor:pointer;color:${e.is_dir?'var(--accent)':'inherit'}" onclick="${e.is_dir ? `loadFiles('${e.path.replace(/'/g,"\\'")}')` : `viewFile('${e.path.replace(/'/g,"\\'")}')`}">${e.name}</span></td>
      <td>${e.is_dir ? '—' : fmtBytes(e.size)}</td>
      <td>${e.modified}</td>
      <td><span class="badge blue">${e.perms}</span></td>
      <td style="display:flex;gap:4px;">
        ${!e.is_dir ? `<button class="btn secondary" style="padding:3px 8px;font-size:.65rem;" onclick="editFile('${e.path.replace(/'/g,"\\'")}')">Edit</button>` : ''}
        <button class="btn danger" style="padding:3px 8px;font-size:.65rem;" onclick="deleteFile('${e.path.replace(/'/g,"\\'")}')">Del</button>
      </td>
    </tr>
  `).join('');
}

function goUp() {
  const parent = currentPath.split('/').slice(0, -1).join('/') || '/';
  loadFiles(parent);
}

async function viewFile(path) {
  const r = await fetch('/api/file/read?path=' + encodeURIComponent(path));
  const d = await r.json();
  if (!d.ok) { toast(d.error,'error'); return; }
  const w = window.open('','_blank','width=800,height=600');
  w.document.write(`<pre style="background:#050810;color:#a8d8a8;padding:20px;font-family:monospace;font-size:13px;">${d.content.replace(/</g,'&lt;')}</pre>`);
}

async function editFile(path) {
  const r = await fetch('/api/file/read?path=' + encodeURIComponent(path));
  const d = await r.json();
  if (!d.ok) { toast(d.error,'error'); return; }
  const content = prompt('Edit file (save on OK):', d.content.slice(0, 2000));
  if (content === null) return;
  await fetch('/api/file/write', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path, content})});
  toast('File saved!', 'success');
}

async function deleteFile(path) {
  if (!confirm('Delete ' + path + '?')) return;
  await fetch('/api/exec', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:`rm -rf "${path}"`})});
  toast('Deleted!', 'success');
  loadFiles(currentPath);
}

function newFileDialog() {
  const name = prompt('New file name:');
  if (!name) return;
  fetch('/api/file/write', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path: currentPath+'/'+name, content: ''})})
    .then(() => { toast('File created!','success'); loadFiles(currentPath); });
}

async function newFolderDialog() {
  const name = prompt('New folder name:');
  if (!name) return;
  await fetch('/api/exec', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:`mkdir -p "${currentPath}/${name}"`})});
  toast('Folder created!', 'success');
  loadFiles(currentPath);
}

async function scanPorts() {
  document.getElementById('ports-output').innerHTML = '<div class="spinner"></div> Scanning...';
  const r = await fetch('/api/exec', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:'ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null'})});
  const d = await r.json();
  document.getElementById('ports-output').innerHTML = `<pre style="font-size:.72rem;color:#a8d8a8;white-space:pre-wrap;">${d.output||d.error}</pre>`;
}

// ─── Settings ─────────────────────────────────────────────────────────────
async function saveSettings() {
  const updates = {
    panel_name: document.getElementById('s-name').value,
    accent: document.getElementById('s-accent').value,
    accent2: document.getElementById('s-accent2').value,
    bg_color: document.getElementById('s-bg').value,
    card_color: document.getElementById('s-card').value,
    text_color: document.getElementById('s-text').value,
    font: document.getElementById('s-font').value,
    border_radius: document.getElementById('s-radius').value,
    animations: document.getElementById('s-anim').checked,
    glass_effect: document.getElementById('s-glass').checked,
    glow_effect: document.getElementById('s-glow').checked,
    refresh_rate: parseInt(document.getElementById('s-refresh').value),
    username: document.getElementById('s-user').value,
  };
  const pw = document.getElementById('s-pass').value;
  if (pw) updates.password = pw;
  await fetch('/api/config', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(updates)});
  toast('Settings saved! Reload to apply theme.', 'success');
  applyThemeLive(updates);
  document.getElementById('panel-name-logo').textContent = updates.panel_name;
}

function applyThemeLive(cfg) {
  const r = document.documentElement.style;
  r.setProperty('--accent', cfg.accent);
  r.setProperty('--accent2', cfg.accent2);
  r.setProperty('--bg', cfg.bg_color);
  r.setProperty('--card', cfg.card_color);
  r.setProperty('--text', cfg.text_color);
  r.setProperty('--radius', cfg.border_radius);
  document.body.style.fontFamily = `'${cfg.font}', monospace`;
}

const presets = {
  cyber:   {accent:'#00d4ff',accent2:'#7c3aed',bg_color:'#080b14',card_color:'#0d1117',text_color:'#e2e8f0'},
  matrix:  {accent:'#00ff41',accent2:'#00cc33',bg_color:'#000a00',card_color:'#001100',text_color:'#00ff41'},
  crimson: {accent:'#ef4444',accent2:'#dc2626',bg_color:'#0f0505',card_color:'#1a0808',text_color:'#fca5a5'},
  purple:  {accent:'#a855f7',accent2:'#7c3aed',bg_color:'#0d0814',card_color:'#120d1a',text_color:'#e9d5ff'},
  gold:    {accent:'#f59e0b',accent2:'#d97706',bg_color:'#0f0a00',card_color:'#1a1200',text_color:'#fde68a'},
  pink:    {accent:'#ec4899',accent2:'#db2777',bg_color:'#0f0510',card_color:'#1a0818',text_color:'#fbcfe8'},
  mono:    {accent:'#94a3b8',accent2:'#64748b',bg_color:'#0a0a0a',card_color:'#111111',text_color:'#e2e8f0'},
  light:   {accent:'#2563eb',accent2:'#7c3aed',bg_color:'#f1f5f9',card_color:'#ffffff',text_color:'#1e293b'},
};

function applyPreset(name) {
  const p = presets[name];
  if (!p) return;
  document.getElementById('s-accent').value = p.accent;
  document.getElementById('s-accent2').value = p.accent2;
  document.getElementById('s-bg').value = p.bg_color;
  document.getElementById('s-card').value = p.card_color;
  document.getElementById('s-text').value = p.text_color;
  applyThemeLive({...p, border_radius: document.getElementById('s-radius').value});
  toast(`Preset "${name}" applied! Hit Save to keep.`, 'info');
}

// ─── Toast ─────────────────────────────────────────────────────────────────
function toast(msg, type='info') {
  const wrap = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `<span>${type==='success'?'✅':type==='error'?'❌':'ℹ️'}</span> ${msg}`;
  wrap.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ─── Clock ─────────────────────────────────────────────────────────────────
setInterval(() => {
  document.getElementById('topbar-time').textContent = new Date().toLocaleTimeString();
}, 1000);

// ─── Init ──────────────────────────────────────────────────────────────────
loadSavedCmds();
fetch('/api/stats').then(r=>r.json()).then(updateStats);
</script>
</body></html>"""

# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("╔══════════════════════════════════════════╗")
    print("║        NEXUS PANEL STARTING...           ║")
    print("╠══════════════════════════════════════════╣")
    print(f"║  URL:  http://0.0.0.0:5555               ║")
    print(f"║  Login: admin / admin                    ║")
    print("╚══════════════════════════════════════════╝")
    socketio.run(app, host='0.0.0.0', port=5555, debug=False, allow_unsafe_werkzeug=True)
