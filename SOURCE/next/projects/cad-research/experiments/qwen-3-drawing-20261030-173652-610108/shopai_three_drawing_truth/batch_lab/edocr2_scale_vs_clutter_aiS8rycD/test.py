import ast
import copy
import json
import sys
import typing
from pathlib import Path

import cv2
import numpy as np
import tensorflow as tf
from tensorflow import keras
from PIL import Image, ImageDraw, ImageFont

SOURCE, MODELS, DRAWING, OUT = [
    Path(p) for p in sys.argv[1:]
]

# Build the inference architecture from original source.
tree = ast.parse(
    (SOURCE / 'recognition.py').read_text(encoding='utf8')
)

needed = ('_repeat', '_meshgrid', '_transform', 'build_model')

functions = {
    n.name: copy.deepcopy(n)
    for n in tree.body
    if isinstance(n, ast.FunctionDef)
    and n.name in needed
}

assert set(functions) == set(needed)

params = next(
    n for n in tree.body
    if isinstance(n, ast.Assign)
    and any(
        isinstance(t, ast.Name)
        and t.id == 'DEFAULT_BUILD_PARAMS'
        for t in n.targets
    )
)

builder = functions['build_model']

end = next(
    i for i, n in enumerate(builder.body)
    if isinstance(n, ast.Assign)
    and any(
        isinstance(t, ast.Name) and t.id == 'model'
        for t in n.targets
    )
)

builder.body = builder.body[:end + 1] + [
    ast.Return(
        value=ast.Name(id='model', ctx=ast.Load())
    )
]

module = ast.fix_missing_locations(
    ast.Module(
        body=[copy.deepcopy(params)] +
             [functions[n] for n in needed],
        type_ignores=[]
    )
)

ns = {'tf': tf, 'keras': keras}

exec(
    compile(module, str(SOURCE / 'recognition.py'), 'exec'),
    ns
)

alphabet = (
    MODELS / 'recognizer_dimensions_2.txt'
).read_text(encoding='utf8').strip()

model = ns['build_model'](
    alphabet=alphabet,
    **ns['DEFAULT_BUILD_PARAMS']
)

model.load_weights(
    str(MODELS / 'recognizer_dimensions_2.keras')
)

assert tuple(model.input_shape[1:]) == (31, 200, 1)
assert model.output_shape[-1] == len(alphabet) + 1

print(
    'PASS: Weights loaded; degree symbol supported:',
    '°' in alphabet,
    flush=True
)

# Load upstream image fitting.
tree = ast.parse(
    (SOURCE / 'tools.py').read_text(encoding='utf8')
)

fns = [
    copy.deepcopy(n)
    for n in tree.body
    if isinstance(n, ast.FunctionDef)
    and n.name in ('fit', 'read_and_fit')
]

assert {n.name for n in fns} == {'fit', 'read_and_fit'}

tools_ns = {
    'np': np,
    'cv2': cv2,
    'typing': typing
}

exec(
    compile(
        ast.fix_missing_locations(
            ast.Module(body=fns, type_ignores=[])
        ),
        str(SOURCE / 'tools.py'),
        'exec'
    ),
    tools_ns
)

read_and_fit = tools_ns['read_and_fit']

inputs = []
records = []

def submit(kind, label, variant, img, source_ref):
    if img.size == 0:
        raise ValueError('Empty image crop')

    if img.ndim == 2:
        img = cv2.cvtColor(
            img, cv2.COLOR_GRAY2RGB
        )

    fitted = read_and_fit(
        img,
        width=200,
        height=31,
        cval=0
    )

    gray = cv2.cvtColor(
        fitted, cv2.COLOR_RGB2GRAY
    )

    assert gray.shape == (31, 200)

    inputs.append(
        gray[..., None].astype('float32') / 255.0
    )

    records.append({
        'kind': kind,
        'reference_label': label,
        'variant': variant,
        'source': source_ref
    })

    cv2.imwrite(
        str(OUT / f'input_{len(records):03d}.png'),
        gray
    )

def render_text(label, fontpath):
    font = ImageFont.truetype(str(fontpath), 32)

    dummy = Image.new(
        'RGB', (250, 80), (255, 255, 255)
    )

    bbox = ImageDraw.Draw(dummy).textbbox(
        (0, 0), label, font=font
    )

    w = bbox[2] - bbox[0] + 8
    h = bbox[3] - bbox[1] + 8

    canvas = Image.new(
        'RGB', (w, h), (255, 255, 255)
    )

    ImageDraw.Draw(canvas).text(
        (4 - bbox[0], 4 - bbox[1]),
        label,
        font=font,
        fill=(0, 0, 0)
    )

    return np.asarray(canvas)

# ---------------------------------------------------
# TEST A: How far can we reduce clean text?
# ---------------------------------------------------

print(
    '\n=== SYNTHETIC RESOLUTION EXPERIMENT ===',
    flush=True
)

font_dir = (
    SOURCE.parent / 'tools' / 'dimension_fonts'
)

fonts = [
    font_dir / 'Cardo-Regular.ttf',
    font_dir / 'Mplus1p-Regular.ttf'
]

for font in fonts:
    if not font.is_file():
        raise SystemExit(
            'Missing reference font: ' + str(font)
        )

    for label in ('35°', '40°'):
        full = render_text(label, font)

        submit(
            'synthetic',
            label,
            f'{font.stem}_full',
            full,
            str(font)
        )

        for height in (8, 10, 12, 16):
            width = max(
                1,
                int(round(
                    full.shape[1] *
                    height / full.shape[0]
                ))
            )

            reduced = cv2.resize(
                full,
                (width, height),
                interpolation=cv2.INTER_AREA
            )

            submit(
                'synthetic',
                label,
                f'{font.stem}_{height}px_high',
                reduced,
                str(font)
            )

# ---------------------------------------------------
# TEST B: D3 actual pixels and surrounding geometry
# ---------------------------------------------------

print(
    '\n=== D3 CROP EXPERIMENT ===',
    flush=True
)

original = cv2.imread(
    str(DRAWING),
    cv2.IMREAD_GRAYSCALE
)

assert original is not None

H, W = original.shape

regions = {
    '35°': {
        'paddle_box': (259, 194, 276, 208),
        'digit_band': (259, 197, 279, 208),
        'top_and_right': (258, 190, 283, 210),
        'wide_context': (254, 186, 284, 215),
        'digit_tight': (261, 197, 279, 207)
    },
    '40°': {
        'paddle_box': (258, 239, 276, 251),
        'digit_band': (259, 242, 282, 251),
        'top_and_right': (258, 239, 284, 252),
        'wide_context': (253, 233, 286, 257),
        'digit_tight': (260, 241, 282, 251)
    }
}

for label, variants in regions.items():
    for name, coords in variants.items():
        x0, y0, x1, y1 = coords

        assert 0 <= x0 < x1 <= W
        assert 0 <= y0 < y1 <= H

        crop = original[y0:y1, x0:x1]

        # One variable at a time:
        # crop boundaries, then image thresholding.
        for prep in (
            'raw',
            'threshold160',
            'threshold210',
            'otsu'
        ):
            if prep == 'raw':
                processed = crop

            elif prep == 'otsu':
                _, processed = cv2.threshold(
                    crop, 0, 255,
                    cv2.THRESH_BINARY +
                    cv2.THRESH_OTSU
                )

            else:
                threshold = int(
                    prep.replace('threshold', '')
                )

                _, processed = cv2.threshold(
                    crop,
                    threshold,
                    255,
                    cv2.THRESH_BINARY
                )

            submit(
                'D3',
                label,
                name + '_' + prep,
                processed,
                coords
            )

# ---------------------------------------------------
# RUN INFERENCE
# ---------------------------------------------------

print(
    '\nTotal inference inputs:',
    len(records),
    flush=True
)

X = np.stack(inputs)

probs = model(
    X,
    training=False
).numpy()

assert probs.shape[0] == len(records)
assert np.isfinite(probs).all()

# CTC greedy decoding; final class is blank.
logits = tf.transpose(
    tf.math.log(
        tf.clip_by_value(
            probs, 1e-7, 1.0
        )
    ),
    (1, 0, 2)
)

lengths = tf.fill(
    (len(records),),
    tf.shape(logits)[0]
)

sparse, _ = tf.nn.ctc_greedy_decoder(
    logits,
    lengths,
    merge_repeated=True
)

decoded = tf.sparse.to_dense(
    sparse[0],
    default_value=-1
).numpy()

for i, (record, row) in enumerate(
    zip(records, decoded)
):
    record['prediction'] = ''.join(
        alphabet[int(x)]
        for x in row
        if 0 <= int(x) < len(alphabet)
    )

    record['degree_peak'] = round(
        float(
            probs[
                i, :, alphabet.index('°')
            ].max()
        ),
        6
    )

    record['exact_match'] = (
        record['prediction'] ==
        record['reference_label']
    )

# ---------------------------------------------------
# REPORT EVERYTHING
# ---------------------------------------------------

print('\n=== SYNTHETIC RESOLUTION RESULTS ===')

for r in records:
    if r['kind'] == 'synthetic':
        print(
            r['reference_label'],
            r['variant'],
            '->',
            repr(r['prediction']),
            'degree_peak=',
            r['degree_peak']
        )

print('\n=== REAL D3 RESULTS ===')

for r in records:
    if r['kind'] == 'D3':
        print(
            r['reference_label'],
            r['variant'],
            '->',
            repr(r['prediction']),
            'degree_peak=',
            r['degree_peak']
        )

print('\n=== SUMMARY ===')

for kind in ('synthetic', 'D3'):
    subset = [
        r for r in records
        if r['kind'] == kind
    ]

    correct = sum(
        r['exact_match']
        for r in subset
    )

    print(
        kind,
        correct,
        '/',
        len(subset),
        'exact matches'
    )

report = {
    'model': str(
        MODELS / 'recognizer_dimensions_2.keras'
    ),
    'drawing': str(DRAWING),
    'preprocessing': (
        'Upstream read_and_fit, black padding, '
        'grayscale /255'
    ),
    'decoder': (
        'TensorFlow CTC greedy, blank last'
    ),
    'notes': (
        'Synthetic downsampling is diagnostic, '
        'not a D3 accuracy measure. '
        'Reference labels are used only for scoring.'
    ),
    'results': records
}

(OUT / 'results.json').write_text(
    json.dumps(
        report,
        indent=2,
        ensure_ascii=False
    )
)

print(
    '\nRESULTS:',
    OUT / 'results.json'
)

print(
    'INPUT IMAGES:',
    OUT / 'input_*.png'
)

print(
    'No original programs, OCR results, '
    'models, or services modified.',
    flush=True
)
