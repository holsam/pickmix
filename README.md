# pickmix

Multi-kind particle picking GUI for cryo-ET sub-tomogram-averaging workflows.

Pickmix supports picking multiple kinds of user-defined particles from reconstructed tomograms, with built-in SNR-based refinement estimation and a 2D average validation step, for export as a RELION 5-compatible coordinate `.star` file.

## Installation
### Requirements
- Python (≥3.14)
- [`uv`](https://docs.astral.sh/uv/) package manager

### Installation command

```sh
uv tool install git+https://github.com/holsam/pickmix
pickmix [path/to/config.toml]
```
For development, use `uv sync` then `uv run pickmix`.

## Inputs

- One or more RELION projects. Each project must have a tomogram job (default `Tomograms/job006`) which contains a `tomograms.star`.
- Reconstructed tomograms. All raw tomograms should be located (symbolic linking is supported) within a single directory as MRC files. The header shape and pixel size of each MRC file must agree with `tomograms.star`, otherwise the tomogram will be rejected.
- [OPTIONAL] Denoised tomograms. All denoised tomograms should be located (symbolic linking is supported) within a single directory as MRC files. Denoised tomograms can contain an additional specified suffix (e.g. `.denoised`) that will be included when matching to raw tomograms.

## How to use `pickmix`
### 1. Create a project

Launch pickmix using `pickmix`. The welcome page has two buttons for opening an existing project (also via `Ctrl/Cmd+O`) and creating a new project (also via `Ctrl/Cmd+N`).

![Welcome page](docs/images/welcome-page.png)

Click `[New project]`, and complete the fields in the dialog. Hover over a field's `(?)` for further information about each field. Pickmix merges all the entered runs into a single `tomograms.star` and writes `config.toml` in the project directory. Tomogram names get the run name as a prefix. Existing files are never overwritten.

![New project dialog](docs/images/new-project.png)

### 2. Check the project and define kinds

`pickmix` will now open to the Project tab, which contains the three columns described below. 

![Project tab](docs/images/project-tab.png)

#### 2.1 Tomograms
This table lists every tomogram alongside its shape, pixel size and whether a matching denoised volume was identified. Yellow warning indicate usable tomograms with issues to be aware of (e.g. no denoised tomogram found, unusual pixel size), while a red error marks a rejected or unusable tomogram - hover over the error to see the reaon.

#### 2.2 Kinds
Each 'kind' is a type of pick and multiple can be added as required. Each kind has a marker size, an extraction box, an estimator (`ring` fits a circle to a pick, `none` passes the click straight through), a colour, an optional parent kind and an extraction pixel size. A kind with a parent takes its membrane-normal orientation from the nearest parent estimate.

![Kinds dialog](docs/images/kinds-dialog.png)

#### 2.3 Settings
This pane controls general settings for the project, including which volume to use in the picking interface and which hotkeys map to which kinds. Parameters for the `ring` estimator can also be adjusted here as required.

### 3. Pick

Open the Pick tab. To the left is a a list of tomograms in the project, clicking a tomogram will jump there as will typing either its name or number into the search bar (the search bar automatically moves to the first match). If needed, the tomogram list can be hidden using the button next to the tomogram title. Select a kind using a hotkey or from the Kinds group, and left-click to add or select a pick. Picks can be moved by selecting & dragging, or deleted using the delete button (or `Delete` key). Right-click to pan across the current slice, and Ctrl/Cmd+Scroll to adjust zoom. Scrolling updates the current Z slice, and `Enter`/`Shift+Enter` steps forward/backward between tomograms. The settings pane has brightness/contrast controls, including `Auto` (the tomogram's own limits) and `Invert`, as well as auto-zoom functions `Fit` and `Fill`. The views group shows/hides fitted rings, boxes and normals. The pick table beneath shows each pick's estimate status: a green tick, a yellow warning (when flagged), a red error (when error occured during estimation), or a blue spinner (during processing).

![Pick tab](docs/images/pick-tab.png)

### 4. Review

Open the Review tab. Picks can be filtered by kind, tomogram, minimum SNR and whether they were flagged, with options to delete the selected pick or all currently shown. All picks can be queued for re-estimation here if required as well. Single-click a pick to view XY/XZ/YZ previews, or double-click to open that pick in the Pick tab.

![Review tab](docs/images/review-tab.png)

### 5. Average and export

Open the Export tab. At the top, the averaging pane allows selection of a kind to build a mean projection and montage of the picks for that kind (optionally filterable by tomogram). The mean and montage images can be saved to `out/` from here, as well as per-tomogram extracted picks if desired. Below, a table summarises the collected data for all kinds and allow specification of a minimum SNR and whether to include flagged picks in exports. Click the checkboxes for the desired output filetype(s) and click `Export` to save. `Extract` alternatively generates a subvolume from each pick and saves as MRC files under `out/particles/<kind>`.

![Export tab](docs/images/export-tab.png)

## Project layout

```
project/
  config.toml        settings and kinds
  tomograms.star     merged RELION tomogram table
  tilt_series/       one star file per tomogram
  out/               picks, estimates, averages, RELION & .csv exports
```
