import os
import re
import csv
import json
import math

def parse_filename(filename):
    """
    Parses filename to extract metadata: rack, commanded torque, and trial identifier.
    Example: torque_instant_300cNm_1780030629_237_7_300_r2_2.csv
    """
    name = os.path.basename(filename)
    if not name.endswith('.csv'):
        return None
    
    base = name[:-4]
    parts = base.split('_')
    
    # Identify the rack
    rack = None
    if '237' in parts:
        rack = '237'
    elif '311' in parts:
        rack = '311'
    else:
        return None
        
    # Extract commanded torque
    # Regex searches for _[rack]_7_[torque]
    match = re.search(rf'_{rack}_7_(\d+)', base)
    if not match:
        # Fallback search for cNm_<timestamp>_<rack>
        match = re.search(r'cNm_\d+_[23]7_7_(\d+)', base)
        if not match:
            return None
            
    torque = int(match.group(1))
    
    # Determine the unique run representation
    pattern = f"_{rack}_7_{torque}"
    idx = base.find(pattern)
    suffix = ""
    if idx != -1:
        suffix = base[idx + len(pattern):].strip('_')
        
    run_name = "Run 1"
    if suffix == "2":
        run_name = "Run 2"
    elif suffix == "3":
        run_name = "Run 3"
    elif suffix == "r2":
        run_name = "Test 2 Run 1"
    elif suffix == "r2_2":
        run_name = "Test 2 Run 2"
    elif suffix:
        run_name = f"Run {suffix.replace('_', ' ').title()}"
        
    return {
        "filepath": filename,
        "basename": name,
        "rack": rack,
        "torque": torque,
        "run_name": run_name
    }

def downsample_series(time_series, val_series, t_min, t_max, target_dt=0.01):
    """
    Resamples time and value series on a uniform grid from t_min to t_max with step target_dt.
    Uses linear interpolation for accuracy and smooth visual curves.
    """
    if not time_series:
        return [], []
        
    resampled_t = []
    resampled_v = []
    
    t_curr = t_min
    idx = 0
    n = len(time_series)
    
    while t_curr <= t_max:
        # Advance index to surround t_curr
        while idx < n - 1 and time_series[idx + 1] < t_curr:
            idx += 1
            
        if idx == n - 1:
            val = val_series[-1]
        else:
            t0, t1 = time_series[idx], time_series[idx + 1]
            v0, v1 = val_series[idx], val_series[idx + 1]
            if t1 == t0:
                val = v0
            else:
                fraction = (t_curr - t0) / (t1 - t0)
                val = v0 + fraction * (v1 - v0)
                
        resampled_t.append(round(t_curr, 4))
        resampled_v.append(round(val, 4))
        t_curr += target_dt
        
    return resampled_t, resampled_v

def analyze_file(file_info):
    """
    Parses a single trial CSV file and extracts key response metrics.
    Time-aligns the data such that HCA activation (eps_torque == 8) starts at t_aligned = 0.
    """
    filepath = file_info["filepath"]
    
    time_sec = []
    commanded_torque = []
    wheel_angle = []
    angular_velocity = []
    driver_torque = []
    eps_torque = []
    
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                time_sec.append(float(row['time_sec']))
                commanded_torque.append(float(row['commanded_torque']))
                wheel_angle.append(float(row['wheel_angle']))
                angular_velocity.append(float(row['angular_velocity']))
                driver_torque.append(float(row['driver_torque']))
                eps_torque.append(float(row['eps_torque']))
            except (ValueError, KeyError):
                continue
                
    if not time_sec:
        return None
        
    # Find HCA activation start index (first eps_torque > 5.0, i.e., 8.0)
    t_start = None
    start_idx = -1
    for i, eps in enumerate(eps_torque):
        if eps > 5.0:
            t_start = time_sec[i]
            start_idx = i
            break
            
    if t_start is None:
        # Fallback to index 0 if HCA activation trigger is not found
        t_start = time_sec[0]
        start_idx = 0
        
    # Calculate aligned times
    t_aligned = [t - t_start for t in time_sec]
    
    # Filter active phase data (from t_aligned >= 0)
    active_indices = [i for i, t in enumerate(t_aligned) if t >= 0]
    if not active_indices:
        return None
        
    # Key dynamic metrics
    peak_angle = max(wheel_angle[i] for i in active_indices)
    peak_velocity = max(angular_velocity[i] for i in active_indices)
    
    # Driver torque coupling metrics
    abs_driver_torques = [abs(driver_torque[i]) for i in active_indices]
    peak_driver_torque = max(abs_driver_torques) if abs_driver_torques else 0.0
    
    # Calculate steady state driver torque in the latter hold phase (t_aligned between 2.5 and 4.5 seconds)
    hold_indices = [i for i in active_indices if 2.5 <= t_aligned[i] <= 4.5]
    if hold_indices:
        ss_driver_torque = sum(abs(driver_torque[i]) for i in hold_indices) / len(hold_indices)
    else:
        cutoff = int(len(active_indices) * 0.8)
        fallback_indices = active_indices[cutoff:]
        ss_driver_torque = sum(abs(driver_torque[i]) for i in fallback_indices) / len(fallback_indices) if fallback_indices else 0.0
        
    # Acceleration metrics
    # Time to reach peak velocity
    peak_vel_idx = active_indices[0]
    max_v = -1e9
    for i in active_indices:
        if angular_velocity[i] > max_v:
            max_v = angular_velocity[i]
            peak_vel_idx = i
    time_to_peak_velocity = t_aligned[peak_vel_idx]
    
    # Rise time to 50% and 90% of peak angle
    t_rise_50 = 0.0
    t_rise_90 = 0.0
    
    target_50 = 0.5 * peak_angle
    target_90 = 0.9 * peak_angle
    
    for i in active_indices:
        if wheel_angle[i] >= target_50 and t_rise_50 == 0.0:
            t_rise_50 = t_aligned[i]
        if wheel_angle[i] >= target_90 and t_rise_90 == 0.0:
            t_rise_90 = t_aligned[i]
            break
            
    # Resample curves on a uniform timeline (-0.2s to 4.5s) for visual overlays in the GUI
    resampled_t, resampled_angle = downsample_series(t_aligned, wheel_angle, -0.2, 4.5, 0.01)
    _, resampled_velocity = downsample_series(t_aligned, angular_velocity, -0.2, 4.5, 0.01)
    _, resampled_driver_tq = downsample_series(t_aligned, driver_torque, -0.2, 4.5, 0.01)
    _, resampled_eps_tq = downsample_series(t_aligned, eps_torque, -0.2, 4.5, 0.01)
    
    return {
        "basename": file_info["basename"],
        "rack": file_info["rack"],
        "torque": file_info["torque"],
        "run_name": file_info["run_name"],
        "metrics": {
            "peak_angle": round(peak_angle, 2),
            "peak_velocity": round(peak_velocity, 2),
            "peak_driver_torque": round(peak_driver_torque, 2),
            "steady_state_driver_torque": round(ss_driver_torque, 2),
            "time_to_peak_velocity": round(time_to_peak_velocity, 3),
            "rise_time_50": round(t_rise_50, 3),
            "rise_time_90": round(t_rise_90, 3)
        },
        "series": {
            "time": resampled_t,
            "angle": resampled_angle,
            "velocity": resampled_velocity,
            "driver_torque": resampled_driver_tq,
            "eps_torque": resampled_eps_tq
        }
    }

def calculate_stats(values):
    """
    Calculates mean and standard deviation for a list of numeric values.
    """
    if not values:
        return 0.0, 0.0
    n = len(values)
    mean = sum(values) / n
    if n <= 1:
        return mean, 0.0
    variance = sum((x - mean) ** 2 for x in values) / (n - 1)
    std_dev = math.sqrt(variance)
    return mean, std_dev

def process_all_data(data_dir):
    """
    Iterates through all CSVs, processes the dynamic metrics, and aggregates statistical summaries.
    """
    files = [os.path.join(data_dir, f) for f in os.listdir(data_dir) if f.endswith('.csv')]
    
    raw_results = []
    
    for f in files:
        file_info = parse_filename(f)
        if not file_info:
            continue
        analysis = analyze_file(file_info)
        if analysis:
            raw_results.append(analysis)
            
    # Group raw trials by (rack, torque) to compute standard deviations/means
    grouped = {}
    for res in raw_results:
        key = (res["rack"], res["torque"])
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(res)
        
    aggregated = []
    for (rack, torque), trials in grouped.items():
        # Collect metric arrays
        angles = [t["metrics"]["peak_angle"] for t in trials]
        velocities = [t["metrics"]["peak_velocity"] for t in trials]
        peak_driver_tqs = [t["metrics"]["peak_driver_torque"] for t in trials]
        ss_driver_tqs = [t["metrics"]["steady_state_driver_torque"] for t in trials]
        vel_times = [t["metrics"]["time_to_peak_velocity"] for t in trials]
        rise_90s = [t["metrics"]["rise_time_90"] for t in trials]
        
        # Calculate stats
        mean_angle, std_angle = calculate_stats(angles)
        mean_vel, std_vel = calculate_stats(velocities)
        mean_p_dtq, std_p_dtq = calculate_stats(peak_driver_tqs)
        mean_ss_dtq, std_ss_dtq = calculate_stats(ss_driver_tqs)
        mean_t_vel, std_t_vel = calculate_stats(vel_times)
        mean_rise, std_rise = calculate_stats(rise_90s)
        
        aggregated.append({
            "rack": rack,
            "torque": torque,
            "num_trials": len(trials),
            "trials_list": [t["run_name"] for t in trials],
            "stats": {
                "peak_angle_mean": round(mean_angle, 2),
                "peak_angle_std": round(std_angle, 2),
                "peak_velocity_mean": round(mean_vel, 2),
                "peak_velocity_std": round(std_vel, 2),
                "peak_driver_torque_mean": round(mean_p_dtq, 2),
                "peak_driver_torque_std": round(std_p_dtq, 2),
                "steady_state_driver_torque_mean": round(mean_ss_dtq, 2),
                "steady_state_driver_torque_std": round(std_ss_dtq, 2),
                "time_to_peak_velocity_mean": round(mean_t_vel, 3),
                "time_to_peak_velocity_std": round(std_t_vel, 3),
                "rise_time_90_mean": round(mean_rise, 3),
                "rise_time_90_std": round(std_rise, 3)
            }
        })
        
    return raw_results, aggregated

def markdown_to_html(md_text):
    """
    Lightweight, robust markdown parser to convert report content into clean HTML.
    Supports headers, horizontal lines, tables, lists, bolding, inline code, and Mermaid blocks.
    """
    lines = md_text.split('\n')
    html_lines = []
    in_list = False
    in_table = False
    in_mermaid = False
    mermaid_lines = []
    
    for line in lines:
        stripped = line.strip()
        
        # Handle Images: ![caption](src)
        img_match = re.match(r'^!\[(.*?)\]\((.*?)\)$', stripped)
        if img_match:
            caption = img_match.group(1)
            src = img_match.group(2)
            html_lines.append(f'<div style="display:flex; flex-direction:column; align-items:center; gap:0.5rem; margin:2rem 0;"><img src="{src}" alt="{caption}" style="max-width:100%; max-height:480px; border-radius:12px; border:1px solid var(--border-color); box-shadow:0 8px 32px rgba(0,0,0,0.3);"/><span style="color:var(--text-secondary); font-size:0.95rem; font-weight:300; font-family:\'Outfit\',sans-serif; margin-top:0.25rem;">{caption}</span></div>')
            continue
            
        # Handle Mermaid Blocks
        if stripped.startswith('```mermaid'):
            in_mermaid = True
            mermaid_lines = []
            continue
        elif stripped == '```' and in_mermaid:
            in_mermaid = False
            mermaid_content = '\n'.join(mermaid_lines)
            html_lines.append(f'<div style="display:flex; justify-content:center; margin: 1.5rem 0;"><pre class="mermaid" style="background: rgba(15, 23, 42, 0.4); border: 1px solid var(--border-color); border-radius: 12px; padding: 1.5rem; display: inline-block;">\n{mermaid_content}\n</pre></div>')
            continue
            
        if in_mermaid:
            mermaid_lines.append(line)
            continue
            
        # Handle Lists
        if stripped.startswith('* ') or stripped.startswith('- '):
            if not in_list:
                html_lines.append('<ul style="margin-left: 2rem; margin-bottom: 1.25rem; list-style-type: disc;">')
                in_list = True
            content = stripped[2:]
            content = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', content)
            content = re.sub(r'`(.*?)`', r'<code style="font-family:\'JetBrains Mono\',monospace; background:rgba(0,0,0,0.3); padding:0.15rem 0.3rem; border-radius:4px; font-size:0.9rem; color:#3b82f6;">\1</code>', content)
            html_lines.append(f'<li style="margin-bottom: 0.5rem; color: var(--text-secondary); font-weight: 300;">{content}</li>')
            continue
        elif in_list:
            html_lines.append('</ul>')
            in_list = False
            
        # Handle Tables
        if stripped.startswith('|') and stripped.endswith('|'):
            if '---' in stripped:
                continue
            columns = [col.strip() for col in stripped.split('|')[1:-1]]
            if not in_table:
                html_lines.append('<div class="table-wrapper" style="margin: 1.5rem 0; overflow-x:auto;"><table style="width:100%; border-collapse:collapse;">')
                html_lines.append('<thead><tr style="border-bottom: 2px solid var(--border-color);">')
                for col in columns:
                    col = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', col)
                    html_lines.append(f'<th style="padding:0.75rem; color:var(--text-secondary); font-size:0.8rem; text-transform:uppercase; font-weight:600; text-align:left;">{col}</th>')
                html_lines.append('</tr></thead><tbody>')
                in_table = True
                continue
            else:
                html_lines.append('<tr style="border-bottom: 1px solid rgba(255, 255, 255, 0.05);">')
                for col in columns:
                    col = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', col)
                    cell_style = 'padding:0.75rem; font-size:0.95rem; font-weight:300;'
                    if 'TTS (237)' in col or 'TTS' in col:
                        col = col.replace('TTS (237)', '<span style="color:#60a5fa; font-weight:500;">TTS (237)</span>')
                    elif 'Passat (311)' in col or 'Passat' in col:
                        col = col.replace('Passat (311)', '<span style="color:#f472b6; font-weight:500;">Passat (311)</span>')
                    html_lines.append(f'<td style="{cell_style}">{col}</td>')
                html_lines.append('</tr>')
                continue
        elif in_table:
            html_lines.append('</tbody></table></div>')
            in_table = False
            
        if not stripped:
            html_lines.append('<div style="height: 0.5rem;"></div>')
            continue
            
        # Headers
        if stripped.startswith('### '):
            content = stripped[4:]
            html_lines.append(f'<h4 style="font-size: 1.25rem; font-weight: 600; color: var(--text-primary); margin-top: 1.5rem; margin-bottom: 0.5rem;">{content}</h4>')
        elif stripped.startswith('## '):
            content = stripped[3:]
            html_lines.append(f'<h3 style="font-size: 1.5rem; font-weight: 700; color: var(--text-primary); margin-top: 2rem; margin-bottom: 0.75rem; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 0.5rem;">{content}</h3>')
        elif stripped.startswith('# '):
            content = stripped[2:]
            html_lines.append(f'<h2 style="font-size: 2rem; font-weight: 800; color: var(--text-primary); margin-top: 1rem; margin-bottom: 1rem; border-left: 4px solid var(--accent-cyan); padding-left: 0.75rem;">{content}</h2>')
        elif stripped.startswith('---'):
            html_lines.append('<hr style="border: 0; border-top: 1px solid rgba(255,255,255,0.08); margin: 2.5rem 0;"/>')
        else:
            # Standard Paragraph
            content = re.sub(r'\*\frac{(.*?)}{(.*?)}', r'\1/\2', stripped) # Basic latex strip if any
            content = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', content)
            content = re.sub(r'`(.*?)`', r'<code style="font-family:\'JetBrains Mono\',monospace; background:rgba(0,0,0,0.3); padding:0.15rem 0.3rem; border-radius:4px; font-size:0.9rem; color:#3b82f6;">\1</code>', content)
            html_lines.append(f'<p style="margin-bottom: 1rem; color: var(--text-secondary); font-weight: 300; font-size: 1.05rem; line-height:1.7;">{content}</p>')
            
    return '\n'.join(html_lines)

def generate_dashboard_page(raw_results, aggregated, output_path):
    """
    Compiles the data results and writes a premium responsive HTML dashboard file.
    Includes custom dark-mode Vanilla CSS styling and interactive CDN-loaded Plotly.js charts.
    """
    json_raw_data = json.dumps(raw_results)
    json_agg_data = json.dumps(aggregated)
    
    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Steering Rack Step Response Analysis</title>
    <!-- Premium Google Font -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <!-- Plotly.js CDN -->
    <script src="https://cdn.plot.ly/plotly-2.24.1.min.js"></script>
    
    <style>
        /* Modern Glassmorphic Dark Theme Style Guide */
        :root {
            --bg-color-1: #070a13;
            --bg-color-2: #0f172a;
            --card-bg: rgba(30, 41, 59, 0.45);
            --card-bg-hover: rgba(30, 41, 59, 0.6);
            --border-color: rgba(255, 255, 255, 0.08);
            --border-hover: rgba(255, 255, 255, 0.15);
            --accent-cyan: #00f2fe;
            --accent-purple: #8a2be2;
            --accent-tts: #3b82f6;      /* Blue for TTS */
            --accent-passat: #ec4899;   /* Pink for Passat */
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --glass-blur: blur(16px);
        }
        
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        
        body {
            font-family: 'Outfit', sans-serif;
            background: linear-gradient(135deg, var(--bg-color-1) 0%, var(--bg-color-2) 100%);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.6;
            overflow-x: hidden;
            padding: 2rem;
        }
        
        /* Layout Structure */
        .container {
            max-width: 1600px;
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            gap: 2rem;
        }
        
        /* Header Block */
        header {
            background: var(--card-bg);
            backdrop-filter: var(--glass-blur);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
            animation: fadeIn 0.8s ease-in-out;
        }
        
        .header-title h1 {
            font-size: 2.2rem;
            font-weight: 800;
            background: linear-gradient(to right, var(--text-primary), var(--text-secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -0.5px;
        }
        
        .header-title p {
            color: var(--text-secondary);
            font-size: 1rem;
            margin-top: 0.25rem;
            font-weight: 300;
        }
        
        .nav-link {
            text-decoration: none;
            color: var(--text-secondary);
            font-weight: 500;
            font-size: 0.95rem;
            padding: 0.5rem 1rem;
            border-radius: 8px;
            transition: all 0.3s;
            border: 1px solid transparent;
        }
        
        .nav-link:hover {
            color: var(--accent-cyan) !important;
            background: rgba(255, 255, 255, 0.03);
        }
        
        .nav-link.active {
            color: var(--accent-cyan) !important;
            background: rgba(0, 242, 254, 0.1) !important;
            border: 1px solid rgba(0, 242, 254, 0.2);
        }
        
        .badge-container {
            display: flex;
            gap: 1rem;
        }
        
        .badge {
            padding: 0.5rem 1rem;
            border-radius: 9999px;
            font-size: 0.85rem;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            border: 1px solid var(--border-color);
        }
        
        .badge-tts {
            background: rgba(59, 130, 246, 0.15);
            color: #60a5fa;
            border-color: rgba(59, 130, 246, 0.3);
        }
        
        .badge-passat {
            background: rgba(236, 72, 153, 0.15);
            color: #f472b6;
            border-color: rgba(236, 72, 153, 0.3);
        }

        /* Interactive Filter Bar */
        .control-panel {
            background: var(--card-bg);
            backdrop-filter: var(--glass-blur);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.5rem;
            display: flex;
            flex-wrap: wrap;
            gap: 1.5rem;
            align-items: center;
            box-shadow: 0 4px 20px 0 rgba(0,0,0,0.15);
        }

        .filter-group {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }

        .filter-group label {
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-secondary);
            font-weight: 600;
        }

        .filter-select {
            background: rgba(15, 23, 42, 0.8);
            border: 1px solid var(--border-color);
            color: var(--text-primary);
            padding: 0.6rem 2rem 0.6rem 1rem;
            border-radius: 8px;
            font-size: 0.95rem;
            font-family: inherit;
            cursor: pointer;
            outline: none;
            transition: all 0.3s ease;
            appearance: none;
            background-image: url("data:image/svg+xml;charset=UTF-8,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2394a3b8' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3e%3cpolyline points='6 9 12 15 18 9'%3e%3c/polyline%3e%3c/svg%3e");
            background-repeat: no-repeat;
            background-position: right 0.7rem center;
            background-size: 1em;
        }

        .filter-select:hover, .filter-select:focus {
            border-color: var(--accent-cyan);
            box-shadow: 0 0 10px rgba(0, 242, 254, 0.15);
        }

        /* Grid Layouts */
        .chart-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(700px, 1fr));
            gap: 2rem;
        }

        .chart-card {
            background: var(--card-bg);
            backdrop-filter: var(--glass-blur);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 1rem;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.2);
            transition: transform 0.3s ease, border-color 0.3s ease;
        }

        .chart-card:hover {
            border-color: var(--border-hover);
            transform: translateY(-2px);
        }

        .chart-title {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            padding-bottom: 0.75rem;
        }

        .chart-title h3 {
            font-size: 1.2rem;
            font-weight: 600;
            color: var(--text-primary);
        }

        .chart-desc {
            font-size: 0.85rem;
            color: var(--text-secondary);
            font-weight: 300;
        }

        .plotly-chart {
            width: 100%;
            height: 480px;
            background: transparent;
        }
        
        .kpi-container {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1.5rem;
        }
        
        .kpi-card {
            background: rgba(30, 41, 59, 0.3);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.25rem;
            text-align: center;
            position: relative;
            overflow: hidden;
            transition: all 0.3s ease;
        }
        
        .kpi-card:hover {
            background: rgba(30, 41, 59, 0.5);
            border-color: rgba(255, 255, 255, 0.12);
        }
        
        .kpi-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 4px;
            height: 100%;
        }
        
        .kpi-tts::before {
            background: var(--accent-tts);
        }
        
        .kpi-passat::before {
            background: var(--accent-passat);
        }
        
        .kpi-label {
            font-size: 0.75rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 0.5rem;
        }
        
        .kpi-value {
            font-size: 1.8rem;
            font-weight: 700;
            color: var(--text-primary);
            line-height: 1.1;
        }
        
        .kpi-sub {
            font-size: 0.8rem;
            color: var(--text-muted);
            margin-top: 0.25rem;
            font-family: 'JetBrains Mono', monospace;
        }

        /* Table Card Styles */
        .table-card {
            background: var(--card-bg);
            backdrop-filter: var(--glass-blur);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 2rem;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.2);
        }

        .table-wrapper {
            overflow-x: auto;
            margin-top: 1rem;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }

        th {
            padding: 1rem;
            border-bottom: 2px solid var(--border-color);
            color: var(--text-secondary);
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            font-weight: 600;
        }

        td {
            padding: 1rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            font-size: 0.95rem;
            color: var(--text-primary);
            font-weight: 300;
        }

        tr:hover td {
            background: rgba(255, 255, 255, 0.02);
            color: #fff;
        }
        
        .row-tts {
            border-left: 3px solid var(--accent-tts);
        }
        
        .row-passat {
            border-left: 3px solid var(--accent-passat);
        }

        .mono {
            font-family: 'JetBrains Mono', monospace;
        }

        /* Keyframes */
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        @media (max-width: 768px) {
            body {
                padding: 1rem;
            }
            header {
                flex-direction: column;
                align-items: flex-start;
                gap: 1rem;
            }
            .chart-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        
        <!-- Header -->
        <header>
            <div class="header-title">
                <h1>Steering Rack Dynamic Response</h1>
                <p>Advanced comparative step-response and torque coupling analysis</p>
                <div class="badge-container" style="margin-top: 0.75rem; display: flex; gap: 0.75rem;">
                    <span class="badge badge-tts">Rack 237: Audi TTS Dataset</span>
                    <span class="badge badge-passat">Rack 311: Passat NMS Dataset</span>
                </div>
            </div>
            <div style="display: flex; align-items: center; gap: 1.5rem;">
                <nav style="display: flex; gap: 0.5rem; background: rgba(15,23,42,0.4); border: 1px solid var(--border-color); border-radius: 12px; padding: 0.5rem;">
                    <a href="index.html" class="nav-link active">Graphs</a>
                    <a href="notes.html" class="nav-link">my notes</a>
                    <a href="analysis.html" class="nav-link">AIs useful info</a>
                </nav>
                <a href="https://github.com/dsparks156x/pq35rackanalysis" target="_blank" style="display: flex; align-items: center; gap: 0.5rem; text-decoration: none; color: var(--text-secondary); background: rgba(255,255,255,0.03); border: 1px solid var(--border-color); border-radius: 8px; padding: 0.5rem 1rem; font-size: 0.9rem; font-weight: 500; transition: all 0.3s;" onmouseover="this.style.color='var(--accent-cyan)'; this.style.borderColor='rgba(0, 242, 254, 0.3)'; this.style.boxShadow='0 0 10px rgba(0, 242, 254, 0.15)';" onmouseout="this.style.color='var(--text-secondary)'; this.style.borderColor='var(--border-color)'; this.style.boxShadow='none';">
                    <svg height="16" width="16" viewBox="0 0 16 16" fill="currentColor" style="display: inline-block; vertical-align: middle;">
                        <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"></path>
                    </svg>
                    <span>Repository</span>
                </a>
            </div>
        </header>

        <!-- Global Notice Banner -->
        <div style="background: rgba(0, 242, 254, 0.04); border: 1px solid rgba(0, 242, 254, 0.15); border-radius: 12px; padding: 1rem 1.5rem; display: flex; align-items: center; gap: 0.75rem; box-shadow: 0 4px 20px rgba(0,0,0,0.15); animation: fadeIn 0.8s ease-in-out;">
            <span style="font-size: 1.25rem; vertical-align: middle;">💡</span>
            <p style="color: var(--text-secondary); font-size: 0.95rem; font-weight: 300; margin: 0; line-height: 1.5;">
                For custom testing comments, firmware patch offsets, standstill activation overrides, and torque ceilings, please see the dedicated <a href="notes.html" style="color: var(--accent-cyan); font-weight: 500; text-decoration: none; border-bottom: 1px dashed rgba(0, 242, 254, 0.4); padding-bottom: 1px; transition: all 0.3s;" onmouseover="this.style.color='#fff'; this.style.borderBottomColor='#fff';" onmouseout="this.style.color='var(--accent-cyan)'; this.style.borderBottomColor='rgba(0, 242, 254, 0.4)';">my notes</a> page.
            </p>
        </div>

        <!-- Dynamic Filter Controls -->
        <div class="control-panel">
            <div class="filter-group">
                <label for="filter-torque">Step Command (cNm)</label>
                <select id="filter-torque" class="filter-select" onchange="updateDashboard()">
                    <option value="all">All Torques</option>
                    <option value="150">150 cNm</option>
                    <option value="300">300 cNm</option>
                    <option value="400">400 cNm</option>
                    <option value="500">500 cNm</option>
                    <option value="600">600 cNm</option>
                    <option value="632" selected>632 cNm (Peak)</option>
                </select>
            </div>
            
            <div class="filter-group" style="flex-grow: 1;">
                <p style="color: var(--text-secondary); font-size: 0.9rem; font-weight: 300;">
                    Select a commanded torque above to filter the aligned step response transient and phase portrait charts. The statistical summaries compare overall performance.
                </p>
            </div>
        </div>
        
        <!-- KPI Cards -->
        <div class="kpi-container" id="kpi-deck">
            <!-- Populated dynamically via JS -->
        </div>

        <!-- Charts Grid 1 -->
        <div class="chart-grid">
            
            <!-- Angle Response Chart -->
            <div class="chart-card">
                <div class="chart-title">
                    <div>
                        <h3>Wheel Angle Step Response</h3>
                        <span class="chart-desc">Normalized time-aligned deflection profile (HCA active at t=0s)</span>
                    </div>
                </div>
                <div id="chart-angle" class="plotly-chart"></div>
            </div>

            <!-- Velocity Response Chart -->
            <div class="chart-card">
                <div class="chart-title">
                    <div>
                        <h3>Angular Velocity Profile</h3>
                        <span class="chart-desc">Comparative step angular speed curves (degrees per second)</span>
                    </div>
                </div>
                <div id="chart-velocity" class="plotly-chart"></div>
            </div>

        </div>

        <!-- Charts Grid 2 (Phase Space) -->
        <div class="chart-grid">
            
            <!-- Velocity vs Angle Phase portrait -->
            <div class="chart-card" style="grid-column: span 2;">
                <div class="chart-title" style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem;">
                    <div>
                        <h3>Angular Velocity vs. Wheel Angle Phase Portrait</h3>
                        <span class="chart-desc">Dynamic phase-space trajectories (acceleration loops, breakaway arcs, and mechanical stops)</span>
                    </div>
                    <div class="filter-group" style="display: flex; flex-direction: column; gap: 0.25rem;">
                        <label for="filter-phase-torque" style="font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-secondary); font-weight: 600;">Phase Torque</label>
                        <select id="filter-phase-torque" class="filter-select" onchange="updatePhaseChart()" style="padding: 0.4rem 2rem 0.4rem 0.8rem; font-size: 0.85rem; height: auto;">
                            <option value="all">All Torques</option>
                            <option value="150">150 cNm</option>
                            <option value="300">300 cNm</option>
                            <option value="400">400 cNm</option>
                            <option value="500">500 cNm</option>
                            <option value="600">600 cNm</option>
                            <option value="632" selected>632 cNm (Peak)</option>
                        </select>
                    </div>
                </div>
                <div id="chart-phase" class="plotly-chart" style="height: 520px;"></div>
            </div>

        </div>

        <!-- Charts Grid 3 -->
        <div class="chart-grid">
            
            <!-- Peak Velocity vs Torque -->
            <div class="chart-card">
                <div class="chart-title">
                    <div>
                        <h3>Peak Response Speed vs. Commanded Torque</h3>
                        <span class="chart-desc">Quantifying speed limits and standard deviations across trials</span>
                    </div>
                </div>
                <div id="chart-peak-velocity" class="plotly-chart"></div>
            </div>

            <!-- Max Angle vs Torque -->
            <div class="chart-card">
                <div class="chart-title">
                    <div>
                        <h3>Maximum Angle Deflection vs. Commanded Torque</h3>
                        <span class="chart-desc">Analyzing saturation points and torque-limited travel bounds</span>
                    </div>
                </div>
                <div id="chart-max-angle" class="plotly-chart"></div>
            </div>

        </div>

        <!-- Charts Grid 4 -->
        <div class="chart-grid">
            
            <!-- Driver Torque vs Commanded Torque -->
            <div class="chart-card" style="grid-column: span 2;">
                <div class="chart-title">
                    <div>
                        <h3>Driver Torque Feedback vs. Commanded HCA Torque</h3>
                        <span class="chart-desc">Analyzing driver feedback coupling during dynamic maneuvers</span>
                    </div>
                </div>
                <div id="chart-driver-coupling" class="plotly-chart"></div>
            </div>

        </div>

        <!-- Statistical Aggregations Grid -->
        <div class="table-card">
            <h2 style="font-weight: 700; margin-bottom: 0.5rem; font-size: 1.4rem;">Statistical Summary Table</h2>
            <p style="color: var(--text-secondary); font-size: 0.95rem; font-weight: 300; margin-bottom: 1.5rem;">
                Comparison matrix for both steering racks displaying the mean and standard deviation (deviation) across all available runs.
            </p>
            <div class="table-wrapper">
                <table id="summary-table">
                    <thead>
                        <tr>
                            <th>Rack</th>
                            <th>Command Torque</th>
                            <th>Trials</th>
                            <th>Peak Angle (deg)</th>
                            <th>Peak Velocity (deg/s)</th>
                            <th>Rise Time 90% (s)</th>
                            <th>Peak Driver Feedback (cNm)</th>
                            <th>SS Driver Feedback (cNm)</th>
                        </tr>
                    </thead>
                    <tbody>
                        <!-- Populated dynamically via JS -->
                    </tbody>
                </table>
            </div>
        </div>

    </div>

    <!-- Data Injection & Dashboard Controller -->
    <script>
        const rawData = {json_raw_data};
        const aggData = {json_agg_data};
        
        // Custom Plotly Template Settings to integrate perfectly with the page style
        const plotlyLayoutTemplate = {
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor: 'rgba(0,0,0,0)',
            font: {
                family: 'Outfit, sans-serif',
                color: '#e2e8f0'
            },
            margin: { t: 25, b: 50, l: 50, r: 25 },
            xaxis: {
                gridcolor: 'rgba(255,255,255,0.05)',
                linecolor: 'rgba(255,255,255,0.1)',
                zerolinecolor: 'rgba(255,255,255,0.15)',
                tickfont: { size: 11 }
            },
            yaxis: {
                gridcolor: 'rgba(255,255,255,0.05)',
                linecolor: 'rgba(255,255,255,0.1)',
                zerolinecolor: 'rgba(255,255,255,0.15)',
                tickfont: { size: 11 }
            },
            legend: {
                font: { size: 12 },
                orientation: 'h',
                yanchor: 'bottom',
                y: 1.02,
                xanchor: 'right',
                x: 1
            }
        };

        // Initialize the UI elements and draw all charts
        window.onload = function() {
            buildAggregatedCharts();
            updateDashboard();
            updatePhaseChart();
            buildSummaryTable();
        };

        function updateDashboard() {
            const selectedTorque = document.getElementById("filter-torque").value;
            
            // Filter raw data according to selection
            let filteredTrials = rawData;
            if (selectedTorque !== "all") {
                const tVal = parseInt(selectedTorque);
                filteredTrials = rawData.filter(d => d.torque === tVal);
            }

            buildStepAngleChart(filteredTrials);
            buildStepVelocityChart(filteredTrials);
            updateKPICards(selectedTorque);
        }

        function updatePhaseChart() {
            const selectedTorque = document.getElementById("filter-phase-torque").value;
            let filteredTrials = rawData;
            if (selectedTorque !== "all") {
                const tVal = parseInt(selectedTorque);
                filteredTrials = rawData.filter(d => d.torque === tVal);
            }
            buildStepPhaseChart(filteredTrials);
        }

        function updateKPICards(selectedTorque) {
            const kpiDeck = document.getElementById("kpi-deck");
            kpiDeck.innerHTML = ""; // Clear existing

            // Compute high-level comparisons for selected configuration
            let ttsTrials = rawData.filter(d => d.rack === "237");
            let passatTrials = rawData.filter(d => d.rack === "311");

            if (selectedTorque !== "all") {
                const tVal = parseInt(selectedTorque);
                ttsTrials = ttsTrials.filter(d => d.torque === tVal);
                passatTrials = passatTrials.filter(d => d.torque === tVal);
            }

            const avgPeakTTS = ttsTrials.reduce((sum, d) => sum + d.metrics.peak_angle, 0) / (ttsTrials.length || 1);
            const avgVelTTS = ttsTrials.reduce((sum, d) => sum + d.metrics.peak_velocity, 0) / (ttsTrials.length || 1);
            const avgRiseTTS = ttsTrials.reduce((sum, d) => sum + d.metrics.rise_time_90, 0) / (ttsTrials.length || 1);

            const avgPeakPassat = passatTrials.reduce((sum, d) => sum + d.metrics.peak_angle, 0) / (passatTrials.length || 1);
            const avgVelPassat = passatTrials.reduce((sum, d) => sum + d.metrics.peak_velocity, 0) / (passatTrials.length || 1);
            const avgRisePassat = passatTrials.reduce((sum, d) => sum + d.metrics.rise_time_90, 0) / (passatTrials.length || 1);

            const labelSuffix = selectedTorque === "all" ? " (All Sweeps)" : ` (@${selectedTorque} cNm)`;

            kpiDeck.innerHTML = `
                <div class="kpi-card kpi-tts">
                    <div class="kpi-label">TTS 237 Avg Peak Angle</div>
                    <div class="kpi-value">${avgPeakTTS.toFixed(1)}°</div>
                    <div class="kpi-sub">${ttsTrials.length} active trials${labelSuffix}</div>
                </div>
                <div class="kpi-card kpi-passat">
                    <div class="kpi-label">Passat 311 Avg Peak Angle</div>
                    <div class="kpi-value">${avgPeakPassat.toFixed(1)}°</div>
                    <div class="kpi-sub">${passatTrials.length} active trials${labelSuffix}</div>
                </div>
                <div class="kpi-card kpi-tts">
                    <div class="kpi-label">TTS 237 Avg Velocity</div>
                    <div class="kpi-value">${avgVelTTS.toFixed(0)} °/s</div>
                    <div class="kpi-sub">Transient speed performance</div>
                </div>
                <div class="kpi-card kpi-passat">
                    <div class="kpi-label">Passat 311 Avg Velocity</div>
                    <div class="kpi-value">${avgVelPassat.toFixed(0)} °/s</div>
                    <div class="kpi-sub">Transient speed performance</div>
                </div>
                <div class="kpi-card kpi-tts">
                    <div class="kpi-label">TTS 237 90% Rise Time</div>
                    <div class="kpi-value">${avgRiseTTS.toFixed(3)} s</div>
                    <div class="kpi-sub">Responsiveness latency</div>
                </div>
                <div class="kpi-card kpi-passat">
                    <div class="kpi-label">Passat 311 90% Rise Time</div>
                    <div class="kpi-value">${avgRisePassat.toFixed(3)} s</div>
                    <div class="kpi-sub">Responsiveness latency</div>
                </div>
            `;
        }

        function buildStepAngleChart(trials) {
            const data = [];
            
            trials.forEach(t => {
                const isTTS = t.rack === "237";
                data.push({
                    x: t.series.time,
                    y: t.series.angle,
                    mode: 'lines',
                    name: `${isTTS ? 'TTS (237)' : 'Passat (311)'} - ${t.torque} cNm (${t.run_name})`,
                    line: {
                        color: isTTS ? `rgba(59, 130, 246, ${t.torque / 632 * 0.7 + 0.3})` : `rgba(236, 72, 153, ${t.torque / 632 * 0.7 + 0.3})`,
                        width: isTTS ? 2.5 : 2
                    }
                });
            });

            const layout = JSON.parse(JSON.stringify(plotlyLayoutTemplate));
            layout.xaxis.title = 'Aligned Time (seconds)';
            layout.yaxis.title = 'Wheel Angle (degrees)';
            layout.showlegend = trials.length <= 12; // Hide messy legends if too many traces are shown
            
            Plotly.newPlot('chart-angle', data, layout);
        }

        function buildStepVelocityChart(trials) {
            const data = [];
            
            trials.forEach(t => {
                const isTTS = t.rack === "237";
                data.push({
                    x: t.series.time,
                    y: t.series.velocity,
                    mode: 'lines',
                    name: `${isTTS ? 'TTS (237)' : 'Passat (311)'} - ${t.torque} cNm (${t.run_name})`,
                    line: {
                        color: isTTS ? `rgba(59, 130, 246, ${t.torque / 632 * 0.7 + 0.3})` : `rgba(236, 72, 153, ${t.torque / 632 * 0.7 + 0.3})`,
                        width: isTTS ? 2.5 : 2
                    }
                });
            });

            const layout = JSON.parse(JSON.stringify(plotlyLayoutTemplate));
            layout.xaxis.title = 'Aligned Time (seconds)';
            layout.yaxis.title = 'Angular Velocity (degrees/second)';
            layout.showlegend = trials.length <= 12;
            
            Plotly.newPlot('chart-velocity', data, layout);
        }

        function buildStepPhaseChart(trials) {
            const data = [];
            let seenTTS = false;
            let seenPassat = false;
            
            trials.forEach(t => {
                const isTTS = t.rack === "237";
                let showLegend = false;
                
                if (isTTS && !seenTTS) {
                    showLegend = true;
                    seenTTS = true;
                } else if (!isTTS && !seenPassat) {
                    showLegend = true;
                    seenPassat = true;
                }
                
                data.push({
                    x: t.series.angle,
                    y: t.series.velocity,
                    mode: 'lines',
                    name: isTTS ? 'TTS (237)' : 'Passat (311)',
                    showlegend: showLegend,
                    legendgroup: isTTS ? 'tts' : 'passat',
                    line: {
                        color: isTTS ? `rgba(59, 130, 246, ${t.torque / 632 * 0.7 + 0.3})` : `rgba(236, 72, 153, ${t.torque / 632 * 0.7 + 0.3})`,
                        width: isTTS ? 2.5 : 2
                    },
                    hovertemplate: `<b>${isTTS ? 'TTS (237)' : 'Passat (311)'}</b><br>Torque: ${t.torque} cNm<br>Run: ${t.run_name}<br>Angle: %{x}°<br>Velocity: %{y}°/s<extra></extra>`
                });
            });

            const layout = JSON.parse(JSON.stringify(plotlyLayoutTemplate));
            layout.xaxis.title = 'Wheel Angle (degrees)';
            layout.yaxis.title = 'Angular Velocity (degrees/second)';
            layout.showlegend = true;
            
            Plotly.newPlot('chart-phase', data, layout);
        }

        function buildAggregatedCharts() {
            // Sort stats by torque command ascending
            const ttsAgg = aggData.filter(d => d.rack === "237").sort((a,b) => a.torque - b.torque);
            const passatAgg = aggData.filter(d => d.rack === "311").sort((a,b) => a.torque - b.torque);

            // 1. Peak Velocity chart with Error Bars
            const traceVelTTS = {
                x: ttsAgg.map(d => d.torque),
                y: ttsAgg.map(d => d.stats.peak_velocity_mean),
                error_y: {
                    type: 'data',
                    array: ttsAgg.map(d => d.stats.peak_velocity_std),
                    visible: true,
                    color: '#93c5fd'
                },
                mode: 'lines+markers',
                name: 'TTS 237 (Mean ± SD)',
                line: { color: '#3b82f6', width: 3 },
                marker: { size: 8 }
            };

            const traceVelPassat = {
                x: passatAgg.map(d => d.torque),
                y: passatAgg.map(d => d.stats.peak_velocity_mean),
                error_y: {
                    type: 'data',
                    array: passatAgg.map(d => d.stats.peak_velocity_std),
                    visible: true,
                    color: '#f9a8d4'
                },
                mode: 'lines+markers',
                name: 'Passat 311 (Mean ± SD)',
                line: { color: '#ec4899', width: 3 },
                marker: { size: 8 }
            };

            const layoutVel = JSON.parse(JSON.stringify(plotlyLayoutTemplate));
            layoutVel.xaxis.title = 'Commanded Torque (cNm)';
            layoutVel.yaxis.title = 'Peak Angular Velocity (deg/s)';
            layoutVel.legend.y = 1.05;
            
            Plotly.newPlot('chart-peak-velocity', [traceVelTTS, traceVelPassat], layoutVel);

            // 2. Max Angle chart with Error Bars
            const traceAngleTTS = {
                x: ttsAgg.map(d => d.torque),
                y: ttsAgg.map(d => d.stats.peak_angle_mean),
                error_y: {
                    type: 'data',
                    array: ttsAgg.map(d => d.stats.peak_angle_std),
                    visible: true,
                    color: '#93c5fd'
                },
                mode: 'lines+markers',
                name: 'TTS 237 (Mean ± SD)',
                line: { color: '#3b82f6', width: 3 },
                marker: { size: 8 }
            };

            const traceAnglePassat = {
                x: passatAgg.map(d => d.torque),
                y: passatAgg.map(d => d.stats.peak_angle_mean),
                error_y: {
                    type: 'data',
                    array: passatAgg.map(d => d.stats.peak_angle_std),
                    visible: true,
                    color: '#f9a8d4'
                },
                mode: 'lines+markers',
                name: 'Passat 311 (Mean ± SD)',
                line: { color: '#ec4899', width: 3 },
                marker: { size: 8 }
            };

            const layoutAngle = JSON.parse(JSON.stringify(plotlyLayoutTemplate));
            layoutAngle.xaxis.title = 'Commanded Torque (cNm)';
            layoutAngle.yaxis.title = 'Maximum Angle Deflection (deg)';
            layoutAngle.legend.y = 1.05;

            Plotly.newPlot('chart-max-angle', [traceAngleTTS, traceAnglePassat], layoutAngle);

            // 3. Driver Feedback coupling chart (Scatter plot + trendline)
            const driverDataPoints = rawData.map(d => ({
                x: d.torque,
                y: d.metrics.steady_state_driver_torque,
                rack: d.rack,
                name: d.basename
            }));

            const ttsScatter = driverDataPoints.filter(p => p.rack === "237");
            const passatScatter = driverDataPoints.filter(p => p.rack === "311");

            const traceScatterTTS = {
                x: ttsScatter.map(p => p.x),
                y: ttsScatter.map(p => p.y),
                mode: 'markers',
                name: 'TTS 237 Feedback',
                marker: {
                    color: 'rgba(59, 130, 246, 0.7)',
                    size: 10,
                    line: { color: '#3b82f6', width: 1 }
                },
                text: ttsScatter.map(p => p.name),
                type: 'scatter'
            };

            const traceScatterPassat = {
                x: passatScatter.map(p => p.x),
                y: passatScatter.map(p => p.y),
                mode: 'markers',
                name: 'Passat 311 Feedback',
                marker: {
                    color: 'rgba(236, 72, 153, 0.7)',
                    size: 10,
                    line: { color: '#ec4899', width: 1 }
                },
                text: passatScatter.map(p => p.name),
                type: 'scatter'
            };

            // Draw fit lines
            const fitTTS = linearRegression(ttsScatter.map(p => p.x), ttsScatter.map(p => p.y));
            const fitPassat = linearRegression(passatScatter.map(p => p.x), passatScatter.map(p => p.y));

            const xFit = [150, 650];
            const traceFitTTS = {
                x: xFit,
                y: xFit.map(x => fitTTS.slope * x + fitTTS.intercept),
                mode: 'lines',
                name: `TTS Trend (R² = ${fitTTS.r2.toFixed(2)})`,
                line: { color: '#3b82f6', dash: 'dash', width: 1.5 }
            };

            const traceFitPassat = {
                x: xFit,
                y: xFit.map(x => fitPassat.slope * x + fitPassat.intercept),
                mode: 'lines',
                name: `Passat Trend (R² = ${fitPassat.r2.toFixed(2)})`,
                line: { color: '#ec4899', dash: 'dash', width: 1.5 }
            };

            const layoutDriver = JSON.parse(JSON.stringify(plotlyLayoutTemplate));
            layoutDriver.xaxis.title = 'Commanded HCA Torque (cNm)';
            layoutDriver.yaxis.title = 'Opposing Steady-State Driver Torque (cNm)';
            
            Plotly.newPlot('chart-driver-coupling', [
                traceScatterTTS, traceScatterPassat, traceFitTTS, traceFitPassat
            ], layoutDriver);
        }

        // Helper function for linear regression fit
        function linearRegression(x, y) {
            const n = x.length;
            const sumX = x.reduce((a,b) => a+b, 0);
            const sumY = y.reduce((a,b) => a+b, 0);
            const sumXY = x.reduce((sum, val, i) => sum + val * y[i], 0);
            const sumXX = x.reduce((sum, val) => sum + val * val, 0);
            
            const slope = (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX);
            const intercept = (sumY - slope * sumX) / n;
            
            // Calculate R2
            const yMean = sumY / n;
            const ssTot = y.reduce((sum, val) => sum + (val - yMean) ** 2, 0);
            const ssRes = y.reduce((sum, val, i) => {
                const pred = slope * x[i] + intercept;
                return sum + (val - pred) ** 2;
            }, 0);
            const r2 = 1 - (ssRes / (ssTot || 1));
            
            return { slope, intercept, r2 };
        }

        function buildSummaryTable() {
            const tbody = document.querySelector("#summary-table tbody");
            tbody.innerHTML = "";

            // Group stats by rack, sorted by torque
            const sortedAgg = aggData.sort((a,b) => {
                if (a.rack !== b.rack) return a.rack.localeCompare(b.rack);
                return a.torque - b.torque;
            });

            sortedAgg.forEach(row => {
                const isTTS = row.rack === "237";
                const rowClass = isTTS ? "row-tts" : "row-passat";
                const rackName = isTTS ? "TTS (237)" : "Passat NMS (311)";
                
                const tr = document.createElement("tr");
                tr.className = rowClass;
                tr.innerHTML = `
                    <td style="font-weight: 500;">${rackName}</td>
                    <td class="mono">${row.torque} cNm</td>
                    <td>${row.num_trials} (${row.trials_list.join(", ")})</td>
                    <td class="mono">${row.stats.peak_angle_mean.toFixed(1)}° ± ${row.stats.peak_angle_std.toFixed(1)}</td>
                    <td class="mono">${row.stats.peak_velocity_mean.toFixed(0)} ± ${row.stats.peak_velocity_std.toFixed(0)}</td>
                    <td class="mono">${row.stats.rise_time_90_mean.toFixed(3)}s</td>
                    <td class="mono">${row.stats.peak_driver_torque_mean.toFixed(1)} ± ${row.stats.peak_driver_torque_std.toFixed(1)}</td>
                    <td class="mono">${row.stats.steady_state_driver_torque_mean.toFixed(1)} ± ${row.stats.steady_state_driver_torque_std.toFixed(1)}</td>
                `;
                tbody.appendChild(tr);
            });
        }
    </script>
</body>
</html>
"""
    
    # Perform raw string placeholder replacement
    html_content = html_template.replace("{json_raw_data}", json_raw_data).replace("{json_agg_data}", json_agg_data)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"Main Dashboard compiled successfully at: {output_path}")

def generate_text_page(title, nav_active, body_html, output_path):
    """
    Compiles a style-consistent HTML text page rendering parsed markdown data.
    Provides standard back-end navigation tab activations.
    """
    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page_title}</title>
    <!-- Premium Google Font -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <!-- Mermaid.js CDN for Flowcharts -->
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10.6.1/dist/mermaid.min.js"></script>
    
    <style>
        /* Shared Stylesheets for Absolute Visual Consistency */
        :root {
            --bg-color-1: #070a13;
            --bg-color-2: #0f172a;
            --card-bg: rgba(30, 41, 59, 0.45);
            --card-bg-hover: rgba(30, 41, 59, 0.6);
            --border-color: rgba(255, 255, 255, 0.08);
            --border-hover: rgba(255, 255, 255, 0.15);
            --accent-cyan: #00f2fe;
            --accent-purple: #8a2be2;
            --accent-tts: #3b82f6;
            --accent-passat: #ec4899;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --glass-blur: blur(16px);
        }
        
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        
        body {
            font-family: 'Outfit', sans-serif;
            background: linear-gradient(135deg, var(--bg-color-1) 0%, var(--bg-color-2) 100%);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.6;
            overflow-x: hidden;
            padding: 2rem;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            gap: 2rem;
        }
        
        header {
            background: var(--card-bg);
            backdrop-filter: var(--glass-blur);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
        }
        
        .header-title h1 {
            font-size: 2.2rem;
            font-weight: 800;
            background: linear-gradient(to right, var(--text-primary), var(--text-secondary));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -0.5px;
        }
        
        .header-title p {
            color: var(--text-secondary);
            font-size: 1rem;
            margin-top: 0.25rem;
            font-weight: 300;
        }
        
        .nav-link {
            text-decoration: none;
            color: var(--text-secondary);
            font-weight: 500;
            font-size: 0.95rem;
            padding: 0.5rem 1rem;
            border-radius: 8px;
            transition: all 0.3s;
            border: 1px solid transparent;
        }
        
        .nav-link:hover {
            color: var(--accent-cyan) !important;
            background: rgba(255, 255, 255, 0.03);
        }
        
        .nav-link.active {
            color: var(--accent-cyan) !important;
            background: rgba(0, 242, 254, 0.1) !important;
            border: 1px solid rgba(0, 242, 254, 0.2);
        }
        
        .article-card {
            background: var(--card-bg);
            backdrop-filter: var(--glass-blur);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 3rem;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.2);
        }
        
        .badge-container {
            display: flex;
            gap: 1rem;
        }
        
        .badge {
            padding: 0.5rem 1rem;
            border-radius: 9999px;
            font-size: 0.85rem;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            border: 1px solid var(--border-color);
        }
        
        .badge-tts {
            background: rgba(59, 130, 246, 0.15);
            color: #60a5fa;
            border-color: rgba(59, 130, 246, 0.3);
        }
        
        .badge-passat {
            background: rgba(236, 72, 153, 0.15);
            color: #f472b6;
            border-color: rgba(236, 72, 153, 0.3);
        }
        
        /* Table styles inside articles */
        .table-wrapper {
            overflow-x: auto;
            margin: 1.5rem 0;
            border: 1px solid var(--border-color);
            border-radius: 12px;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }
        
        th {
            padding: 1rem;
            background: rgba(15, 23, 42, 0.4);
            border-bottom: 2px solid var(--border-color);
            color: var(--text-secondary);
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            font-weight: 600;
        }
        
        td {
            padding: 1rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            font-size: 0.95rem;
            color: var(--text-primary);
            font-weight: 300;
        }
        
        tr:hover td {
            background: rgba(255, 255, 255, 0.01);
        }
    </style>
</head>
<body>
    <div class="container">
        
        <header>
            <div class="header-title">
                <h1>Steering Rack Dynamic Response</h1>
                <p>Advanced comparative step-response and torque coupling analysis</p>
                <div class="badge-container" style="margin-top: 0.75rem; display: flex; gap: 0.75rem;">
                    <span class="badge badge-tts">Rack 237: Audi TTS Dataset</span>
                    <span class="badge badge-passat">Rack 311: Passat NMS Dataset</span>
                </div>
            </div>
            <div style="display: flex; align-items: center; gap: 1.5rem;">
                <nav style="display: flex; gap: 0.5rem; background: rgba(15,23,42,0.4); border: 1px solid var(--border-color); border-radius: 12px; padding: 0.5rem;">
                    <a href="index.html" class="nav-link {active_dashboard}">Graphs</a>
                    <a href="notes.html" class="nav-link {active_notes}">my notes</a>
                    <a href="analysis.html" class="nav-link {active_analysis}">AIs useful info</a>
                </nav>
                <a href="https://github.com/dsparks156x/pq35rackanalysis" target="_blank" style="display: flex; align-items: center; gap: 0.5rem; text-decoration: none; color: var(--text-secondary); background: rgba(255,255,255,0.03); border: 1px solid var(--border-color); border-radius: 8px; padding: 0.5rem 1rem; font-size: 0.9rem; font-weight: 500; transition: all 0.3s;" onmouseover="this.style.color='var(--accent-cyan)'; this.style.borderColor='rgba(0, 242, 254, 0.3)'; this.style.boxShadow='0 0 10px rgba(0, 242, 254, 0.15)';" onmouseout="this.style.color='var(--text-secondary)'; this.style.borderColor='var(--border-color)'; this.style.boxShadow='none';">
                    <svg height="16" width="16" viewBox="0 0 16 16" fill="currentColor" style="display: inline-block; vertical-align: middle;">
                        <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"></path>
                    </svg>
                    <span>Repository</span>
                </a>
            </div>
        </header>

        <div class="article-card">
            {article_content}
        </div>

    </div>

    <script>
        window.onload = function() {
            // Initialize Mermaid flowcharts in dark mode
            mermaid.initialize({
                startOnLoad: true,
                theme: 'dark',
                securityLevel: 'loose',
                themeVariables: {
                    background: '#1e293b',
                    primaryColor: '#0f172a',
                    primaryTextColor: '#f8fafc',
                    lineColor: '#00f2fe'
                }
            });
        };
    </script>
</body>
</html>
"""
    # Build navigation active flags
    active_dash = "active" if nav_active == "dashboard" else ""
    active_anal = "active" if nav_active == "analysis" else ""
    active_note = "active" if nav_active == "notes" else ""
    
    html_content = html_template.replace("{page_title}", title)\
                                 .replace("{active_dashboard}", active_dash)\
                                 .replace("{active_analysis}", active_anal)\
                                 .replace("{active_notes}", active_note)\
                                 .replace("{article_content}", body_html)
                                 
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"Compiled text page successfully at: {output_path}")

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, "data")
    
    report_path = os.path.join(base_dir, "analysis_report.md")
    notes_path = os.path.join(base_dir, "notes.md")
    
    dashboard_out = os.path.join(base_dir, "index.html")
    analysis_out = os.path.join(base_dir, "analysis.html")
    notes_out = os.path.join(base_dir, "notes.html")
    
    # Process dynamic CSV data sweeps
    print(f"Scanning '{data_dir}' for steering rack files...")
    raw, agg = process_all_data(data_dir)
    print(f"Processed {len(raw)} successful runs across {len(agg)} distinct system configurations.")
    
    # 1. Generate Dashboard Page (index.html)
    generate_dashboard_page(raw, agg, dashboard_out)
    
    # 2. Generate Analysis Report Page (analysis.html)
    print(f"Loading analysis report from '{report_path}'...")
    if os.path.exists(report_path):
        with open(report_path, 'r', encoding='utf-8') as f:
            md_text = f.read()
        report_html = markdown_to_html(md_text)
    else:
        report_html = "<p style='color: var(--accent-passat);'>Error: analysis_report.md not found in workspace.</p>"
    generate_text_page("Steering Rack Response Analysis Report", "analysis", report_html, analysis_out)
    
    # 3. Generate Engineering Notes Page (notes.html)
    print(f"Loading engineering notes from '{notes_path}'...")
    if os.path.exists(notes_path):
        with open(notes_path, 'r', encoding='utf-8') as f:
            md_text = f.read()
        notes_html = markdown_to_html(md_text)
    else:
        notes_html = "<p style='color: var(--accent-passat);'>Error: notes.md not found in workspace. Create a notes.md file in the workspace directory.</p>"
    generate_text_page("Steering Rack Patcher & Reference Notes", "notes", notes_html, notes_out)
    
    print("Multi-page build completely completed for GitHub Pages deployment!")
