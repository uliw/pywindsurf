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
from pywindsurf import analyze_tcx

# Cleanup any orphaned map files from previous crashes on server startup
def cleanup_orphaned_maps():
    for f in os.listdir('.'):
        if f.startswith('map_') and f.endswith('.html'):
            try:
                os.remove(f)
            except Exception:
                pass

cleanup_orphaned_maps()

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

# Custom Local File Picker Dialog
class LocalFilePicker(ui.dialog):
    def __init__(self, directory: str = '.', suffix: str = '.tcx', on_select=None) -> None:
        super().__init__()
        self.path = os.path.abspath(directory)
        self.suffix = suffix
        self.on_select = on_select
        
        with self, ui.card().classes('w-[500px] h-[600px] flex flex-col bg-zinc-900 border border-zinc-800 text-zinc-100'):
            with ui.row().classes('w-full items-center justify-between border-b border-zinc-800 pb-2'):
                ui.label('Select TCX File').classes('text-lg font-bold text-white')
                ui.button(icon='close', on_click=self.close).props('flat dense').classes('text-zinc-400')
                
            with ui.row().classes('w-full items-center gap-2 py-2'):
                ui.button(icon='arrow_upward', on_click=self.go_up).props('flat dense').classes('text-zinc-400').tooltip('Go up one directory')
                self.path_label = ui.label(self.path).classes('text-xs font-mono truncate grow text-zinc-400')
                
            self.list_container = ui.column().classes('w-full grow overflow-y-auto gap-1 border border-zinc-800 rounded p-2 bg-zinc-950')
            self.update_list()
            
    def update_list(self):
        self.list_container.clear()
        self.path_label.text = self.path
        
        try:
            items = os.listdir(self.path)
        except Exception as e:
            with self.list_container:
                ui.label(f'Error reading directory: {e}').classes('text-red-500 text-xs p-2')
            return
            
        folders = []
        files = []
        for item in items:
            full_path = os.path.join(self.path, item)
            if os.path.isdir(full_path):
                folders.append(item)
            elif os.path.isfile(full_path) and item.lower().endswith(self.suffix.lower()):
                files.append(item)
                
        folders.sort()
        files.sort()
        
        with self.list_container:
            if not folders and not files:
                ui.label('No folders or .tcx files found.').classes('text-zinc-600 italic text-sm p-4 text-center w-full')
                
            for folder in folders:
                with ui.row().classes('w-full items-center hover:bg-zinc-850 p-2 rounded cursor-pointer gap-2') \
                        .on('click', lambda _, f=folder: self.navigate_to(f)):
                    ui.icon('folder', color='primary').classes('text-xl')
                    ui.label(folder).classes('grow truncate text-sm text-zinc-300')
                    
            for file in files:
                with ui.row().classes('w-full items-center hover:bg-zinc-850 p-2 rounded cursor-pointer gap-2') \
                        .on('click', lambda _, f=file: self.select_file(f)):
                    ui.icon('insert_drive_file', color='secondary').classes('text-xl')
                    ui.label(file).classes('grow truncate text-sm text-zinc-300')
                    ui.button(icon='check', on_click=lambda _, f=file: self.select_file(f)).props('flat dense').classes('text-emerald-500')

    def navigate_to(self, folder_name: str):
        self.path = os.path.abspath(os.path.join(self.path, folder_name))
        self.update_list()
        
    def go_up(self):
        parent = os.path.dirname(self.path)
        if parent != self.path:  # Prevent infinite loop at root
            self.path = parent
            self.update_list()
            
    def select_file(self, file_name: str):
        full_path = os.path.join(self.path, file_name)
        if self.on_select:
            self.on_select(full_path)
        self.close()

# Main Per-Session Page Function
@ui.page('/')
def index(client: Client):
    # Custom Styling Elements (inside page scope to satisfy NiceGUI decorator rules)
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
                await run.io_bound(analyze_tcx, **params)
                
            stdout_content = f.getvalue()
            for line in stdout_content.splitlines():
                log_viewer.push(line)
                
            # Update components
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
        # 1. SIDEBAR PANEL (Controls)
        with ui.column().classes('w-[320px] h-full p-4 border-r border-zinc-800 bg-zinc-900/40 shrink-0 gap-4 overflow-y-auto'):
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

        # 2. MAP AREA (Middle, takes remaining available space)
        with ui.column().classes('grow h-full p-4 gap-0'):
            map_container = ui.column().classes('w-full h-full border border-zinc-800 rounded-2xl overflow-hidden bg-zinc-950')
            with map_container:
                map_iframe = ui.element('iframe').classes('w-full h-full border-none bg-zinc-950')
                map_iframe.props(f'src="/map/{session_id}"')

        # 3. CONSOLE LOG PANEL (Right sidebar)
        with ui.column().classes('w-[530px] h-full p-4 border-l border-zinc-800 bg-zinc-900/10 shrink-0 overflow-hidden flex flex-col gap-2'):
            ui.label('Analysis Output').classes('text-xs font-semibold text-zinc-400 uppercase tracking-wider')
            log_viewer = ui.log().classes('w-full grow font-mono text-[11px] text-emerald-400 bg-zinc-950 p-3 rounded-xl border border-zinc-800')
            log_viewer.push("System Initialized. Awaiting TCX analysis execution...")

    # Run auto-detect
    auto_detect_tcx()

# Run NiceGUI App
if __name__ in {'__main__', '__mp_main__'}:
    ui.run(title='PyWindsurf GPS Analytics', port=8080, show=True)
