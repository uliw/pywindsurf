#!/usr/bin/env python3
"""Analyze tcx data from health apps with metrics that are
of interest to water sport.
"""
import sys
import os
import xml.etree.ElementTree as ET
from datetime import datetime
import math

try:
    import folium
    HAS_FOLIUM = True
except ImportError:
    HAS_FOLIUM = False

def haversine(lat1, lon1, lat2, lon2):
    """Calculate the great-circle distance between two points on the Earth's surface (in meters)."""
    R = 6371000  # radius of Earth in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def bearing(lat1, lon1, lat2, lon2):
    """Calculate the bearing/heading from point 1 to point 2 (in degrees)."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_lon = math.radians(lon2 - lon1)
    y = math.sin(delta_lon) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lon)
    b = math.atan2(y, x)
    return math.degrees(b)

def format_duration(seconds):
    """Format duration in seconds into HH:MM:SS format."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"

def parse_tcx(file_path):
    """Parse the TCX file and return list of trackpoints with time, latitude, longitude, and distance."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found at '{file_path}'")
        
    try:
        tree = ET.parse(file_path)
    except ET.ParseError as e:
        raise ValueError(f"Error parsing XML file '{file_path}': {e}") from e
        
    root = tree.getroot()
    ns = {'ns': 'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2'}
    trackpoints_el = root.findall('.//ns:Trackpoint', ns)
    
    points = []
    for tp in trackpoints_el:
        time_el = tp.find('ns:Time', ns)
        lat_el = tp.find('ns:Position/ns:LatitudeDegrees', ns)
        lon_el = tp.find('ns:Position/ns:LongitudeDegrees', ns)
        dist_el = tp.find('ns:DistanceMeters', ns)
        
        if time_el is None or lat_el is None or lon_el is None or dist_el is None:
            continue
            
        try:
            time_val = time_el.text
            lat_val = float(lat_el.text)
            lon_val = float(lon_el.text)
            dist_val = float(dist_el.text)
            points.append({
                'time_str': time_val,
                'time': datetime.fromisoformat(time_val),
                'lat': lat_val,
                'lon': lon_val,
                'dist': dist_val
            })
        except ValueError:
            continue
            
    total_calories = 0
    has_calories = False
    calories_el = root.findall('.//ns:Calories', ns)
    for cel in calories_el:
        try:
            total_calories += int(cel.text)
            has_calories = True
        except ValueError:
            pass
            
    return points, total_calories, has_calories

def get_speed_bin_info(speed, unit, cutoff_speed, bin_interval, num_bins_above, colormap):
    if speed <= cutoff_speed:
        return 0, f"≤ {cutoff_speed:g} {unit}", "#808080"
        
    if num_bins_above <= 0:
        return 0, f"≤ {cutoff_speed:g} {unit}", "#808080"
        
    val = (speed - cutoff_speed) / bin_interval
    j = math.ceil(val)
    if j < 1:
        j = 1
    if j > num_bins_above:
        j = num_bins_above
        
    color = colormap[(j - 1) % len(colormap)]
    
    t_start = cutoff_speed + (j - 1) * bin_interval
    t_end = cutoff_speed + j * bin_interval
    
    if j == num_bins_above:
        return j, f"> {t_start:g} {unit}", color
    else:
        return j, f"{t_start:g} - {t_end:g} {unit}", color

def analyze_tcx(file_path, segment_len=100.0, angle_threshold=90.0, local_window=10.0, merge_dist=30.0,
                scheme="speed", speed_thresh=5.0, speed_duration=5.0, cutoff_speed=5.0, bin_interval=5.0, speed_unit="knots", map_file="map.html"):
    points, total_calories, has_calories = parse_tcx(file_path)
    if not points:
        raise ValueError("No valid trackpoints found in the TCX file.")
        
    # --- 1. Date and Time ---
    start_time = points[0]['time']
    end_time = points[-1]['time']
    
    # --- 2. Total Duration and Length ---
    total_duration = (end_time - start_time).total_seconds()
    total_length = points[-1]['dist'] - points[0]['dist']
    
    # --- 3 & 4. Duration and Distance above/below cutoff speed ---
    duration_above = 0.0
    duration_below = 0.0
    dist_above = 0.0
    dist_below = 0.0
    
    points[0]['speed'] = 0.0
    for i in range(1, len(points)):
        dt = (points[i]['time'] - points[i-1]['time']).total_seconds()
        dd = points[i]['dist'] - points[i-1]['dist']
        if dt > 0:
            speed_mps = dd / dt
            speed_kmh = speed_mps * 3.6
            points[i]['speed'] = speed_kmh
            
            if speed_unit == "knots":
                speed_val = speed_kmh / 1.852
            else:
                speed_val = speed_kmh
                
            if speed_val > cutoff_speed:
                duration_above += dt
                dist_above += dd
            else:
                duration_below += dt
                dist_below += dd
        else:
            points[i]['speed'] = points[i-1]['speed']
            
    # --- 5. Fastest 50m, 100m, 500m ---
    def find_fastest_window(X):
        min_duration_discrete = float('inf')
        min_duration_interpolated = float('inf')
        best_dist_discrete = 0.0
        
        right = 0
        for left in range(len(points)):
            while right < len(points) and points[right]['dist'] - points[left]['dist'] < X:
                right += 1
                
            if right < len(points):
                dur_disc = (points[right]['time'] - points[left]['time']).total_seconds()
                if dur_disc < min_duration_discrete:
                    min_duration_discrete = dur_disc
                    best_dist_discrete = points[right]['dist'] - points[left]['dist']
                    
                if right > left:
                    d_prev = points[right-1]['dist'] - points[left]['dist']
                    d_curr = points[right]['dist'] - points[left]['dist']
                    t_prev = (points[right-1]['time'] - points[left]['time']).total_seconds()
                    t_curr = (points[right]['time'] - points[left]['time']).total_seconds()
                    
                    if d_curr > d_prev:
                        dur_interp = t_prev + (X - d_prev) / (d_curr - d_prev) * (t_curr - t_prev)
                        if dur_interp < min_duration_interpolated:
                            min_duration_interpolated = dur_interp
                            
        return min_duration_interpolated, min_duration_discrete, best_dist_discrete

    fastest_50_interp, fastest_50_disc, dist_50_disc = find_fastest_window(50)
    fastest_100_interp, fastest_100_disc, dist_100_disc = find_fastest_window(100)
    fastest_500_interp, fastest_500_disc, dist_500_disc = find_fastest_window(500)
    
    if speed_unit == "knots":
        speed_factor = 3.6 / 1.852
        unit_label = "knots"
    else:
        speed_factor = 3.6
        unit_label = "km/h"
    
    speed_50_interp = (50.0 / fastest_50_interp) * speed_factor if fastest_50_interp > 0 else 0.0
    speed_50_disc = (dist_50_disc / fastest_50_disc) * speed_factor if fastest_50_disc > 0 else 0.0
    
    speed_100_interp = (100.0 / fastest_100_interp) * speed_factor if fastest_100_interp > 0 else 0.0
    speed_100_disc = (dist_100_disc / fastest_100_disc) * speed_factor if fastest_100_disc > 0 else 0.0
    
    speed_500_interp = (500.0 / fastest_500_interp) * speed_factor if fastest_500_interp > 0 else 0.0
    speed_500_disc = (dist_500_disc / fastest_500_disc) * speed_factor if fastest_500_disc > 0 else 0.0
    
    # --- 6. Leg and Turn Detection Calculations ---
    
    # 6.1 Directional Turn Detection (Segment-based curvature peak)
    anchors = [0]
    for idx, pt in enumerate(points):
        if pt['dist'] - points[anchors[-1]]['dist'] >= segment_len:
            anchors.append(idx)
    if anchors[-1] != len(points) - 1:
        anchors.append(len(points) - 1)
        
    segment_bearings = []
    for j in range(len(anchors) - 1):
        p_start = points[anchors[j]]
        p_end = points[anchors[j+1]]
        b = bearing(p_start['lat'], p_start['lon'], p_end['lat'], p_end['lon'])
        segment_bearings.append(b)
        
    turn_regions = []
    for j in range(len(segment_bearings) - 1):
        b1 = segment_bearings[j]
        b2 = segment_bearings[j+1]
        diff = abs(b2 - b1)
        if diff > 180:
            diff = 360 - diff
        if diff > angle_threshold:
            turn_regions.append((anchors[j], anchors[j+2]))
            
    raw_turn_points = []
    for start_idx, end_idx in turn_regions:
        best_pt_idx = -1
        max_curvature = -1.0
        
        for i in range(start_idx, end_idx + 1):
            ib = i
            while ib > 0 and points[i]['dist'] - points[ib]['dist'] < local_window:
                ib -= 1
            iff = i
            while iff < len(points) - 1 and points[iff]['dist'] - points[i]['dist'] < local_window:
                iff += 1
                
            h_in = bearing(points[ib]['lat'], points[ib]['lon'], points[i]['lat'], points[i]['lon'])
            h_out = bearing(points[i]['lat'], points[i]['lon'], points[iff]['lat'], points[iff]['lon'])
            
            diff = abs(h_out - h_in)
            if diff > 180:
                diff = 360 - diff
                
            ds = points[iff]['dist'] - points[ib]['dist']
            if ds > 0:
                curvature = diff / ds
                if curvature > max_curvature:
                    max_curvature = curvature
                    best_pt_idx = i
                    
        if best_pt_idx != -1:
            if points[-1]['dist'] - points[best_pt_idx]['dist'] < 15.0:
                continue
            if not raw_turn_points or raw_turn_points[-1] != best_pt_idx:
                raw_turn_points.append(best_pt_idx)
                
    def get_local_curvature(idx):
        ib = idx
        while ib > 0 and points[idx]['dist'] - points[ib]['dist'] < local_window:
            ib -= 1
        iff = idx
        while iff < len(points) - 1 and points[iff]['dist'] - points[idx]['dist'] < local_window:
            iff += 1
        h_in = bearing(points[ib]['lat'], points[ib]['lon'], points[idx]['lat'], points[idx]['lon'])
        h_out = bearing(points[idx]['lat'], points[idx]['lon'], points[iff]['lat'], points[iff]['lon'])
        diff = abs(h_out - h_in)
        if diff > 180:
            diff = 360 - diff
        ds = points[iff]['dist'] - points[ib]['dist']
        return diff / ds if ds > 0 else 0.0

    # Merge adjacent directional turn points
    directional_turn_indices = []
    if raw_turn_points:
        current_group = [raw_turn_points[0]]
        for t_idx in raw_turn_points[1:]:
            last_t_idx = current_group[-1]
            if points[t_idx]['dist'] - points[last_t_idx]['dist'] < merge_dist:
                current_group.append(t_idx)
            else:
                peak = max(current_group, key=get_local_curvature)
                directional_turn_indices.append(peak)
                current_group = [t_idx]
        if current_group:
            peak = max(current_group, key=get_local_curvature)
            directional_turn_indices.append(peak)
            
    # 6.2 Speed-Based Transition Detection (State machine)
    speed_transition_indices = []
    if len(points) >= speed_duration:
        if speed_unit == "knots":
            speeds_values = [pt['speed'] / 1.852 for pt in points]
        else:
            speeds_values = [pt['speed'] for pt in points]
        dur = int(speed_duration)
        
        # Estimate initial state
        avg_first_seconds = sum(speeds_values[:dur]) / dur
        current_state = "FAST" if avg_first_seconds > speed_thresh else "SLOW"
        
        i = 0
        while i < len(points):
            if i + dur <= len(points):
                run = speeds_values[i : i + dur]
                if current_state == "SLOW":
                    if all(s > speed_thresh for s in run):
                        speed_transition_indices.append(i)
                        current_state = "FAST"
                        i += dur - 1
                else: # FAST
                    if all(s <= speed_thresh for s in run):
                        speed_transition_indices.append(i)
                        current_state = "SLOW"
                        i += dur - 1
            i += 1
            
    # 6.3 Combined Turn Detection (Union of directional & speed-based, merged)
    combined_turn_points = sorted(list(set(directional_turn_indices + speed_transition_indices)))
    combined_turn_indices = []
    if combined_turn_points:
        current_group = [combined_turn_points[0]]
        for t_idx in combined_turn_points[1:]:
            last_t_idx = current_group[-1]
            if points[t_idx]['dist'] - points[last_t_idx]['dist'] < merge_dist:
                current_group.append(t_idx)
            else:
                peak = max(current_group, key=get_local_curvature)
                combined_turn_indices.append(peak)
                current_group = [t_idx]
        if current_group:
            peak = max(current_group, key=get_local_curvature)
            combined_turn_indices.append(peak)

    # 6.4 Select active scheme for stdout results
    if scheme == "direction":
        active_turn_indices = directional_turn_indices
        scheme_label = "Direction-based (Turns)"
    elif scheme == "speed":
        active_turn_indices = speed_transition_indices
        scheme_label = f"Speed-based (Transitions, >{speed_thresh} {unit_label} for {speed_duration}s)"
    else: # both
        active_turn_indices = combined_turn_indices
        scheme_label = "Combined (Direction + Speed)"
        
    leg_bounds = [0] + active_turn_indices + [len(points) - 1]
    
    # Calculate stats for stdout legs
    legs = []
    for idx in range(len(leg_bounds) - 1):
        start_pt = points[leg_bounds[idx]]
        end_pt = points[leg_bounds[idx+1]]
        
        duration = (end_pt['time'] - start_pt['time']).total_seconds()
        length = end_pt['dist'] - start_pt['dist']
        speed_val = (length / duration * speed_factor) if duration > 0 else 0.0
        
        legs.append({
            'num': idx + 1,
            'duration': duration,
            'length': length,
            'speed_val': speed_val
        })
        
    fastest_leg = max(legs, key=lambda x: x['speed_val'])
    longest_dist_leg = max(legs, key=lambda x: x['length'])
    longest_time_leg = max(legs, key=lambda x: x['duration'])
    
    # --- Output Results to Stdout ---
    print("======================================================================")
    print("                        TCX GPS DATA ANALYSIS                         ")
    print("======================================================================")
    print(f"Date and Time (Start):   {start_time.strftime('%Y-%m-%d %H:%M:%S %z')}")
    print(f"Date and Time (End):     {end_time.strftime('%Y-%m-%d %H:%M:%S %z')}")
    print(f"Total Duration:          {format_duration(total_duration)} ({total_duration:.0f} seconds)")
    print(f"Total Length:            {total_length / 1000:.3f} km ({total_length:.2f} meters)")
    if has_calories:
        print(f"Energy Burned:           {total_calories} kcal")
    print("----------------------------------------------------------------------")
    label_dur_above = f"Duration > {cutoff_speed:g} {unit_label}:"
    label_dur_below = f"Duration <= {cutoff_speed:g} {unit_label}:"
    label_dist_above = f"Distance > {cutoff_speed:g} {unit_label}:"
    label_dist_below = f"Distance <= {cutoff_speed:g} {unit_label}:"
    
    print(f"{label_dur_above:<25}{format_duration(duration_above)} ({duration_above:.0f} seconds)")
    print(f"{label_dur_below:<25}{format_duration(duration_below)} ({duration_below:.0f} seconds)")
    print(f"{label_dist_above:<25}{dist_above / 1000:.3f} km ({dist_above:.2f} meters)")
    print(f"{label_dist_below:<25}{dist_below / 1000:.3f} km ({dist_below:.2f} meters)")
    print("----------------------------------------------------------------------")
    print("Fastest Segments (exact interpolated / raw discrete):")
    print(f"  Fastest 50m:           {fastest_50_interp:.2f}s @ {speed_50_interp:.2f} {unit_label}  (raw discrete: {fastest_50_disc:.2f}s @ {speed_50_disc:.2f} {unit_label})")
    print(f"  Fastest 100m:          {fastest_100_interp:.2f}s @ {speed_100_interp:.2f} {unit_label}  (raw discrete: {fastest_100_disc:.2f}s @ {speed_100_disc:.2f} {unit_label})")
    print(f"  Fastest 500m:          {fastest_500_interp:.2f}s @ {speed_500_interp:.2f} {unit_label}  (raw discrete: {fastest_500_disc:.2f}s @ {speed_500_disc:.2f} {unit_label})")
    print("----------------------------------------------------------------------")
    print(f"Active Scheme:           {scheme_label}")
    print(f"Number of Legs:          {len(legs)}")
    print(f": fasted leg: {fastest_leg['speed_val']:.2f} {unit_label}, {fastest_leg['duration']:.0f}s, {fastest_leg['length']:.1f}m")
    print(f": longest leg by distance: {longest_dist_leg['speed_val']:.2f} {unit_label}, {longest_dist_leg['duration']:.0f}s, {longest_dist_leg['length']:.1f}m")
    print(f": longest leg by time: {longest_time_leg['speed_val']:.2f} {unit_label}, {longest_time_leg['duration']:.0f}s, {longest_time_leg['length']:.1f}m")
    print("======================================================================")
    
    # --- Folium Map Generation ---
    if map_file:
        if not HAS_FOLIUM:
            print("\nWarning: 'folium' library is not installed. Skipping map generation.", file=sys.stderr)
        else:
            lats = [pt['lat'] for pt in points]
            lons = [pt['lon'] for pt in points]
            center_lat = sum(lats) / len(points)
            center_lon = sum(lons) / len(points)
            
            m = folium.Map(location=[center_lat, center_lon])
            
            # Calculate maximum speed in unit to determine number of bins above cutoff
            if len(points) > 1:
                if speed_unit == "knots":
                    max_speed_unit = max(pt['speed'] for pt in points[1:]) / 1.852
                else:
                    max_speed_unit = max(pt['speed'] for pt in points[1:])
            else:
                max_speed_unit = 0.0
                
            if max_speed_unit > cutoff_speed:
                num_bins_above = math.ceil((max_speed_unit - cutoff_speed) / bin_interval)
            else:
                num_bins_above = 0
                
            TAB10 = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]
            TAB20 = ["#1f77b4", "#aec7e8", "#ff7f0e", "#ffbb78", "#2ca02c", "#98df8a", "#d62728", "#ff9896", "#9467bd", "#c5b0d5", "#8c564b", "#c49c94", "#e377c2", "#f7b6d2", "#7f7f7f", "#c7c7c7", "#bcbd22", "#dbdb8d", "#17becf", "#9edae5"]
            
            if num_bins_above <= 10:
                colormap = TAB10
            else:
                colormap = TAB20
            
            # Helper to add a leg overlay group
            def add_leg_layer(name, t_indices, is_shown):
                group = folium.FeatureGroup(name=name, show=is_shown)
                bounds = [0] + t_indices + [len(points) - 1]
                
                # Draw lines
                for idx in range(len(bounds) - 1):
                    leg_pts = points[bounds[idx] : bounds[idx+1] + 1]
                    leg_coords = [(pt['lat'], pt['lon']) for pt in leg_pts]
                    
                    start_pt = points[bounds[idx]]
                    end_pt = points[bounds[idx+1]]
                    duration = (end_pt['time'] - start_pt['time']).total_seconds()
                    length = end_pt['dist'] - start_pt['dist']
                    speed_val = (length / duration * speed_factor) if duration > 0 else 0.0
                    
                    _, _, color = get_speed_bin_info(speed_val, unit_label, cutoff_speed, bin_interval, num_bins_above, colormap)
                    tooltip_txt = f"Leg {idx+1}: {speed_val:.2f} {unit_label}, {format_duration(duration)} ({duration:.0f}s), {length:.1f}m"
                    
                    folium.PolyLine(
                        locations=leg_coords,
                        color=color,
                        weight=5,
                        opacity=0.85,
                        tooltip=tooltip_txt
                    ).add_to(group)
                    
                # Add markers at leg ends (turns/transitions)
                if "Speed-based" not in name:
                    for turn_idx_in_layer, orig_idx in enumerate(t_indices):
                        pt = points[orig_idx]
                        
                        if "Directional" in name:
                            fill_col = "#FFFF00"  # Yellow for direction turns
                            label_type = "Turn"
                        elif "Speed-based" in name:
                            fill_col = "#34C759"  # Green for speed transitions
                            label_type = "Speed Transition"
                        else:
                            fill_col = "#AF52DE"  # Purple for combined
                            label_type = "Combined Turn"
                            
                        folium.CircleMarker(
                            location=[pt['lat'], pt['lon']],
                            radius=5.5,
                            color="#000000",
                            fill=True,
                            fill_color=fill_col,
                            fill_opacity=1.0,
                            weight=1.5,
                            tooltip=f"Leg End {turn_idx_in_layer+1} ({label_type}): Dist={pt['dist']:.1f}m, Time={pt['time_str'].split('T')[1]}"
                        ).add_to(group)
                    
                return group
            
            # Create the three leg layers
            group_dir = add_leg_layer("Legs: Directional", directional_turn_indices, (scheme == "direction"))
            group_spd = add_leg_layer("Legs: Speed-based", speed_transition_indices, (scheme == "speed"))
            group_comb = add_leg_layer("Legs: Combined", combined_turn_indices, (scheme == "both"))
            
            # Create the speed bins color overlay layer
            group_speed_colors = folium.FeatureGroup(name=f"Track: Speed ({bin_interval:g} {unit_label} bins)", show=False)
            
            if len(points) > 1:
                def get_pt_speed(pt):
                    if speed_unit == "knots":
                        return pt['speed'] / 1.852
                    else:
                        return pt['speed']
                        
                first_speed = get_pt_speed(points[1])
                first_bin_id, _, _ = get_speed_bin_info(first_speed, unit_label, cutoff_speed, bin_interval, num_bins_above, colormap)
                current_run = [(points[0]['lat'], points[0]['lon']), (points[1]['lat'], points[1]['lon'])]
                current_bin_id = first_bin_id
                start_pt = points[0]
                
                for i in range(2, len(points)):
                    pt_speed = get_pt_speed(points[i])
                    bin_id, _, _ = get_speed_bin_info(pt_speed, unit_label, cutoff_speed, bin_interval, num_bins_above, colormap)
                    if bin_id == current_bin_id:
                        current_run.append((points[i]['lat'], points[i]['lon']))
                    else:
                        _, label, color = get_speed_bin_info(get_pt_speed(points[i-1]), unit_label, cutoff_speed, bin_interval, num_bins_above, colormap)
                        duration = (points[i-1]['time'] - start_pt['time']).total_seconds()
                        distance = points[i-1]['dist'] - start_pt['dist']
                        avg_speed_val = (distance / duration * speed_factor) if duration > 0 else 0.0
                        
                        tooltip_txt = f"Speed Bin: {label} (Avg: {avg_speed_val:.2f} {unit_label}, {distance:.1f}m, {duration:.0f}s)"
                        
                        folium.PolyLine(
                            locations=current_run,
                            color=color,
                            weight=5,
                            opacity=0.85,
                            tooltip=tooltip_txt
                        ).add_to(group_speed_colors)
                        
                        current_run = [(points[i-1]['lat'], points[i-1]['lon']), (points[i]['lat'], points[i]['lon'])]
                        current_bin_id = bin_id
                        start_pt = points[i-1]
                        
                last_speed = get_pt_speed(points[-1])
                _, label, color = get_speed_bin_info(last_speed, unit_label, cutoff_speed, bin_interval, num_bins_above, colormap)
                duration = (points[-1]['time'] - start_pt['time']).total_seconds()
                distance = points[-1]['dist'] - start_pt['dist']
                avg_speed_val = (distance / duration * speed_factor) if duration > 0 else 0.0
                
                tooltip_txt = f"Speed Bin: {label} (Avg: {avg_speed_val:.2f} {unit_label}, {distance:.1f}m, {duration:.0f}s)"
                
                folium.PolyLine(
                    locations=current_run,
                    color=color,
                    weight=5,
                    opacity=0.85,
                    tooltip=tooltip_txt
                ).add_to(group_speed_colors)
                
            # Add all four feature groups to map
            group_dir.add_to(m)
            group_spd.add_to(m)
            group_comb.add_to(m)
            group_speed_colors.add_to(m)
            
            # Layer control
            folium.LayerControl(collapsed=False).add_to(m)
            
            # Global Start and End markers
            folium.Marker(
                location=[points[0]['lat'], points[0]['lon']],
                popup=f"Start Time: {points[0]['time_str']}",
                icon=folium.Icon(color="green", icon="play")
            ).add_to(m)
            
            folium.Marker(
                location=[points[-1]['lat'], points[-1]['lon']],
                popup=f"End Time: {points[-1]['time_str']}",
                icon=folium.Icon(color="red", icon="stop")
            ).add_to(m)
            
            # Fit bounds
            m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])
            
            # Speed Legend
            legend_items = []
            for j in range(num_bins_above + 1):
                if j == 0:
                    rep_speed = cutoff_speed
                elif j == num_bins_above:
                    rep_speed = cutoff_speed + j * bin_interval + 1.0
                else:
                    rep_speed = cutoff_speed + (j - 0.5) * bin_interval
                _, label, color = get_speed_bin_info(rep_speed, unit_label, cutoff_speed, bin_interval, num_bins_above, colormap)
                legend_items.append(f'<i style="background: {color}; width: 18px; height: 12px; float: left; margin-right: 8px; margin-top: 4px; border-radius: 2px;"></i>{label}<br>')
            legend_rows_html = "\n".join(legend_items)
            
            legend_html = f"""
            <div id="speed-legend" style="
                position: fixed; 
                bottom: 50px; 
                left: 50px; 
                width: 180px; 
                max-height: 400px; 
                overflow-y: auto;
                z-index:9999; 
                background: rgba(255, 255, 255, 0.85);
                backdrop-filter: blur(5px);
                border: 2px solid rgba(0, 0, 0, 0.1);
                padding: 12px 16px; 
                font-size: 14px; 
                font-family: system-ui, -apple-system, sans-serif;
                border-radius: 12px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                pointer-events: auto;
                display: none;
            ">
                <style>
                #speed-legend::-webkit-scrollbar {{
                    width: 6px;
                }}
                #speed-legend::-webkit-scrollbar-track {{
                    background: transparent;
                }}
                #speed-legend::-webkit-scrollbar-thumb {{
                    background: rgba(0, 0, 0, 0.2);
                    border-radius: 3px;
                }}
                #speed-legend::-webkit-scrollbar-thumb:hover {{
                    background: rgba(0, 0, 0, 0.4);
                }}
                </style>
                <b style="color: #333;">Speed Legend</b><br>
                <div style="margin-top: 8px; color: #555;">
                     {legend_rows_html}
                </div>
            </div>
            
            <script>
            function initLegendToggle() {{
                var inputs = document.querySelectorAll('.leaflet-control-layers-selector');
                if (inputs.length === 0) {{
                    setTimeout(initLegendToggle, 100);
                    return;
                }}
                var legend = document.getElementById('speed-legend');
                function updateLegend() {{
                    var anyChecked = false;
                    inputs.forEach(function(cb) {{
                        if (cb.type === 'checkbox' && cb.checked) {{
                            anyChecked = true;
                        }}
                    }});
                    legend.style.display = anyChecked ? 'block' : 'none';
                }}
                inputs.forEach(function(cb) {{
                    cb.addEventListener('change', updateLegend);
                }});
                updateLegend();
            }}
            setTimeout(initLegendToggle, 100);
            </script>
            """
            m.get_root().html.add_child(folium.Element(legend_html))
            
            m.save(map_file)
            print(f"\nMap successfully generated and saved to '{map_file}'")
            
    return {
        'start_time': start_time,
        'end_time': end_time,
        'total_duration': total_duration,
        'total_length': total_length,
        'total_calories': total_calories if has_calories else None,
        'duration_above': duration_above,
        'duration_below': duration_below,
        'dist_above': dist_above,
        'dist_below': dist_below,
        'fastest_50': {
            'duration': fastest_50_interp,
            'speed': speed_50_interp,
        },
        'fastest_100': {
            'duration': fastest_100_interp,
            'speed': speed_100_interp,
        },
        'fastest_500': {
            'duration': fastest_500_interp,
            'speed': speed_500_interp,
        },
        'num_legs': len(legs),
        'speed_unit': unit_label
    }

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Analyze TCX GPS data.")
    parser.add_argument(
        "tcx_file", 
        nargs="?", 
        help="Path to the TCX file. If omitted, the first .tcx file in the current directory will be used."
    )
    parser.add_argument(
        "-c", "--scheme",
        choices=["direction", "speed", "both"],
        default="speed",
        help="Segmentation scheme: 'direction' (turns), 'speed' (speed-based transitions), or 'both' (combined) (default: speed)"
    )
    parser.add_argument(
        "-s", "--segment-len",
        type=float,
        default=100.0,
        help="Segment length in meters to calculate segment directions (default: 100.0)"
    )
    parser.add_argument(
        "-a", "--angle", 
        type=float, 
        default=90.0, 
        help="Direction change threshold in degrees to detect a turn/leg boundary (default: 90.0)"
    )
    parser.add_argument(
        "-w", "--window",
        type=float,
        default=10.0,
        help="Local curvature window in meters to pinpoint turn location (default: 10.0)"
    )
    parser.add_argument(
        "-d", "--merge-dist",
        type=float,
        default=30.0,
        help="Distance threshold in meters to merge adjacent turn points (default: 30.0)"
    )
    parser.add_argument(
        "-u", "--unit",
        choices=["knots", "kmh"],
        default="knots",
        help="Speed unit for input thresholds and output values: 'knots' or 'kmh' (default: knots)"
    )
    parser.add_argument(
        "--speed-thresh",
        type=float,
        default=5.0,
        help="Speed threshold for speed-based segmentation in selected speed unit (default: 5.0)"
    )
    parser.add_argument(
        "--speed-duration",
        type=float,
        default=5.0,
        help="Consecutive duration in seconds to trigger a speed state change (default: 5.0)"
    )
    parser.add_argument(
        "--cutoff-speed",
        type=float,
        default=5.0,
        help="Cutoff speed for duration and distance summary statistics in selected speed unit (default: 5.0)"
    )
    parser.add_argument(
        "--bin-interval",
        type=float,
        default=5.0,
        help="Speed bin interval for map speed coloring in selected speed unit (default: 5.0)"
    )
    parser.add_argument(
        "-m", "--map", 
        default="map.html", 
        help="Path to save the folium HTML map (default: map.html). Use 'none' to disable."
    )
    args = parser.parse_args()
    
    if args.tcx_file:
        tcx_file = args.tcx_file
    else:
        tcx_files = [f for f in os.listdir('.') if f.lower().endswith('.tcx')]
        if not tcx_files:
            print("No .tcx files found in the current directory.", file=sys.stderr)
            print("Usage: python3 tcx_analyzer.py <path_to_tcx_file>", file=sys.stderr)
            sys.exit(1)
        tcx_file = tcx_files[0]
        print(f"Using default TCX file: {tcx_file}")
        
    map_out = None if args.map.lower() == 'none' else args.map
    try:
        analyze_tcx(
            tcx_file, 
            segment_len=args.segment_len,
            angle_threshold=args.angle, 
            local_window=args.window,
            merge_dist=args.merge_dist,
            scheme=args.scheme,
            speed_thresh=args.speed_thresh,
            speed_duration=args.speed_duration,
            cutoff_speed=args.cutoff_speed,
            bin_interval=args.bin_interval,
            speed_unit=args.unit,
            map_file=map_out
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
