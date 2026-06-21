#!/usr/bin/env python3
import os
import sys
import io
import time
import uuid
import contextlib
from datetime import datetime
from fastapi.responses import HTMLResponse

from nicegui import ui, app, run, Client
from pywindsurf import analyze_tcx, format_duration

# Cleanup any orphaned map files from previous crashes on server startup
def cleanup_orphaned_maps():
    for f in os.listdir('.'):
        if f.startswith('map_') and f.endswith('.html'):
            try:
                os.remove(f)
            except Exception:
                pass

cleanup_orphaned_maps()

# Dashboard Metric Card helper
def metric_card(title: str, value: str = '', subtext: str = '', icon: str = None):
    with ui.card().classes('bg-zinc-900 border border-zinc-800/80 shadow-sm p-4 rounded-xl flex flex-col justify-between h-[110px] grow min-w-[210px]'):
        with ui.row().classes('justify-between items-center w-full'):
            ui.label(title).classes('text-[10px] font-semibold text-zinc-500 uppercase tracking-wider')
            if icon:
                ui.icon(icon, color='info').classes('text-lg')
        value_label = ui.label(value).classes('text-xl font-bold text-white mt-1')
        sub_label = ui.label(subtext).classes('text-[10px] text-zinc-500 mt-1 truncate')
    return value_label, sub_label

# Custom FastAPI Map Serving Route (serves isolated map files per session)
@app.get('/map/{session_id}')
def get_map(session_id: str):
    file_path = f'map_{session_id}.html'
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="""
        <div style="
            display: flex; 
            flex-direction: column;
            justify-content: center; 
            align-items: center; 
            height: 100vh; 
            background: #09090b; 
            color: #71717a; 
            font-family: system-ui, -apple-system, sans-serif;
            text-align: center;
            padding: 20px;
        ">
            <svg style="width: 64px; height: 64px; margin-bottom: 16px; color: #3f3f46;" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7"></path>
            </svg>
            <h3 style="margin: 0; font-weight: 500; font-size: 18px; color: #a1a1aa;">No GPS Trace Loaded Yet</h3>
            <p style="margin: 8px 0 0; font-size: 14px; color: #52525b; max-width: 300px;">
                Select a TCX file on the sidebar and click "Analyze" to render your windsurfing map here.
            </p>
        </div>
    """)

# Main Per-Session Page Function
@ui.page('/')
def index(client: Client):
    # Custom Styling Elements (inside page scope)
    ui.add_head_html('<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">')
    ui.query('body').style('font-family: "Inter", sans-serif;')

    # Force dark mode by default for premium dark UI
    dark = ui.dark_mode()
    dark.enable()

    # Create a unique session ID for this browser tab connection
    session_id = str(uuid.uuid4())
    map_filename = f'map_{session_id}.html'
    
    # Automatically clean up the map file when this client disconnects/closes tab
    def cleanup_map():
        if os.path.exists(map_filename):
            try:
                os.remove(map_filename)
            except Exception:
                pass
    client.on_disconnect(cleanup_map)
    
    # Local references to labels in this user's stats dashboard
    stats_labels = {}
    stats_placeholder = None
    stats_grid = None
    stats_threshold_title = None

    # Update Dashboard Statistics (called inside run_analysis)
    def update_dashboard(results):
        if not results:
            stats_placeholder.classes(remove='hidden')
            stats_grid.classes('hidden')
            return
            
        # 1. Update Overview
        dist_km = results['total_length'] / 1000
        stats_labels['dist_val'].text = f"{dist_km:.3f} km"
        stats_labels['dist_sub'].text = f"{results['total_length']:.2f} meters"
        
        dur_str = format_duration(results['total_duration'])
        stats_labels['dur_val'].text = dur_str
        stats_labels['dur_sub'].text = f"{results['total_duration']:.0f} seconds"
        
        cal_val = f"{results['total_calories']} kcal" if results['total_calories'] is not None else "N/A"
        stats_labels['cal_val'].text = cal_val
        stats_labels['cal_sub'].text = 'Estimated calories burned' if results['total_calories'] is not None else 'No calorie data'
        
        stats_labels['legs_val'].text = str(results['num_legs'])
        stats_labels['legs_sub'].text = f"Segmentation: {scheme.value.title()}"
        
        # 2. Update Speed Analysis
        unit_lbl = results['speed_unit']
        stats_labels['speed_50_val'].text = f"{results['fastest_50']['speed']:.2f} {unit_lbl}"
        stats_labels['speed_50_sub'].text = f"Duration: {results['fastest_50']['duration']:.2f}s"
        
        stats_labels['speed_100_val'].text = f"{results['fastest_100']['speed']:.2f} {unit_lbl}"
        stats_labels['speed_100_sub'].text = f"Duration: {results['fastest_100']['duration']:.2f}s"
        
        stats_labels['speed_500_val'].text = f"{results['fastest_500']['speed']:.2f} {unit_lbl}"
        stats_labels['speed_500_sub'].text = f"Duration: {results['fastest_500']['duration']:.2f}s"
        
        # 3. Update Thresholds
        stats_threshold_title.text = f"Threshold Statistics (Cutoff: {cutoff_speed.value} {unit_lbl})"
        
        stats_labels['thresh_dur_above_val'].text = format_duration(results['duration_above'])
        stats_labels['thresh_dur_above_sub'].text = f"{results['duration_above']:.0f}s active speed time"
        
        stats_labels['thresh_dist_above_val'].text = f"{results['dist_above'] / 1000:.3f} km"
        stats_labels['thresh_dist_above_sub'].text = f"{results['dist_above']:.2f}m active distance"
        
        stats_labels['thresh_dur_below_val'].text = format_duration(results['duration_below'])
        stats_labels['thresh_dur_below_sub'].text = f"{results['duration_below']:.0f}s resting speed time"
        
        stats_labels['thresh_dist_below_val'].text = f"{results['dist_below'] / 1000:.3f} km"
        stats_labels['thresh_dist_below_sub'].text = f"{results['dist_below']:.2f}m resting distance"
        
        # Toggle Visibility using CSS classes (avoids virtual DOM diffing errors)
        stats_placeholder.classes('hidden')
        stats_grid.classes(remove='hidden')

    # Run TCX Analysis Async/Thread
    async def run_analysis():
        path = file_input.value
        if not path or not os.path.exists(path):
            ui.notify('Please select a valid TCX file.', type='warning')
            return
            
        run_btn.disable()
        spinner.visible = True
        log_viewer.clear()
        log_viewer.push(f"[{datetime.now().strftime('%H:%M:%S')}] Launching analysis for: {os.path.basename(path)}...")
        
        try:
            params = {
                'file_path': path,
                'segment_len': float(segment_len.value),
                'angle_threshold': float(angle_thresh.value),
                'local_window': float(local_window.value),
                'merge_dist': float(merge_dist.value),
                'scheme': scheme.value,
                'speed_thresh': float(speed_thresh.value),
                'speed_duration': float(speed_duration.value),
                'cutoff_speed': float(cutoff_speed.value),
                'bin_interval': float(bin_interval.value),
                'speed_unit': unit.value,
                'map_file': map_filename
            }
            
            # Run inside a CPU-bound/IO-bound thread pool to avoid blocking the event loop
            f = io.StringIO()
            with contextlib.redirect_stdout(f):
                results = await run.io_bound(analyze_tcx, **params)
                
            stdout_content = f.getvalue()
            for line in stdout_content.splitlines():
                log_viewer.push(line)
                
            # Update components
            update_dashboard(results)
            map_iframe.props(f'src="/map/{session_id}?t={time.time()}"')
            map_iframe.update()
            
            ui.notify('TCX GPS analysis completed!', type='positive')
            
        except Exception as e:
            ui.notify(f'Analysis failed: {e}', type='negative')
            log_viewer.push(f'\n[ERROR ENCOUNTERED] {e}')
        finally:
            run_btn.enable()
            spinner.visible = False

    # Auto-detect default TCX file at directory path on startup
    def auto_detect_tcx():
        tcx_files = [f for f in os.listdir('.') if f.lower().endswith('.tcx')]
        if tcx_files:
            file_input.value = os.path.abspath(tcx_files[0])

    # Build the layout
    with ui.row().classes('w-full h-screen gap-0 wrap-none overflow-hidden bg-zinc-950 text-zinc-100'):
        # SIDEBAR PANEL (Controls)
        with ui.column().classes('w-[360px] h-full p-4 border-r border-zinc-800 bg-zinc-900/40 shrink-0 gap-4 overflow-y-auto'):
            # Header branding
            with ui.row().classes('items-center gap-2 mb-2'):
                ui.icon('sailing', color='info').classes('text-3xl')
                with ui.column().classes('gap-0'):
                    ui.label('PyWindsurf').classes('text-lg font-bold text-white leading-none')
                    ui.label('GPS Analytics Dashboard').classes('text-xs text-zinc-500')
                    
            ui.separator().classes('border-zinc-800')
            
            # File selector input card
            with ui.card().classes('w-full bg-zinc-900 border border-zinc-800 p-3 rounded-xl gap-2 shadow-sm'):
                ui.label('Data Source').classes('text-xs font-semibold text-zinc-400 uppercase tracking-wider')
                with ui.row().classes('w-full items-center gap-2'):
                    file_input = ui.input(placeholder='Select TCX file...').classes('grow text-xs').props('dense dark outlined')
                    ui.button(icon='folder', on_click=lambda: LocalFilePicker(directory='.', on_select=lambda p: file_input.set_value(p)).open())\
                        .props('dense flat color=info').classes('p-1').tooltip('Browse files')
                        
            # Parameters Input Card
            with ui.card().classes('w-full bg-zinc-900 border border-zinc-800 p-3 rounded-xl gap-3 shadow-sm grow-0'):
                ui.label('Analysis Settings').classes('text-xs font-semibold text-zinc-400 uppercase tracking-wider')
                
                # Unit selector
                unit = ui.select(
                    options={'knots': 'Knots (kt)', 'kmh': 'Kilometers per Hour (km/h)'}, 
                    value='knots', 
                    label='Speed Unit'
                ).props('dense dark outlined').classes('w-full text-sm')
                
                # Scheme Selector
                scheme = ui.select(
                    options={'speed': 'Speed Transitions', 'direction': 'Directional Turns', 'both': 'Combined (Both)'}, 
                    value='speed', 
                    label='Segmentation Scheme'
                ).props('dense dark outlined').classes('w-full text-sm')
                
                # Advanced accordion
                with ui.expansion('Advanced Parameters', icon='settings').classes('w-full border border-zinc-800 rounded-lg text-sm bg-zinc-950/40').props('header-class="text-zinc-300 py-1"'):
                    with ui.column().classes('p-2 gap-2 w-full text-xs'):
                        segment_len = ui.number(value=100.0, label='Segment Length (m)', format='%.1f').props('dense dark outlined')
                        angle_thresh = ui.number(value=90.0, label='Angle Threshold (°)', format='%.1f').props('dense dark outlined')
                        local_window = ui.number(value=10.0, label='Curvature Window (m)', format='%.1f').props('dense dark outlined')
                        merge_dist = ui.number(value=30.0, label='Merge Distance (m)', format='%.1f').props('dense dark outlined')
                        speed_thresh = ui.number(value=5.0, label='Speed Threshold', format='%.1f').props('dense dark outlined')
                        speed_duration = ui.number(value=5.0, label='Speed Duration (s)', format='%.1f').props('dense dark outlined')
                        cutoff_speed = ui.number(value=5.0, label='Cutoff Speed', format='%.1f').props('dense dark outlined')
                        bin_interval = ui.number(value=5.0, label='Speed Bin Interval', format='%.1f').props('dense dark outlined')
                        
                # Auto-default parameters when unit changes
                def handle_unit_change(e):
                    if e.value == 'knots':
                        speed_thresh.value = 5.0
                        cutoff_speed.value = 5.0
                        bin_interval.value = 5.0
                    else:
                        speed_thresh.value = 10.0
                        cutoff_speed.value = 10.0
                        bin_interval.value = 10.0
                unit.on_value_change(handle_unit_change)
                
            # Run Action Button
            with ui.row().classes('w-full justify-between items-center mt-2'):
                spinner = ui.spinner(size='md', color='info').classes('grow-0')
                spinner.visible = False
                run_btn = ui.button('Run Analysis', icon='play_arrow', on_click=lambda: run_analysis())\
                    .props('color=info icon-right').classes('grow rounded-xl py-2 font-bold')

        # MAIN RESULT PANEL
        with ui.column().classes('grow h-full bg-zinc-950 overflow-hidden gap-0'):
            # Tabs navigation
            with ui.tabs().classes('w-full border-b border-zinc-800 bg-zinc-900/30 text-zinc-400') as tabs:
                map_tab = ui.tab('Map Viewer', icon='map')
                stats_tab = ui.tab('Stats Dashboard', icon='analytics')
                log_tab = ui.tab('Console Log', icon='terminal')
                
            with ui.tab_panels(tabs, value=map_tab).classes('w-full grow bg-transparent overflow-hidden'):
                # MAP TAB
                with ui.tab_panel(map_tab).classes('p-0 h-full w-full overflow-hidden bg-zinc-950'):
                    map_container = ui.column().classes('w-full h-full p-0 gap-0')
                    with map_container:
                        map_iframe = ui.element('iframe').classes('w-full h-full border-none bg-zinc-950')
                        map_iframe.props(f'src="/map/{session_id}"')
                        
                # STATS DASHBOARD TAB
                with ui.tab_panel(stats_tab).classes('p-6 h-full overflow-y-auto bg-zinc-950'):
                    stats_placeholder = ui.label('No session analyzed yet. Select a file and click "Run Analysis" to view statistics.') \
                        .classes('text-zinc-500 italic p-12 text-center w-full')
                    
                    stats_grid = ui.column().classes('w-full gap-4 pb-12 hidden')
                    
                    with stats_grid:
                        ui.label('Session Overview').classes('text-sm font-bold text-zinc-300 mb-1')
                        with ui.row().classes('w-full gap-4 wrap'):
                            stats_labels['dist_val'], stats_labels['dist_sub'] = metric_card('Total Distance', icon='explore')
                            stats_labels['dur_val'], stats_labels['dur_sub'] = metric_card('Total Duration', icon='schedule')
                            stats_labels['cal_val'], stats_labels['cal_sub'] = metric_card('Energy Burned', icon='local_fire_department')
                            stats_labels['legs_val'], stats_labels['legs_sub'] = metric_card('Total Legs', icon='navigation')
                            
                        ui.separator().classes('my-4 border-zinc-800')
                        
                        ui.label('Speed Analysis').classes('text-sm font-bold text-zinc-300 mb-1')
                        with ui.row().classes('w-full gap-4 wrap'):
                            stats_labels['speed_50_val'], stats_labels['speed_50_sub'] = metric_card('Fastest 50m', icon='speed')
                            stats_labels['speed_100_val'], stats_labels['speed_100_sub'] = metric_card('Fastest 100m', icon='speed')
                            stats_labels['speed_500_val'], stats_labels['speed_500_sub'] = metric_card('Fastest 500m', icon='speed')
                            
                        ui.separator().classes('my-4 border-zinc-800')
                        
                        stats_threshold_title = ui.label("Threshold Statistics").classes('text-sm font-bold text-zinc-300 mb-1')
                        with ui.row().classes('w-full gap-4 wrap'):
                            stats_labels['thresh_dur_above_val'], stats_labels['thresh_dur_above_sub'] = metric_card("Duration > Cutoff", icon='trending_up')
                            stats_labels['thresh_dist_above_val'], stats_labels['thresh_dist_above_sub'] = metric_card("Distance > Cutoff", icon='leaderboard')
                            stats_labels['thresh_dur_below_val'], stats_labels['thresh_dur_below_sub'] = metric_card("Duration <= Cutoff", icon='trending_down')
                            stats_labels['thresh_dist_below_val'], stats_labels['thresh_dist_below_sub'] = metric_card("Distance <= Cutoff", icon='location_off')
                        
                # CONSOLE LOG TAB
                with ui.tab_panel(log_tab).classes('p-4 h-full overflow-hidden bg-zinc-950 flex flex-col'):
                    with ui.column().classes('w-full grow overflow-hidden bg-zinc-950 rounded-xl border border-zinc-800 p-2'):
                        log_viewer = ui.log().classes('w-full h-full font-mono text-[11px] text-emerald-400 bg-zinc-950 p-2 border-none')
                        log_viewer.push("System Initialized. Awaiting TCX analysis execution...")

    # Run auto-detect
    auto_detect_tcx()

# Run NiceGUI App
if __name__ in {'__main__', '__mp_main__'}:
    ui.run(title='PyWindsurf GPS Analytics', port=8080, show=True)
