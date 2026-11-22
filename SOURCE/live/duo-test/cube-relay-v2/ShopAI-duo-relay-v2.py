#!/usr/bin/env python3
"""Local, checklist-driven Director/Viewer relay; never executes model commands."""
import argparse
import base64
import hashlib
import json
import math
import os
import struct
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.home() / 'ShopAI'
DIRECTOR_URL = 'http://127.0.0.1:11434/api/chat'
VIEWER_URL = 'http://127.0.0.1:18081/v1/chat/completions'
CHECKLIST = [
    'Identify and confirm the visible view labels and their XYZ projection planes against the locked datum.',
    'Read the written overall dimensions and units, one dimension at a time.',
    'Locate outer contour corners/endpoints, one view or feature at a time, relative to the locked zero.',
    'Locate hole centers and visible circles, one feature at a time, relative to the locked zero.',
    'Locate slots, steps, recesses, and other internal features, one feature at a time.',
    'Read feature position dimensions and their reference endpoints, one dimension at a time.',
    'Read radius, diameter, depth, thread, and tolerance callouts, one callout at a time.',
    'Determine feature Cartesian part coordinates ONLY from written dimensions and constraints, one feature at a time. Use the locked common XYZ zero.',
    'Check corresponding feature coordinates between views using the locked XYZ projections.',
    'Recheck inconsistencies and list missing dimensions or unresolved coordinates.',
]
DATUM_PROMPT = '''IMPORTANT: This task requests a WORKING MODEL COORDINATE ORIGIN, NOT a formal GD&T datum. A printed datum symbol is NOT required. Lack of a printed datum is NOT a reason to refuse. You MUST choose a convenient actual part corner when no printed origin is available, and identify source as chosen. This is explicitly authorized by the user.
Inspect the attached mechanical drawing. Establish ONE common XYZ part zero and its projection in every shown orthographic view (two or three).
Use an existing drawing origin if clearly established. Otherwise you are AUTHORIZED to CHOOSE a convenient physical reference point on the part (e.g., a clearly identifiable corner) as zero. Label its source chosen. Reporting a chosen origin truthfully does not pretend that it was printed. The zero is a coordinate convention, not a claim about the original drawing.
Choose a single common physical point, not three unrelated local corners. Maintain corresponding X/Y/Z axes across the projections.
Read explicit written dimension units; if no unit label is visible, use unknown. Decimal formatting alone does not prove inches. Do not assume scale or convert pixels to part lengths.
Image Cartesian coordinates: bottom-left origin, x right, y up, original image pixel units.
Return ONLY JSON with this schema:
{"answer":"brief explanation", "datum":{
 "source":"drawing|chosen", "origin_feature":"precise description of the ONE physical zero point",
 "units":"mm|inch|unknown", "common_zero":[0,0,0], "uncertainty":"unresolved correspondence or orientation",
 "views":[{"id":"front/top/side or actual label", "plane":["X","Z"],
 "horizontal_axis":"X", "vertical_axis":"Z", "horizontal_sign":1, "vertical_sign":1,
 "origin_pixel":[x,y], "origin_evidence":"how the common zero projects here"}]
}}.
Give ONLY the two or three orthographic views actually shown, each with a distinct appropriate XYZ projection plane. Never invent a third view. Signs are +1 or -1 for rightward/upward increases. origin_pixel may be null if not locatable; do not invent it.
Only if the actual geometry/views cannot be read well enough to define consistent projections (NOT merely because a datum is unprinted), return {"answer":"unclear", "datum":null}.
'''
DIRECTOR_PROMPT = '''You are the Director for a mechanical drawing inspection. You CANNOT see the image.
Keep a continuing conversation with a fresh Viewer. Work through the supplied checklist IN ORDER.
Ask exactly one short, specific question per turn. Split views/features into separate questions.
Never fabricate Viewer observations or dimensions. Treat all coordinates as UNVERIFIED estimates.
Image Cartesian coordinates: origin bottom-left; x right; y up; pixels. Do not confuse pixels with mm/inches.
Physical part coordinates require legible printed dimensions, an established origin, and enough constraints. When printed units are unknown, retain the raw numerical coordinates in drawing_units without assuming a physical unit. Blind-hole depths may exclude the conical drill point; keep cylindrical depth and drill-tip depth separate and leave an undimensioned tip unresolved.
Do not infer a hidden dimension or assume the drawing is to scale. Keep missing information unresolved.
The provided LOCKED_DATUM is immutable. Never move its zero or change its view axes. Read written dimensions before deriving part coordinates.
Assess the previous Viewer answer: accepted, rejected, needs_recheck, or none. Accepted means provisionally usable, not independently verified.
Return ONLY JSON with keys:
{"decision":"accepted|rejected|needs_recheck|none", "reason":"brief assessment",
 "action":"ask|advance", "question":"one question when action=ask"}.
Use advance when this checklist item is exhausted or cannot be resolved. Never give commands or code.
'''
VIEWER_PROMPT = '''You are the Viewer. Use ONLY the attached drawing and answer ONLY the current question.
Do not plan, ask your own next question, execute commands, or infer missing dimensions.
Coordinates are image pixels in CARTESIAN format: bottom-left origin (0,0), x right, y up.
Use supplied original image width/height; do not report coordinates from a resized image frame.
Visual coordinates are estimates; say unclear when location cannot be established. Do not invent exact precision.
Printed dimensions are separate from pixel coordinates. Copy visible text only. Read blind-hole depth notes carefully: a depth excluding the conical drill point is the cylindrical portion, not total tip depth. Do not convert pixels into physical units.
Return ONLY JSON:
{"answer":"concise answer or unclear", "observations":[
 {"id":"feature identifier", "view":"view or unknown", "kind":"feature type",
 "description":"what is actually visible", "points":[[x,y]],
 "dimension_text":null, "uncertainty":"what is estimated or unclear"}
]}.
Use empty points when no location can be read; dimension_text is a quoted visible callout or null.
The supplied LOCKED_DATUM defines ONE immutable XYZ zero and the axes for all visible projections. Never choose another zero or axes.
For each observation you may add part_coordinate: {"x":number_or_null,"y":number_or_null,"z":number_or_null,"units":"mm|inch|drawing_units","basis":["exact printed dimension and reference endpoint"]}.
Use null for part_coordinate unless legible WRITTEN dimensions and constraints establish it relative to the locked zero. If datum units are unknown, use drawing_units for the written numerical values; do not assume mm or inches. Do not derive lengths from pixel scale. Use null for each unestablished component. All part coordinates remain unverified until checked.
'''

def atomic_json(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    os.replace(temp, path)

def call_json(url, payload, timeout=18000):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)

def parse_json(text):
    text = text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object; raw response was saved.')
    return value

def validate_observations(value, width, height, datum=None):
    if not isinstance(value.get('answer'), str) or not isinstance(value.get('observations'), list):
        raise ValueError('Viewer response lacks answer/observations.')
    for observation in value['observations']:
        if not isinstance(observation, dict):
            raise ValueError('Observation must be an object.')
        points = observation.get('points', [])
        if not isinstance(points, list):
            raise ValueError('Points must be an array.')
        for point in points:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError('Each Cartesian point must be [x,y].')
            x, y = point
            if any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in point):
                raise ValueError('Coordinates must be finite numbers.')
            if not (0 <= x <= width-1 and 0 <= y <= height-1):
                raise ValueError('Coordinate lies outside the original image; needs recheck.')
        physical = observation.get('part_coordinate')
        if physical is not None:
            if not isinstance(physical, dict) or datum is None:
                raise ValueError('Part coordinate requires a locked datum.')
            expected_units = 'drawing_units' if datum['units'] == 'unknown' else datum['units']
            if physical.get('units') != expected_units:
                raise ValueError('Part coordinate units conflict with locked datum.')
            if not isinstance(physical.get('basis'), list) or not physical['basis'] or not all(isinstance(v, str) and v.strip() for v in physical['basis']):
                raise ValueError('Part coordinates require written dimension evidence.')
            for axis in ('x', 'y', 'z'):
                number = physical.get(axis)
                if number is not None and (isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number)):
                    raise ValueError('Part coordinate must contain finite numbers or null.')
            physical['verification'] = 'unverified_dimension_based_model_result'
        observation['coordinate_system'] = 'image_cartesian_bottom_left'
        observation['coordinate_units'] = 'pixels'
        observation['verification'] = 'unverified_model_observation'
    return value

def validate_datum(datum, width, height):
    if not isinstance(datum, dict) or datum.get('source') not in ('drawing', 'chosen'):
        raise ValueError('MechVL could not establish a datum; raw proposal saved.')
    if not isinstance(datum.get('origin_feature'), str) or not datum['origin_feature'].strip():
        raise ValueError('Datum needs a physical origin description.')
    if datum.get('common_zero') != [0, 0, 0] or datum.get('units') not in ('mm', 'inch', 'unknown'):
        raise ValueError('Invalid datum zero or units.')
    views = datum.get('views')
    if not isinstance(views, list) or len(views) not in (2, 3):
        raise ValueError('Datum must define the two or three visible projections.')
    planes, ids = set(), set()
    for view in views:
        if not isinstance(view, dict) or not isinstance(view.get('id'), str):
            raise ValueError('Each datum projection needs a view identifier.')
        ids.add(view['id'])
        axes = [view.get('horizontal_axis'), view.get('vertical_axis')]
        if any(axis not in ('X', 'Y', 'Z') for axis in axes) or axes[0] == axes[1]:
            raise ValueError('Each projection needs two distinct XYZ axes.')
        if view.get('plane') != axes:
            raise ValueError('Projection plane must match horizontal/vertical axes.')
        planes.add(frozenset(axes))
        if any(type(view.get(key)) is not int or view[key] not in (-1, 1) for key in ('horizontal_sign', 'vertical_sign')):
            raise ValueError('Projection axis directions must be +1 or -1.')
        pixel = view.get('origin_pixel')
        if pixel is not None:
            validate_observations({'answer':'datum', 'observations':[{'points':[pixel]}]}, width, height)
    if len(ids) != len(views) or len(planes) != len(views) or set().union(*planes) != set('XYZ'):
        raise ValueError('Visible projections must have distinct planes and cover the XYZ axes.')
    datum['locked'] = True
    datum['verification'] = 'model_proposed_requires_geometric_check'
    return datum

def director_turn(messages):
    result = call_json(DIRECTOR_URL, {
        'model': 'qwen3.5:4b', 'messages': messages, 'stream': False, 'think': False,
        'format': 'json', 'options': {'temperature': 0.1, 'num_predict': 512, 'num_ctx': 8192},
    })
    return result['message']['content']

def viewer_turn(question, image_content, width, height, datum=None, system_prompt=None):
    # Fresh Viewer conversation, including the image, on every request.
    if datum is not None:
        question += '\nLOCKED_DATUM (immutable):\n' + json.dumps(datum)
    content = [{'type': 'text', 'text': f'Original image: {width} x {height} pixels.\nQuestion: {question}'}, image_content]
    result = call_json(VIEWER_URL, {
        'model': '/media/shopai/Extra Space/AI-Models/MechVL-4B-RL-Q8/MechVL-4B-RL.Q8_0.gguf',
        'messages': [{'role': 'system', 'content': system_prompt or VIEWER_PROMPT}, {'role': 'user', 'content': content}],
        'stream': False, 'temperature': 0.1, 'max_tokens': 1024,
    })
    return result['choices'][0]['message']['content']

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rounds', type=int, default=12, help='maximum Viewer questions this run')
    parser.add_argument('--new', action='store_true', help='start a new inspection instead of resuming')
    args = parser.parse_args()
    if not 1 <= args.rounds <= 100:
        parser.error('--rounds must be between 1 and 100')
    shared = ROOT / 'duo-test'
    image_path = Path((shared / 'drawing_path.txt').read_text().strip()).expanduser()
    data = image_path.read_bytes()
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('This first relay version requires the selected PNG drawing.')
    if len(data) > 12 * 1024 * 1024:
        raise ValueError('Image exceeds 12 MiB input limit.')
    width, height = struct.unpack('>II', data[16:24])
    digest = hashlib.sha256(data).hexdigest()
    image_content = {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(data).decode()}}
    # Confirm the existing Viewer; do not start another server/model process.
    with urllib.request.urlopen('http://127.0.0.1:18081/health', timeout=5) as response:
        if json.load(response).get('status') != 'ok':
            raise ValueError('MechVL server is not ready. Start ShopAI option 5 first.')
    state_path = shared / 'relay-state.json'
    if state_path.exists() and not args.new:
        state = json.loads(state_path.read_text())
        if state['image_sha256'] != digest:
            raise ValueError('Selected drawing changed. Use --new for a separate inspection.')
        run = Path(state['run_directory'])
    else:
        run = shared / ('relay-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        run.mkdir(parents=True)
        state = {'image_path': str(image_path), 'image_sha256': digest, 'image_width': width,
                 'image_height': height, 'run_directory': str(run), 'step': 0,
                 'round': 0, 'step_questions': 0, 'messages': [{'role': 'system', 'content': DIRECTOR_PROMPT}],
                 'observations': [], 'checklist': CHECKLIST, 'assessments': []}
    print(f'Director: Qwen 4B (continuing conversation)\nViewer: MechVL (fresh image request each turn)\nDrawing: {image_path}\nSize: {width} x {height}\nRecords: {run}\nCtrl+C stops; run the same command to resume.\n', flush=True)
    if 'datum' not in state:
        print('MechVL establishing the common XYZ datum for all visible views...', flush=True)
        proposal = viewer_turn('Establish the common zero and its visible projections now.', image_content,
                               width, height, system_prompt=DATUM_PROMPT)
        (run / 'datum-proposal.txt').write_text(proposal)
        datum = validate_datum(parse_json(proposal).get('datum'), width, height)
        state['datum'] = datum
        state['datum_sha256'] = hashlib.sha256(json.dumps(datum, sort_keys=True).encode()).hexdigest()
        atomic_json(run / 'locked-datum.json', datum)
    else:
        datum = state['datum']
        if hashlib.sha256(json.dumps(datum, sort_keys=True).encode()).hexdigest() != state['datum_sha256']:
            raise ValueError('Saved datum was changed; relay refuses to continue.')
    print('LOCKED common datum:\n' + json.dumps(datum, indent=2), flush=True)
    atomic_json(state_path, state)
    asked = 0
    last_viewer = None
    while state['step'] < len(CHECKLIST) and asked < args.rounds:
        step = state['step']
        instruction = 'LOCKED_DATUM (immutable):\n' + json.dumps(datum) + '\n' + f'Checklist item {step+1}/{len(CHECKLIST)}: {CHECKLIST[step]}\nOriginal image size: {width} x {height}. Questions asked on this item: {state["step_questions"]}. '
        if state['step_questions'] >= 5:
            instruction += 'Advance now and identify unresolved information in your reason. '
        if last_viewer is not None:
            instruction += '\nPrevious Viewer response:\n' + json.dumps(last_viewer)
        messages = state['messages'] + [{'role': 'user', 'content': instruction}]
        print(f'Checklist {step+1}: Director preparing question/assessment...', flush=True)
        raw = director_turn(messages)
        (run / f'director-{state["round"]+1}-step-{step+1}-{state["step_questions"]}.txt').write_text(raw)
        decision = parse_json(raw)
        if decision.get('decision') not in ('accepted', 'rejected', 'needs_recheck', 'none') or decision.get('action') not in ('ask', 'advance'):
            raise ValueError('Invalid Director decision; raw response saved. No commands were executed.')
        action = decision['action']
        if state['step_questions'] >= 5:
            action = 'advance'
        if action == 'advance':
            state['messages'] = messages + [{'role': 'assistant', 'content': raw}]
            state['assessments'].append({'checklist_item': step+1, 'round': state['round'], 'forced_advance': state['step_questions'] >= 5, **decision})
            state['step'] += 1
            state['step_questions'] = 0
            last_viewer = None
            atomic_json(state_path, state)
            continue
        question = decision.get('question')
        if not isinstance(question, str) or not question.strip():
            raise ValueError('Director did not provide a question.')
        number = state['round'] + 1
        print(f'\n**** QUESTION {number} ****\n{question}\nMechVL reading drawing...', flush=True)
        (shared / 'director_to_viewer.txt').write_text(question + '\n')
        raw_viewer = viewer_turn(question, image_content, width, height, datum=datum)
        (run / f'viewer-{number}.txt').write_text(raw_viewer)
        viewer = validate_observations(parse_json(raw_viewer), width, height, datum=datum)
        print('_____ RESPONSE _____\n' + json.dumps(viewer, indent=2) + '\n', flush=True)
        (shared / 'viewer_to_director.txt').write_text(json.dumps({'question': question, 'response': viewer}, indent=2) + '\n')
        state['assessments'].append({'checklist_item': step+1, 'round': state['round'], 'forced_advance': state['step_questions'] >= 5, **decision})
        state['messages'] = messages + [{'role': 'assistant', 'content': raw},
            {'role': 'user', 'content': 'Actual Viewer response to your question:\n' + json.dumps(viewer)}]
        for observation in viewer['observations']:
            state['observations'].append({'round': number, 'checklist_item': step+1, **observation})
        state['round'] = number
        state['step_questions'] += 1
        last_viewer = viewer
        atomic_json(state_path, state)
        atomic_json(run / 'coordinate-records.json', {'image_path': str(image_path), 'image_size': [width, height],
            'locked_datum': datum, 'coordinate_system': {'origin': 'bottom-left pixel', 'x': 'right', 'y': 'up', 'units': 'pixels'},
            'observations': state['observations'], 'director_assessments': state['assessments']})
        with (run / 'exchange-log.jsonl').open('a') as handle:
            handle.write(json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(), 'round': number,
                                    'checklist_item': step+1, 'question': question, 'viewer': viewer}) + '\n')
        asked += 1
    print('Checklist complete.' if state['step'] == len(CHECKLIST) else f'Paused after {asked} Viewer questions; run again to continue.', flush=True)
    print(f'Coordinate records: {run / "coordinate-records.json"}\nAPI cost: estimated $0; actual $0.')

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped. Completed exchanges are saved; run again to resume.')
    except Exception as exc:
        print(f'\nRelay stopped: {exc}\nCompleted exchanges and raw responses remain saved.', file=sys.stderr)
        sys.exit(1)
