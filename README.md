# PyWindsurf

PyWindsurf is a Python-based GPS data analysis tool specifically designed for windsurfing and other water sports. It parses Garmin/Fit/Strava `.tcx` track files, automatically segments your session into active legs and turns, calculates key statistics (e.g. fastest 50m, 100m, 500m runs), and generates interactive Leaflet maps with speed-binned color track lines. 

It includes both a command-line interface (CLI) and an elegant, desktop-friendly graphical dashboard (GUI) built with **NiceGUI**.

Note: To export track files from your Apple Watch, you need third party software, like https://www.rungap.com/ or https://apps.apple.com/ca/app/healthfit/

---

## Key Features

1. **Detailed GPS Session Analysis**:
   - Computes total duration, distance, and energy burned (calories).
   - Generates speed statistics below/above customizable active speed cutoffs.
   - Measures fastest exact segments: **Fastest 50m**, **100m**, and **500m** runs using high-accuracy mathematical interpolation.

2. **Automated Turn & Leg Segmentation**:
   - **Speed-based transitions**: Detects when you drop off plane (e.g. slow down below threshold for gybes or tacks).
   - **Direction-based turns**: Pinpoints curvature peaks and heading changes.
   - Identifies individual run legs and calculates stats for each leg.

3. **Interactive Maps (Folium / Leaflet)**:
   - Visualizes your complete route on an interactive OpenStreetMap.
   - Color-codes track lines based on speed bins (e.g. knots or km/h).
   - Places markers at detected turn/transition points with hover tooltip metadata.
   - Displays a dynamic, toggleable speed legend in the viewport.

4. **Multi-User Isolated GUI Dashboard**:
   - A dark-theme dashboard with side-by-side controls, map viewer, and scrollable terminal log output.
   - Session-specific map files are generated and automatically cleaned up when client tabs are closed.
   - Built-in local file explorer for easy navigation of your folders.

---

## Installation

### Prerequisites
Make sure Python 3.8+ is installed on your system.

### Install Dependencies
Run the following command to install the required libraries:
```bash
pip install nicegui folium pywebview pyinstaller
```

---

## How to Use

### 1. Graphical Desktop Interface (GUI)
To start the dashboard locally:
```bash
python3 pywindsurf_gui.py
```
This will start the local server and automatically open a tab in your default browser at `http://localhost:8080`.

- **Select File**: Click the folder icon next to **Data Source** to browse your local directory and select a `.tcx` file.
- **Adjust Settings**: Configure your speed units (Knots vs. km/h), segmentation scheme, and parameters.
- **Run**: Click **Run Analysis** to render the interactive map and populate the analysis output console on the right side of the screen.

### 2. Command Line Interface (CLI)
You can run the analyzer directly in your terminal:
```bash
python3 pywindsurf.py [path_to_tcx_file]
```
If the file path is omitted, the script will automatically process the first `.tcx` file it finds in the current directory.

#### CLI Arguments:
* `-u` / `--unit`: Select speed unit (`knots` or `kmh`, default: `knots`).
* `-c` / `--scheme`: Choose segmentation scheme (`speed`, `direction`, or `both`, default: `speed`).
* `--cutoff-speed`: Threshold speed for summary statistics in selected unit (default: `5.0`).
* `-m` / `--map`: Save path for the folium HTML map (default: `map.html`). Use `none` to disable mapping.

For all CLI parameters, run:
```bash
python3 pywindsurf.py --help
```

---

## Configuration Parameters

* **Segment Length (m)**: Length used to calculate general headings along the track (default: `100.0m`).
* **Angle Threshold (°)**: Heading change angle needed to trigger turn detection (default: `90.0°`).
* **Curvature Window (m)**: Lookahead/lookback distance window to pinpoint the center/apex of a turn (default: `10.0m`).
* **Merge Distance (m)**: Minimun distance threshold required between separate gybes to prevent double-marking (default: `30.0m`).
* **Speed Threshold**: Critical speed value separating active planning vs. taxi (default: `5.0`).
* **Speed Duration (s)**: Minimum consecutive time required to confirm a state transition (default: `5.0s`).
* **Bin Interval**: Speed gap width used for map color segment divisions (default: `5.0`).

---

## Standalone Packaging (PyInstaller)

If you want to package the app into a standalone executable (`.exe` on Windows, `.app` on macOS, or a binary on Linux) that can be easily shared with friends:

**On Linux / macOS:**
```bash
python -m PyInstaller --windowed --collect-all nicegui --name pywindsurf_app pywindsurf_gui.py
```

**On Windows:**
```cmd
python -m PyInstaller --windowed --collect-all nicegui --name pywindsurf_app pywindsurf_gui.py
```

* `--windowed` prevents an empty cmd shell window from launching in the background.
* `--collect-all nicegui` is required so PyInstaller copies NiceGUI's embedded Javascript, CSS, and web components.

The executable will be generated inside the `dist/pywindsurf_app/` folder.
