# Dependency and repository inventory

**Nothing in this document was installed or validated in a fresh environment.** This records observations from the source collection on November 21, 2026. Package names and versions are *observed folders*, not a lockfile or guaranteed runtime compatibility list. Do not run `pip install -r` based on this document alone.

## Core software families mentioned

Python 3; Bash; Git; OpenCV; VTracer; Tesseract; PaddleOCR/PaddlePaddle; eDOCr2 (Keras/TensorFlow); PyMuPDF; pytesseract; EasyOCR (historically explored); optional CadQuery and FreeCAD for separate, later stages. Model backends discussed historically: llama.cpp, Ollama and possibly mistral.rs. Other packages must be determined from actual source imports and the existing project environment.

## Observed isolated environments (as recorded)

### `/mnt/shopai-data-new/ShopAI-Next/projects/cad-research/environments/edocr2`

`keras-3.15.1`, `numpy-2.5.4`, `opencv_python-5.0.0.93`, `pillow-13.0.0`, `tensorflow-2.21.0`

### `/mnt/shopai-data-new/ShopAI-Next/projects/cad-research/environments/vtracer-standalone-v1`

`vtracer-0.6.15`

### `/mnt/shopai-data-new/ShopAI-Next/projects/cad-research/environments/paddleocr`

`numpy-2.3.5`, `opencv_contrib_python-4.10.0.84`, `paddleocr-3.7.0`, `paddlepaddle-3.2.0`, `paddlex-3.7.2`, `pandas-3.0.6`, `pillow-13.0.0`, `pypdfium2-5.14.0`, `shapely-2.2.0`

### `/mnt/shopai-data-new/ShopAI-Next/projects/cad-research/environments/cadquery-2.8.0-isolated-v1`

`numpy-2.5.5`, `pillow-13.0.0`, `scipy-1.18.1`

### `/mnt/shopai-data-new/ShopAI-Next/projects/cad-research/environments/common`

`numpy-2.5.4`, `onnxruntime-1.31.0`, `opencv_python_headless-5.0.0.93`, `pillow-13.0.0`, `pymupdf-2.0`, `pymupdf4llm-2.0`, `pymupdf_layout-2.0`, `pytesseract-0.3.13`, `scikit_image-0.26.0`, `scipy-1.18.1`, `shapely-2.2.0`

### `/mnt/shopai-data-new/cad-research/environments/edocr2`

`keras-3.15.1`, `numpy-2.5.4`, `opencv_python-5.0.0.93`, `pillow-13.0.0`, `tensorflow-2.21.0`

### `/mnt/shopai-data-new/cad-research/environments/vtracer-standalone-v1`

`vtracer-0.6.15`

### `/mnt/shopai-data-new/cad-research/environments/paddleocr`

`numpy-2.3.5`, `opencv_contrib_python-4.10.0.84`, `paddleocr-3.7.0`, `paddlepaddle-3.2.0`, `paddlex-3.7.2`, `pandas-3.0.6`, `pillow-13.0.0`, `pypdfium2-5.14.0`, `shapely-2.2.0`

### `/mnt/shopai-data-new/cad-research/environments/cadquery-2.8.0-isolated-v1`

`numpy-2.5.5`, `pillow-13.0.0`, `scipy-1.18.1`

### `/mnt/shopai-data-new/cad-research/environments/common`

`numpy-2.5.4`, `onnxruntime-1.31.0`, `opencv_python_headless-5.0.0.93`, `pillow-13.0.0`, `pymupdf-2.0`, `pymupdf4llm-2.0`, `pymupdf_layout-2.0`, `pytesseract-0.3.13`, `scikit_image-0.26.0`, `scipy-1.18.1`, `shapely-2.2.0`

### `/mnt/shopai-data-new/AI-Models/20-shop-library/.venv`

`docling-2.140.0`, `docling_core-2.101.1`, `docling_ibm_models-4.0.3`, `docling_parse-7.22.3`, `docling_slim-2.140.0`, `numpy-2.5.4`, `opencv_python_headless-5.0.0.93`, `pandas-3.0.6`, `pillow-12.3.0`, `pypdfium2-5.14.0`, `rapidocr-3.10.0`, `scipy-1.18.1`, `shapely-2.2.0`, `torch-2.14.1`, `torchvision-0.29.1`, `transformers-5.20.1`

## External repository locations (names only)

These are historical paths to downloaded third-party projects, not subdirectories bundled in this repository. Full paths and all 50 inventory entries are in `../INVENTORY/external_repositories_and_dependencies.json`.

- `Agent-CAD`
- `CAD-Coder`
- `CAD-Drawing-Skill`
- `CAD-Image-to-3D`
- `CADGenBench`
- `CADOCR`
- `CadQuery`
- `Drawing-to-DXF`
- `FreeCAD-Validator`
- `Image2CAD-Intwala`
- `Image2CAD-Pointer`
- `LibreCAD`
- `OCCT-Design-Loop`
- `OpenCV`
- `Ortho2CAD`
- `Scan-Vectorizer`
- `VTracer`
- `build123d`
- `cad3dify`
- `drawing2cad`
- `eDOCr`
- `eDOCr2`
- `ezdxf`
- `llama.cpp-rpc`
- `pyribs`

## Rebuilding on a fresh computer

1. Confirm the actual hardware/OS and intended machine role first.
2. Identify the exact script you intend to run and its imported dependencies.
3. Compare necessary versions with this inventory and any preserved experiment manifests.
4. Download the appropriate, legitimate upstream project/packages **separately**; preserve licenses.
5. Pin tested versions in a new isolated virtual environment rather than changing system Python.
6. Confirm model file identity, quantization, and required projectors before starting inference.
7. Test in a disposable copy with unchanged input/ground truth. Never report a migrated application as working until tested.

Do **not** automatically fetch from the Internet on ShopAI; internet access is separately permission-gated.
