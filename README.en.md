<p align="center">
  <img src="assets/logo.png" width="96" alt="Zhubi">
</p>

<h1 align="center">Zhubi (朱笔)</h1>

<p align="center">
  <b>A self-hosted image annotation and fine-tuning workbench</b><br>
  Draw boxes, export datasets, fine-tune Florence-2 or YOLO, and validate the result, all on your own machine.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-blue.svg" alt="AGPL-3.0 License"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/backend-Flask-000000?logo=flask&logoColor=white" alt="Flask">
  <img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey" alt="macOS | Linux">
  <img src="https://img.shields.io/badge/status-tech%20validation%20demo-orange" alt="tech validation demo">
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#what-it-does">What it does</a> ·
  <a href="#who-its-for">Who it's for</a> ·
  <a href="#roadmap">Roadmap</a> ·
  <a href="README.md">中文</a>
</p>

> **Technical-validation demo**, run from source. Developed and verified on macOS (Apple Silicon); Linux and NVIDIA GPUs use the same code paths but are not systematically tested. Training needs the weights from upstream [OmniParser](https://github.com/microsoft/OmniParser) as base models; annotation and export do not.

<p align="center">
  <img src="assets/hero.gif" alt="Open a project, draw a box on a screenshot, save and move to the next image, then pick YOLO on the export page" width="100%">
</p>
<p align="center">
  <sub>Opening the "垂直图标训练" project, drawing a box around a browser icon on a phone screenshot, saving into the next image, then choosing YOLO on the export page. A real local project: 50 screenshots, 125 boxes.</sub>
</p>

## Sound familiar?

- You want an icon detector for your own product UI, but the labeling tool, export script, training script and validation script live in four places, and every step means fixing paths.
- Hosted labeling platforms want your screenshots uploaded. Internal-system screenshots cannot leave the company, so you glue tools together yourself.
- You labeled a batch, trained, and the result is poor. Data problem or parameter problem? There is no way to put it next to the base model and compare.
- You use OmniParser as a GUI agent, it misses the icons in your vertical app, and you want to fine-tune with a few hundred samples but cannot find a tool that fits.

Zhubi puts the whole chain into one web page that runs on your machine: create a project, draw boxes, export five formats in one click, fine-tune Florence-2 with LoRA or train YOLO, and upload one image to compare before and after.

## What it does

### 1. Create a project, upload images

A project is one set of categories and one batch of images. After a bulk upload, each card shows image count, labeled count and category count.

<p align="center"><img src="assets/projects.png" alt="Project list with image, labeled and category counts" width="800"></p>
<p align="center"><sub>Four local projects; "垂直图标训练" has all 50 images labeled, "yolo" has 200 images and 3 classes.</sub></p>

### 2. Draw boxes, drive with the keyboard

Drag a rectangle on the canvas; keys 1 to 9 switch category, S saves, N goes to the next image, D deletes, Ctrl+Z undoes. The right panel lists every box on the current image with its coordinates; grid, labels and snapping can be toggled; progress sits in the top left.

<p align="center"><img src="assets/annotate.png" alt="Annotation page: image list on the left, red boxes on the canvas, box list, categories and stats on the right" width="900"></p>
<p align="center"><sub>A 1440×3200 phone screenshot with three "ViaBrower" boxes over the browser icon; on the right, the box list, the category panel and project stats.</sub></p>

### 3. Export five formats in one click

The same annotations export as COCO, YOLO, Pascal VOC, CSV, or the format Florence-2 fine-tuning expects. Train, validation and test splits are made automatically; augmentation and automatic negative samples can be added before export.

<p align="center"><img src="assets/export.png" alt="Export page: project stats and five format cards" width="800"></p>
<p align="center"><sub>With "垂直图标训练" selected: 50 images, 125 boxes, class distribution, and YOLO chosen below.</sub></p>

### 4. Fine-tune locally

Pick YOLO or Florence-2, then one of three presets (quick check, standard, production) or set epochs, learning rate, LoRA rank and augmentation yourself. Training runs in the background while the page shows loss, epoch and logs live; you can stop and resume.

<p align="center"><img src="assets/train.png" alt="Training page: model choice and three smart presets" width="800"></p>
<p align="center"><sub>Training configuration: YOLO or Florence-2, three presets with epochs, augmentation level and estimated time.</sub></p>

### 5. Every run is kept, ready to resume or deploy

Finished models are listed per project and time, each card recording sample count, final loss, learning rate, LoRA parameters and data split. Continue training from any of them, or deploy one into OmniParser's weights directory with one click.

<p align="center"><img src="assets/models.png" alt="Trained model list with time, samples, loss and LoRA parameters per card" width="900"></p>
<p align="center"><sub>Six Florence-2 fine-tuning runs under "垂直图标训练"; the loss under each LoRA rank and augmentation strategy is visible at a glance, and each card can resume or deploy.</sub></p>

### 6. Upload one image, see before and after

The validation page runs the base model and the fine-tuned model on a new screenshot side by side. The OmniParser comparison page runs the full OmniParser pipeline (YOLO detection plus Florence-2 captions) with both sets of weights.

## Who it's for

- **People running OmniParser or a similar GUI agent** whose base model misses the icons in their product and who need to fine-tune with extra samples.
- **Test and RPA teams detecting UI elements** whose screenshots cannot go to a third-party platform.
- **Independent developers with small vision projects**: a few hundred images, a few classes, and no appetite for an MLOps stack.
- **Anyone who wants to see what LoRA fine-tuning actually changed**: every run's parameters and loss stay on a card for comparison.

## Quick start

You need Python 3.10+ and a modern browser.

```bash
git clone https://github.com/icesword0760/zhubi.git
cd zhubi
pip install -r requirements.txt

python app.py
```

Open <http://localhost:8003>, create a project and upload images to start labeling and exporting.

**To train or compare models** you also need an OmniParser checkout with its weights (`weights/icon_detect`, `weights/icon_caption_florence`). Put it next to Zhubi as `../OmniParser`, or point to it explicitly:

```bash
export OMNIPARSER_ROOT=/path/to/OmniParser
python app.py
```

`config.yaml` holds the port, data directories, split ratios, training defaults and shortcuts. Training outputs, export archives and uploaded images live under `data/` and never enter the repository.

## Roadmap

None of this exists yet:

- The "trained YOLO models" list on the validation page. It only shows the base model; trained YOLO weights need a manual path.
- Installers or a Docker image. Source only for now.
- Systematic Linux and NVIDIA GPU verification.
- Multi-user collaboration and annotation review. It is a single-user, single-machine tool.
- Annotation types beyond rectangles, such as polygons or keypoints.

## Developer notes

<details>
<summary><b>Layout</b></summary>

```
app.py                     Flask entry point: project, annotation, export, training, validation and comparison APIs; serves the frontend
backend/
  project_manager.py       projects and images
  annotation_manager.py    annotation read/write and bounds validation
  crop_manager.py          crop icon samples from boxes
  export_manager.py        COCO / YOLO / VOC / CSV / Florence-2 export and splitting
  data_augmentor.py        augmentation
  train_manager.py         Florence-2 LoRA fine-tuning (resume, early stopping)
  yolo_train_manager.py    YOLO training
  model_validator.py       single-model validation and two-model comparison
add_negative_samples.py    automatic negative samples
frontend/                  plain HTML + CSS + JS, no build step
tests/                     unittest regression tests (python -m unittest discover -s tests)
scripts/capture_assets.py  regenerate the README screenshots and GIF with Playwright
docs/                      detailed guides on annotation, training, export formats, resuming and augmentation
```

</details>

<details>
<summary><b>Relationship to OmniParser</b></summary>

Zhubi ships neither OmniParser code nor weights. Training reads base models from `OMNIPARSER_ROOT/weights`; the OmniParser comparison and automatic negative samples import `OMNIPARSER_ROOT/util`. Without them, annotation, export and training YOLO from scratch still work.

</details>

## Feedback and license

Questions and ideas are welcome in [Issues](https://github.com/icesword0760/zhubi/issues).

Licensed under [AGPL-3.0](LICENSE): use, modify and redistribute freely, but modified versions must be released under the same license, whether you distribute them or run them as a network service. If it saved you from gluing labeling and training scripts together, a star helps others find it.
