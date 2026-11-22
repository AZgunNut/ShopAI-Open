import ast
import copy
import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import tensorflow as tf
from tensorflow import keras
from PIL import Image, ImageDraw, ImageFont

root, source, models, ocr_path, image_path, out = map(
    Path, sys.argv[1:]
)

print(
    "VERSIONS",
    "tf=" + tf.__version__,
    "keras=" + keras.__version__,
    "cv2=" + cv2.__version__,
    flush=True
)

# ==========================================================
# 1. RECONSTRUCT VERIFIED INFERENCE ARCHITECTURE
# ==========================================================

tree = ast.parse(
    (source / "edocr2/keras_ocr/recognition.py").read_text(
        encoding="utf-8"
    )
)

needed = (
    "_repeat",
    "_meshgrid",
    "_transform",
    "build_model",
)

func = {
    n.name: copy.deepcopy(n)
    for n in tree.body
    if isinstance(n, ast.FunctionDef)
    and n.name in needed
}

params = next(
    n for n in tree.body
    if isinstance(n, ast.Assign)
    and any(
        isinstance(t, ast.Name)
        and t.id == "DEFAULT_BUILD_PARAMS"
        for t in n.targets
    )
)

assert set(func) == set(needed)

builder = func["build_model"]

end = next(
    i for i, n in enumerate(builder.body)
    if isinstance(n, ast.Assign)
    and any(
        isinstance(t, ast.Name) and t.id == "model"
        for t in n.targets
    )
)

builder.body = builder.body[:end + 1] + [
    ast.Return(
        value=ast.Name(id="model", ctx=ast.Load())
    )
]

module = ast.fix_missing_locations(
    ast.Module(
        body=[copy.deepcopy(params)]
        + [func[n] for n in needed],
        type_ignores=[]
    )
)

ns = {"tf": tf, "keras": keras}

exec(
    compile(
        module,
        str(source / "edocr2/keras_ocr/recognition.py"),
        "exec"
    ),
    ns
)

alphabet = (
    models / "recognizer_dimensions_2.txt"
).read_text(encoding="utf-8").strip()

model = ns["build_model"](
    alphabet=alphabet,
    **ns["DEFAULT_BUILD_PARAMS"]
)

model.load_weights(
    str(models / "recognizer_dimensions_2.keras")
)

assert model.input_shape[1:] == (31, 200, 1)
assert model.output_shape[-1] == len(alphabet) + 1

print("MODEL WEIGHTS LOADED")
print("ALPHABET:", repr(alphabet), flush=True)

# ==========================================================
# 2. LOAD ACTUAL UPSTREAM PREPROCESSING FUNCTIONS
# ==========================================================

tree2 = ast.parse(
    (source / "edocr2/keras_ocr/tools.py").read_text(
        encoding="utf-8"
    )
)

funcs = [
    copy.deepcopy(n)
    for n in tree2.body
    if isinstance(n, ast.FunctionDef)
    and n.name in ("fit", "read_and_fit")
]

assert {n.name for n in funcs} == {
    "fit",
    "read_and_fit"
}

tns = {"np": np, "cv2": cv2, "typing": __import__("typing")}

exec(
    compile(
        ast.fix_missing_locations(
            ast.Module(body=funcs, type_ignores=[])
        ),
        "upstream_tools.py",
        "exec"
    ),
    tns
)

read_and_fit = tns["read_and_fit"]

print("UPSTREAM PREPROCESSING LOADED", flush=True)

# ==========================================================
# 3. FIND OR GENERATE LABELED REFERENCE SAMPLES
# ==========================================================

font_paths = sorted(
    (source / "edocr2/tools/dimension_fonts").glob("*.ttf")
)

if len(font_paths) < 2:
    font_paths += list(
        Path("/usr/share/fonts").rglob("DejaVuSans*.ttf")
    )[:2]

font_paths = list(dict.fromkeys(font_paths))[:2]

if not font_paths:
    raise SystemExit(
        "STOP: No existing fonts for reference samples"
    )

print("\nREFERENCE FONTS:")

for font in font_paths:
    print(" ", font)

def render_sample(text, fontpath, size=32):
    font = ImageFont.truetype(str(fontpath), size)

    blank = Image.new(
        "RGB", (400, 100), (255, 255, 255)
    )

    draw = ImageDraw.Draw(blank)

    bbox = draw.textbbox(
        (0, 0),
        text,
        font=font
    )

    draw.text(
        (4 - bbox[0], 4 - bbox[1]),
        text,
        font=font,
        fill=(0, 0, 0)
    )

    w = min(
        blank.width,
        max(20, bbox[2] - bbox[0] + 9)
    )

    h = min(
        blank.height,
        max(20, bbox[3] - bbox[1] + 9)
    )

    return np.asarray(
        blank.crop((0, 0, w, h)).copy()
    )

samples = []

# Use existing repository reference pairs if present.
for imgfile in sorted(source.rglob("*.png")):
    txtfile = imgfile.with_suffix(".txt")

    if not txtfile.is_file():
        continue

    label = txtfile.read_text(
        encoding="utf-8",
        errors="replace"
    ).strip()

    if not (
        label
        and len(label) <= 16
        and all(ch in alphabet for ch in label)
    ):
        continue

    im = cv2.imread(
        str(imgfile),
        cv2.IMREAD_COLOR
    )

    if im is not None:
        samples.append((
            "repository",
            label,
            cv2.cvtColor(im, cv2.COLOR_BGR2RGB),
            str(imgfile)
        ))

    if len(samples) >= 6:
        break

print(
    "EXISTING REPOSITORY LABELED SAMPLES:",
    len(samples)
)

# Independently generated reference text.
# Ground truth is established by rendering, not OCR.
for font in font_paths:
    for label in ("35°", "40°", "0.75", "12.5"):

        if not all(ch in alphabet for ch in label):
            continue

        samples.append((
            "synthetic",
            label,
            render_sample(label, font),
            str(font)
        ))

# ==========================================================
# 4. EXTRACT D3 REGIONS
# ==========================================================

doc = json.loads(
    ocr_path.read_text(encoding="utf-8")
)

rows = [
    r for r in doc["rows"]
    if r.get("profiles") == "1060+1947"
    and r.get("plan") == "whole"
]

assert len(rows) == 1

im = cv2.imread(
    str(image_path),
    cv2.IMREAD_COLOR
)

assert im is not None

H, W = im.shape[:2]

regions = []

for desired in ("35°", "40"):

    groups = [
        g for g in rows[0]["results"]
        if desired in [
            a.get("text")
            for a in g.get("alternatives", [])
            if isinstance(a, dict)
        ]
    ]

    assert len(groups) == 1, (
        desired,
        len(groups)
    )

    x0, y0, x1, y1 = map(
        int,
        groups[0]["anchor"]
    )

    for variant, right in (
        ("exact", 0),
        ("right6", 6)
    ):

        xA = max(0, x0)
        yA = max(0, y0)
        xB = min(W, x1 + right)
        yB = min(H, y1)

        roi = cv2.cvtColor(
            im[yA:yB, xA:xB],
            cv2.COLOR_BGR2RGB
        )

        assert roi.size > 0

        regions.append((
            desired,
            variant,
            roi,
            [xA, yA, xB, yB]
        ))

# ==========================================================
# 5. COMPARE ORIGINAL AND INVERTED INPUT
# ==========================================================

inputs = []
records = []

def add(kind, label, roi, origin, variant):

    if roi.ndim == 2:
        roi = cv2.cvtColor(
            roi,
            cv2.COLOR_GRAY2RGB
        )

    for polarity in ("original", "inverted"):

        sourceimg = (
            roi
            if polarity == "original"
            else cv2.bitwise_not(roi)
        )

        fitted = read_and_fit(
            sourceimg,
            width=200,
            height=31,
            cval=0
        )

        assert fitted.shape == (31, 200, 3)

        gray = cv2.cvtColor(
            fitted,
            cv2.COLOR_RGB2GRAY
        )

        records.append({
            "kind": kind,
            "label": label,
            "variant": variant,
            "polarity": polarity,
            "source": origin
        })

        k = len(records)

        cv2.imwrite(
            str(out / f"input_{k:03d}.png"),
            gray
        )

        inputs.append(
            gray[..., None].astype("float32")
            / 255.0
        )

for kind, label, roi, origin in samples:
    add(
        kind,
        label,
        roi,
        origin,
        "reference"
    )

for target, variant, roi, box in regions:
    add(
        "D3",
        target,
        roi,
        box,
        variant
    )

# ==========================================================
# 6. INFERENCE — NO RETRAINING
# ==========================================================

X = np.stack(inputs)

print(
    "\nINFERENCES:",
    len(records),
    flush=True
)

probs = model(
    X,
    training=False
).numpy()

assert np.isfinite(probs).all()

# CTC greedy decoding, final class reserved as blank.
logits = tf.transpose(
    tf.math.log(
        tf.clip_by_value(
            probs,
            1e-7,
            1.0
        )
    ),
    (1, 0, 2)
)

lengths = tf.fill(
    (len(records),),
    tf.shape(logits)[0]
)

decoded, _ = tf.nn.ctc_greedy_decoder(
    logits,
    lengths,
    merge_repeated=True
)

decoded_rows = tf.sparse.to_dense(
    decoded[0],
    default_value=-1
).numpy()

assert len(decoded_rows) == len(records)

# ==========================================================
# 7. INDEPENDENT SCORING AND REPORT
# ==========================================================

print("\n=== RECOGNITION RESULTS ===")

for i, (rec, row) in enumerate(
    zip(records, decoded_rows)
):

    rec["predicted"] = "".join(
        alphabet[int(j)]
        for j in row
        if 0 <= int(j) < len(alphabet)
    )

    rec["degree_peak"] = round(
        float(
            probs[
                i,
                :,
                alphabet.index("°")
            ].max()
        ),
        6
    )

    rec["exact"] = (
        rec["predicted"] == rec["label"]
    )

    print(
        f"{rec['kind']:10s} "
        f"{rec['label']:6s} "
        f"{rec['variant']:10s} "
        f"{rec['polarity']:8s} "
        f"-> {rec['predicted']!r} "
        f"degree_peak={rec['degree_peak']:.5f}",
        flush=True
    )

report = {
    "model": str(
        models / "recognizer_dimensions_2.keras"
    ),
    "model_sha256": hashlib.sha256(
        (
            models / "recognizer_dimensions_2.keras"
        ).read_bytes()
    ).hexdigest(),
    "image": str(image_path),
    "image_sha256": hashlib.sha256(
        image_path.read_bytes()
    ).hexdigest(),
    "input_preprocessing": (
        "Upstream read_and_fit(), cval=0, "
        "original versus inverted polarity"
    ),
    "decoder": (
        "TensorFlow CTC greedy, blank last"
    ),
    "reference_samples_used_as_model_prompts": False,
    "notes": (
        "Synthetic references use local fonts and "
        "are not certified published benchmark samples. "
        "D3 crops come from previous PaddleOCR boxes."
    ),
    "results": records
}

(out / "results.json").write_text(
    json.dumps(
        report,
        indent=2,
        ensure_ascii=False
    )
)

print("\n=== SUMMARY ===")

for kind in (
    "repository",
    "synthetic",
    "D3"
):
    rr = [
        r for r in records
        if r["kind"] == kind
    ]

    for polarity in ("original", "inverted"):

        group = [
            r for r in rr
            if r["polarity"] == polarity
        ]

        if group:
            correct = sum(
                r["exact"]
                for r in group
            )

            print(
                f"{kind} {polarity}: "
                f"{correct}/{len(group)} exact"
            )

print(
    "\nRESULT_JSON",
    out / "results.json"
)

print(
    "Original files/models unchanged; "
    "no network used."
)
