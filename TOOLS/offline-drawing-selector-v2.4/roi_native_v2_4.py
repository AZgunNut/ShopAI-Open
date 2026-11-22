#!/usr/bin/env python3
"""ShopAI Native ROI v2.4: fully offline GTK3 drag/drop/paste inbox -> ready.

Additive: uses existing 01_INBOX and 02_READY, no network, no ShopAI changes.
Original source bytes are copied and verified; normalized raster derivatives are PNG.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile
import traceback
import urllib.parse
import uuid
import zipfile
import zlib

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / '01_INBOX'
CACHE = INBOX / '_NORMALIZED'
READY = ROOT / '02_READY'
LOGS = ROOT / '03_LOGS'
EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp', '.tif', '.tiff', '.svg'}


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def slug(s):
    return (re.sub(r'[^A-Za-z0-9._-]+', '_', s).strip('._')[:75] or 'drawing')


def json_write_atomic(path, obj):
    path = Path(path)
    tmp = path.parent / ('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def mask_png(path, width, height, box):
    """Native-pixel grayscale mask: 255 in selected ROI, otherwise 0."""
    x0, y0, x1, y1 = box
    assert 0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height
    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data +
                struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff))
    enc = zlib.compressobj(6)
    chunks = []
    mid = b'\0' * x0 + b'\xff' * (x1 - x0) + b'\0' * (width - x1)
    empty = b'\0' * width
    for y in range(height):
        p = enc.compress(b'\0' + (mid if y0 <= y < y1 else empty))
        if p:
            chunks.append(p)
    chunks.append(enc.flush())
    path.write_bytes(b'\x89PNG\r\n\x1a\n' +
                     chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0)) +
                     chunk(b'IDAT', b''.join(chunks)) + chunk(b'IEND', b''))


def check_svg_offline(path):
    """Reject SVG external resource references before passing it to a decoder."""
    import xml.etree.ElementTree as ET
    data = Path(path).read_bytes()
    data_lower = data.lower()
    if b'<!doctype' in data_lower or b'<!entity' in data_lower:
        raise ValueError('SVG DOCTYPE/entity is not permitted in offline mode')
    if re.search(rb'(?:https?|ftp|file):[/\\]{1,2}', data_lower) or b'@import' in data_lower:
        # XML namespace identifiers are standard, not fetched. Exclude those.
        sanitized = re.sub(rb'xmlns(?::[\w-]+)?\s*=\s*["\'][^"\']+["\']', b'', data_lower)
        if re.search(rb'(?:https?|ftp|file):[/\\]{1,2}', sanitized) or b'@import' in sanitized:
            raise ValueError('SVG has external resource references; import rejected (offline rule)')
    root = ET.fromstring(data)
    for element in root.iter():
        for name, value in element.attrib.items():
            if name.rsplit('}', 1)[-1].lower() == 'href':
                if not (value.startswith('#') or value.startswith('data:')):
                    raise ValueError('SVG links to an external resource; import rejected')
            if 'url(' in value.lower():
                for ref in re.findall(r'url\(\s*["\']?([^\s)"\']+)', value, re.I):
                    if not ref.startswith('#'):
                        raise ValueError('SVG references an external URL; import rejected')


def collect_sources():
    return sorted((p for p in INBOX.iterdir()
                   if p.is_file() and not p.is_symlink() and p.suffix.lower() in EXTS),
                  key=lambda p: p.name.casefold())


def import_file(source):
    """Copy one local file into 01_INBOX, never overwriting existing content."""
    source = Path(source)
    if source.suffix.lower() not in EXTS:
        raise ValueError('Unsupported image: ' + source.name)
    if not source.is_file() or source.is_symlink():
        raise ValueError('Not a regular local image: ' + str(source))
    if source.parent.resolve() == INBOX.resolve():
        return source  # Already in 01_INBOX; no duplicate
    basic = slug(source.stem)
    name = basic + source.suffix.lower()
    candidate = INBOX / name
    count = 1
    while candidate.exists():
        if candidate.is_file() and sha256(candidate) == sha256(source):
            return candidate
        candidate = INBOX / (basic + '_copy' + str(count) + source.suffix.lower())
        count += 1
    fd, temp = tempfile.mkstemp(prefix='.incoming_', dir=INBOX)
    try:
        with os.fdopen(fd, 'wb') as dst, source.open('rb') as src:
            shutil.copyfileobj(src, dst, 1024 * 1024)
        if sha256(temp) != sha256(source):
            raise RuntimeError('Imported file checksum mismatch')
        # Atomic no-overwrite link: never clobber a simultaneous user file.
        while True:
            try:
                os.link(temp, candidate)
                break
            except FileExistsError:
                candidate = INBOX / (basic + '_copy' + str(count) + source.suffix.lower())
                count += 1
        return candidate
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def write_index():
    entries = []
    for d in sorted(READY.iterdir()):
        if not d.is_dir() or d.is_symlink() or d.name.startswith('.building_'):
            continue
        m = d / 'manifest.json'
        if not m.exists():
            continue
        try:
            obj = json.loads(m.read_text(encoding='utf-8'))
            # Preserve v1 selections and make their expected fields discoverable.
            a = obj.get('input_name')
            if not a:
                continue
            entries.append({
                'selection_folder': d.name,
                'input_name': a,
                'source_sha256': obj.get('input_sha256'),
                'geometry_input': str(d / 'geometry_input.png'),
                'geometry_full_masked': str(d / 'geometry_full_masked.png'),
                'ocr_full_original': str(d / obj.get('ocr_full_original', 'source_full.png')),
                'ocr_raster_png': str(d / 'source_full.png') if (d / 'source_full.png').exists() else None,
                'crop_origin_px': obj.get('crop_origin_in_original_px'),
                'manifest': str(m),
            })
        except (ValueError, OSError, TypeError):
            continue
    json_write_atomic(READY / 'READY_INDEX.json', {
        'schema': 'shopai.geometry.roi_ready_index.v1', 'ready_items': entries,
        'count': len(entries),
        'note': 'Only selected inputs; no geometry engines automatically execute.'
    })
    return len(entries)


def selftest():
    from PIL import Image
    with tempfile.TemporaryDirectory(prefix='shopai-roi-v2-test-') as td:
        test = Path(td) / 'mask.png'
        mask_png(test, 112, 76, [12, 20, 86, 62])
        i = Image.open(test).convert('L')
        assert i.size == (112, 76)
        assert i.getpixel((0, 0)) == 0
        assert i.getpixel((12, 20)) == 255
        assert i.getpixel((85, 61)) == 255
        assert i.getpixel((86, 62)) == 0
    print('CORE_SELF_TEST_PASS: native-coordinate PNG mask verified')


def run_gui():
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        gi.require_version('Gdk', '3.0')
        gi.require_version('GdkPixbuf', '2.0')
        from gi.repository import Gtk, Gdk, GdkPixbuf, Gio, GLib
    except Exception as e:
        raise SystemExit('Missing local GTK3/PyGObject runtime: ' + str(e) + '\n'
                         'On Ubuntu check: /usr/bin/python3 -c "import gi; gi.require_version(\'Gtk\', \'3.0\'); from gi.repository import Gtk"\n'
                         'Requires existing OS packages python3-gi, gir1.2-gtk-3.0 and GdkPixbuf image loaders. '
                         'No online installation was attempted.')

    for p in (INBOX, CACHE, READY, LOGS):
        p.mkdir(parents=True, exist_ok=True)

    def white_rgb(w, h):
        pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, w, h)
        pb.fill(0xffffffff)
        return pb

    def to_rgb(pb):
        out = white_rgb(pb.get_width(), pb.get_height())
        if pb.get_has_alpha():
            pb.composite(out, 0, 0, out.get_width(), out.get_height(), 0, 0,
                         1.0, 1.0, GdkPixbuf.InterpType.NEAREST, 255)
        else:
            pb.copy_area(0, 0, pb.get_width(), pb.get_height(), out, 0, 0)
        return out

    def save_png(pb, path):
        pb.savev(str(path), 'png', [], [])

    def normalized_for(path):
        """Decode image locally; create lossless original-size RGB PNG raster."""
        digest = sha256(path)
        cache_file = CACHE / (digest + '.png')
        info = CACHE / (digest + '.json')
        if cache_file.is_file() and info.is_file():
            try:
                meta = json.loads(info.read_text())
                if (meta['source_sha256'] == digest and
                    meta['canonical_sha256'] == sha256(cache_file)):
                    return cache_file, meta
            except (OSError, ValueError, KeyError):
                pass
        if path.suffix.lower() == '.svg':
            check_svg_offline(path)
        src = GdkPixbuf.Pixbuf.new_from_file(str(path))
        # JPEG EXIF orientation is made explicit in the canonical PNG coordinate space.
        rotated = src.apply_embedded_orientation()
        if rotated is not None:
            src = rotated
        w, h = src.get_width(), src.get_height()
        if w < 1 or h < 1:
            raise ValueError('Empty decoded image')
        raster = to_rgb(src)
        temp = CACHE / ('.converting_' + uuid.uuid4().hex + '.png')
        try:
            save_png(raster, temp)
            if sha256(path) != digest:
                raise RuntimeError('Original source changed during import')
            os.replace(temp, cache_file)
        finally:
            temp.unlink(missing_ok=True)
        meta = {
            'schema': 'shopai.roi.canonical.v2',
            'source_sha256': digest,
            'source_name': path.name,
            'source_format': path.suffix.lower(),
            'canonical_format': 'PNG RGB 8-bit lossless raster',
            'canonical_dimensions_px': [w, h],
            'canonical_sha256': sha256(cache_file),
            'source_bytes_modified': False,
            'pixel_transform': 'EXIF orientation applied when available; SVG rasterized at decoder intrinsic size; no user resizing',
            'multi_frame_policy': 'first frame/page only for GIF/TIFF; animation not preserved',
        }
        json_write_atomic(info, meta)
        return cache_file, meta

    def make_ready(source, full_pb, box, canonical_meta):
        """Create an immutable versioned ready folder; never modify original source."""
        h0 = sha256(source)
        if h0 != canonical_meta['source_sha256']:
            raise RuntimeError('Original changed since preview. Refresh and reselect.')
        w, h = full_pb.get_width(), full_pb.get_height()
        x0, y0, x1, y1 = box
        if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h and
                x1 - x0 >= 10 and y1 - y0 >= 10):
            raise ValueError('Select a valid region of at least 10×10 pixels')
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        folder = f'{slug(source.stem)}__{h0[:12]}__{stamp}'
        dest = READY / folder
        stage = READY / ('.building_' + folder + '_' + uuid.uuid4().hex[:6])
        stage.mkdir(mode=0o700)
        try:
            ext = source.suffix.lower()
            original_name = 'source_original' + ext
            shutil.copyfile(source, stage / original_name)
            if sha256(stage / original_name) != h0:
                raise RuntimeError('Original checksum mismatch during copy')
            # Processing-standard full-image raster.
            save_png(full_pb, stage / 'source_full.png')
            # No resizing, color-quantization or altered crop coordinates.
            selected = full_pb.new_subpixbuf(x0, y0, x1 - x0, y1 - y0)
            save_png(selected, stage / 'geometry_input.png')
            masked = white_rgb(w, h)
            full_pb.copy_area(x0, y0, x1 - x0, y1 - y0, masked, x0, y0)
            save_png(masked, stage / 'geometry_full_masked.png')
            mask_png(stage / 'geometry_keep_mask.png', w, h, box)
            overlay = full_pb.copy()
            # Bright high-contrast frame on the UNMODIFIED original-size raster copy.
            thickness = max(2, min(7, round(min(w, h) / 250)))
            green = 0x00d090ff
            for bx, by, bw, bh in (
                (x0, y0, x1 - x0, min(thickness, y1 - y0)),
                (x0, max(y0, y1 - thickness), x1 - x0, min(thickness, y1 - y0)),
                (x0, y0, min(thickness, x1 - x0), y1 - y0),
                (max(x0, x1 - thickness), y0, min(thickness, x1 - x0), y1 - y0),
            ):
                if bw > 0 and bh > 0:
                    overlay.new_subpixbuf(bx, by, bw, bh).fill(green)
            save_png(overlay, stage / 'selection_overlay.png')
            manifest = {
                'schema': 'shopai.geometry.roi_ready.v2',
                'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                'input_name': source.name,
                'input_sha256': h0,
                'input_dimensions_px': [w, h],
                'native_raster_dimensions_px': [w, h],
                'roi_xyxy_exclusive': [x0, y0, x1, y1],
                'roi_size_px': [x1-x0, y1-y0],
                'crop_origin_in_original_px': [x0, y0],
                'coordinate_transform': 'canonical_full_xy = crop_xy + crop_origin; x1/y1 are exclusive',
                'canonical_source': 'source_full.png',
                'ocr_full_original': original_name,
                'ocr_full_raster': 'source_full.png',
                'geometry_input': 'geometry_input.png',
                'geometry_full_masked': 'geometry_full_masked.png',
                'geometry_keep_mask': 'geometry_keep_mask.png',
                'review_overlay': 'selection_overlay.png',
                'canonical_metadata': canonical_meta,
                'source_preserved_in_inbox': True,
                'geometry_interpretation_verified': False,
                'notes': ('ROI is a rectangle, not part silhouette. May include nearby annotations. '
                          'OCR can read the entire unmasked source_full.png. No geometry engine run.'),
            }
            json_write_atomic(stage / 'manifest.json', manifest)
            file_checks = {p.name: {'sha256': sha256(p), 'bytes': p.stat().st_size}
                           for p in sorted(stage.iterdir()) if p.is_file()}
            json_write_atomic(stage / 'SHA256_MANIFEST.json', file_checks)
            if sha256(source) != h0:
                raise RuntimeError('Original changed while saving; no result promoted')
            stage.rename(dest)
        except BaseException:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        count = write_index()
        return dest, count

    class App(Gtk.Window):
        def __init__(self):
            super().__init__(title='ShopAI — Offline Drawing ROI Selector v2.4')
            self.set_default_size(1350, 850)
            self.connect('destroy', Gtk.main_quit)
            self.connect('key-press-event', self.on_key)
            self.current = None
            self.pb = None
            self.box = None
            self.drag_start = None
            self.scale = 1.0
            self.render_width = 0
            self.render_height = 0
            self.preview_base = None
            self.fit_mode = True
            self._last_viewport_size = None
            self._listing = False
            self.last_snapshot = None
            self.build()
            self.drag_dest_set(Gtk.DestDefaults.ALL,
                               [Gtk.TargetEntry.new('text/uri-list', 0, 0),
                                Gtk.TargetEntry.new('image/png', 0, 1),
                                Gtk.TargetEntry.new('image/jpeg', 0, 2)], Gdk.DragAction.COPY)
            self.connect('drag-data-received', self.on_drop)
            self.refresh()
            GLib.timeout_add_seconds(4, self.check_inbox)
            self.show_all()
            GLib.idle_add(self.fit)

        def on_canvas_realize(self, widget):
            window = widget.get_window()
            if window is not None:
                window.set_cursor(Gdk.Cursor.new(Gdk.CursorType.CROSSHAIR))

        def btn(self, text, fn):
            b = Gtk.Button(label=text)
            b.connect('clicked', lambda *_: fn())
            return b

        def build(self):
            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            self.add(root)
            heading = Gtk.Label(label='OFFLINE  •  01_INBOX → drag-select the part → 02_READY')
            heading.set_xalign(0.0)
            heading.set_margin_start(12)
            heading.set_margin_top(8)
            root.pack_start(heading, False, False, 0)
            tip = Gtk.Label(label='Drop or paste a file, then DOUBLE-CLICK its name in the left list to display and auto-fit. '
                                  'Drag a rectangle on the drawing; originals stay intact.')
            tip.set_xalign(0.0)
            tip.set_margin_start(12)
            root.pack_start(tip, False, False, 0)
            bar = Gtk.Box(spacing=5)
            bar.set_margin_start(8)
            bar.set_margin_end(8)
            root.pack_start(bar, False, False, 0)
            for label, fn in [
                ('Add Files…', self.choose_files),
                ('Paste Image / Files', self.paste),
                ('Refresh INBOX', self.refresh),
                ('Fit', self.fit),
                ('Zoom +', lambda: self.zoom(1.25)),
                ('Zoom −', lambda: self.zoom(0.8)),
                ('Clear Box', self.clear_box),
                ('Save to 02_READY', self.save_selection),
                ('Open READY Folder', self.open_ready),
            ]:
                bar.pack_start(self.btn(label, fn), False, False, 0)
            split = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
            split.set_position(290)
            root.pack_start(split, True, True, 0)
            left = Gtk.ScrolledWindow()
            left.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            self.files = Gtk.ListBox()
            self.files.set_selection_mode(Gtk.SelectionMode.SINGLE)
            # GTK ListBox activation is double-click only, even for a selected row.
            self.files.set_activate_on_single_click(False)
            self.files.connect('row-activated', self.on_row_activated)
            left.add(self.files)
            split.pack1(left, False, False)
            self.scroller = Gtk.ScrolledWindow()
            self.scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            self.scroller.set_hexpand(True)
            self.scroller.set_vexpand(True)
            # The GTK Image owns pixel rendering. The DrawingArea draws ONLY the ROI
            # rectangle above it. No Python Cairo callback is used,
            # and avoids shrinking the picture itself to 1x1 during initial layout.
            self.canvas = Gtk.Overlay()
            self.canvas.set_hexpand(True)
            self.canvas.set_vexpand(True)
            self.preview = Gtk.Image()
            self.preview.set_halign(Gtk.Align.START)
            self.preview.set_valign(Gtk.Align.START)
            self.canvas.add(self.preview)
            # EventBox is an input-only mouse layer. No Python Cairo draw signal.
            # GTK.Image below renders the source; redraw_preview() adds the
            # rectangle to a copy of its pixels using GdkPixbuf.
            self.area = Gtk.EventBox()
            self.area.set_visible_window(False)
            self.area.set_hexpand(True)
            self.area.set_vexpand(True)
            self.area.set_halign(Gtk.Align.FILL)
            self.area.set_valign(Gtk.Align.FILL)
            self.area.set_app_paintable(True)
            self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                                 Gdk.EventMask.POINTER_MOTION_MASK)
            self.area.connect('realize', self.on_canvas_realize)
            self.area.connect('button-press-event', self.on_press)
            self.area.connect('motion-notify-event', self.on_motion)
            self.area.connect('button-release-event', self.on_release)
            self.canvas.add_overlay(self.area)
            self.canvas.set_overlay_pass_through(self.area, False)
            self.scroller.add_with_viewport(self.canvas)
            self.scroller.connect('size-allocate', self.on_viewport_allocate)
            split.pack2(self.scroller, True, False)
            self.status = Gtk.Label(label='Drop images here or into 01_INBOX; no network used.')
            self.status.set_xalign(0.0)
            self.status.set_line_wrap(True)
            self.status.set_margin_start(10)
            self.status.set_margin_bottom(8)
            root.pack_start(self.status, False, False, 0)

        def message(self, s):
            self.status.set_text(str(s))
            print(str(s), flush=True)

        def error(self, s):
            self.message('ERROR: ' + str(s))
            dialog = Gtk.MessageDialog(transient_for=self, flags=0, message_type=Gtk.MessageType.ERROR,
                                       buttons=Gtk.ButtonsType.OK, text='ShopAI ROI tool')
            dialog.format_secondary_text(str(s))
            dialog.run()
            dialog.destroy()

        def choose_files(self):
            dlg = Gtk.FileChooserDialog(title='Add drawings to 01_INBOX', parent=self,
                                        action=Gtk.FileChooserAction.OPEN)
            dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                            Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
            dlg.set_select_multiple(True)
            flt = Gtk.FileFilter()
            flt.set_name('Supported images')
            for ext in sorted(EXTS):
                flt.add_pattern('*' + ext)
                flt.add_pattern('*' + ext.upper())
            dlg.add_filter(flt)
            if dlg.run() == Gtk.ResponseType.OK:
                names = dlg.get_filenames()
                dlg.destroy()
                self.import_paths(names)
            else:
                dlg.destroy()

        def import_paths(self, paths):
            good, errs = [], []
            for p in paths:
                try:
                    new = import_file(p)
                    # Convert upon import, not only after selection.
                    normalized_for(new)
                    good.append(new)
                except Exception as exc:
                    errs.append(f'{p}: {exc}')
            self.refresh(prefer_path=good[-1] if good else None)
            if good and self.pb is not None and self.current == good[-1]:
                self.message(f'Imported/normalized {len(good)} image(s) into 01_INBOX; '
                             f'NOW DISPLAYING: {good[-1].name}. Drag a box, then Save to 02_READY.')
            if errs:
                self.error('\n'.join(errs[:5]))

        def on_drop(self, _widget, context, _x, _y, data, info, when):
            accepted = False
            try:
                if info in (1, 2):
                    pb = data.get_pixbuf()
                    if pb is not None:
                        self.paste_pixbuf(pb, 'dropped')
                        accepted = True
                else:
                    paths = []
                    for uri in data.get_uris() or []:
                        p = Gio.File.new_for_uri(uri).get_path()
                        if p:
                            paths.append(p)
                    if paths:
                        self.import_paths(paths)
                        accepted = True
                if not accepted:
                    self.error('Drop local image files, or an image copied from another app; external URLs are rejected.')
            except Exception as ex:
                self.error('Drop failed: ' + str(ex))
            Gtk.drag_finish(context, accepted, False, when)

        def paste_pixbuf(self, pb, label):
            stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            p = INBOX / (label + '_' + stamp + '_' + uuid.uuid4().hex[:6] + '.png')
            save_png(pb, p)
            normalized_for(p)
            self.refresh(prefer_path=p)
            self.message('NOW DISPLAYING pasted/dropped image: ' + str(p.name) + '. Drag a box to select.')

        def paste(self):
            cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            try:
                uris = cb.wait_for_uris()
                if uris:
                    paths = [Gio.File.new_for_uri(u).get_path() for u in uris]
                    paths = [p for p in paths if p]
                    if paths:
                        self.import_paths(paths)
                        return
                # GNOME Files may use its own clipboard target for copied files.
                atom = Gdk.Atom.intern('x-special/gnome-copied-files', False)
                payload = cb.wait_for_contents(atom)
                if payload is not None and payload.get_data():
                    raw = bytes(payload.get_data()).decode('utf-8', 'replace')
                    paths = [Gio.File.new_for_uri(u.strip()).get_path() for u in raw.splitlines()[1:]
                             if u.strip().startswith('file://')]
                    paths = [p for p in paths if p]
                    if paths:
                        self.import_paths(paths)
                        return
                pb = cb.wait_for_image()
                if pb is not None:
                    self.paste_pixbuf(pb, 'pasted')
                    return
                text = cb.wait_for_text()
                if text:
                    p = Path(text.strip().strip('"\''))
                    if p.is_absolute() and p.is_file():
                        self.import_paths([p])
                        return
                self.message('Clipboard contains no supported image or local file paths.')
            except Exception as ex:
                self.error('Paste failed: ' + str(ex))

        def on_key(self, _widget, event):
            if event.keyval in (Gdk.KEY_v, Gdk.KEY_V) and event.state & Gdk.ModifierType.CONTROL_MASK:
                self.paste()
                return True
            return False

        def snapshot(self):
            return tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in collect_sources())

        def check_inbox(self):
            try:
                snap = self.snapshot()
                if snap != self.last_snapshot:
                    self.refresh()
            except OSError:
                pass
            return True

        def refresh(self, prefer_path=None):
            """Keep list and visible preview in sync; show the newest imported image.

            prefer_path is supplied by drop, paste, or Add Files. When files are
            copied directly into 01_INBOX, detect new arrivals and open the most
            recently modified one. Plain refresh preserves the current drawing.
            """
            if self._listing:
                return
            try:
                paths = collect_sources()
                previous = self.current
                previous_hash = (self.meta.get('source_sha256')
                                 if previous and getattr(self, 'meta', None) else None)
                old_names = {name for name, *_ in (self.last_snapshot or ())}
                new_paths = [p for p in paths if p.name not in old_names] if self.last_snapshot is not None else []
                if prefer_path is not None:
                    preferred = Path(prefer_path)
                elif new_paths:
                    preferred = max(new_paths, key=lambda p: (p.stat().st_mtime_ns, p.name))
                else:
                    preferred = previous

                good_paths, failed = [], []
                for p in paths:
                    try:
                        normalized_for(p)
                        good_paths.append(p)
                    except Exception as exc:
                        failed.append(f'{p.name}: {exc}')

                # Rebuild only while temporarily blocking selection callbacks.
                self._listing = True
                try:
                    for child in self.files.get_children():
                        self.files.remove(child)
                    rows = []
                    for p in good_paths:
                        row = Gtk.ListBoxRow()
                        row.path = p
                        label = Gtk.Label(label=p.name)
                        label.set_xalign(0.0)
                        label.set_line_wrap(True)
                        label.set_margin_top(8)
                        label.set_margin_bottom(8)
                        label.set_margin_start(6)
                        row.add(label)
                        self.files.add(row)
                        rows.append(row)
                    self.files.show_all()
                finally:
                    self._listing = False

                self.last_snapshot = self.snapshot()
                if rows:
                    selected = next((row for row in rows if row.path == preferred), rows[0])
                    self.files.select_row(selected)
                    # Explicit update also works if GTK doesn't emit row-selected
                    # when a recycled selection has the same row/path.
                    needs_load = (self.pb is None or self.current != selected.path or
                                  (selected.path == previous and previous_hash is not None and
                                   sha256(selected.path) != previous_hash))
                    if needs_load:
                        self.load_source(selected.path)
                else:
                    self.current = None
                    self.pb = None
                    self.box = None
                    self.drag_start = None
                    self.render_width = self.render_height = 0
                    self.preview_base = None
                    self.preview.clear()
                    self.message('01_INBOX has no readable drawings. Drop/paste/Add Files.')
                if failed:
                    self.message(f'{len(failed)} image(s) could not be decoded: ' + '; '.join(failed[:2]))
            except Exception as e:
                self.error('Refresh failed: ' + str(e))

        def on_row_activated(self, _listbox, row):
            """Double-click ALWAYS opens and fits the row's file in the right pane."""
            if self._listing or row is None:
                return
            try:
                path = Path(row.path)
                self.load_source(path)  # intentionally reload even if already selected
                self.files.select_row(row)
                self.message(f'DISPLAYED & FIT: {path.name}. Drag a box over the part, then Save to 02_READY.')
            except Exception as e:
                self.error(f'Could not display {getattr(row, "path", "selected file")}: {e}')

        def load_source(self, path):
            cache_path, meta = normalized_for(path)
            self.pb = GdkPixbuf.Pixbuf.new_from_file(str(cache_path))
            self.current = path
            self.meta = meta
            self.box = None
            self.drag_start = None
            self.fit_mode = True
            # Immediately display a native GTK image, BEFORE layout-based scaling.
            # A failed/zero-size fit must never leave a blank right pane.
            self.show_preview(1.0)
            GLib.idle_add(self.fit)
            GLib.timeout_add(130, self.fit)
            GLib.timeout_add(400, self.fit)
            self.message(f'{path.name}: {self.pb.get_width()}×{self.pb.get_height()} PNG processing pixels. '
                         'Drag a rectangle around the part. Source is unchanged.')

        def show_preview(self, requested_scale):
            """Show the image with GTK's native pixbuf widget, never a Cairo paint."""
            if self.pb is None:
                return
            w, h = self.pb.get_width(), self.pb.get_height()
            s = max(.04, min(8.0, float(requested_scale)))
            outw = max(1, round(w*s))
            outh = max(1, round(h*s))
            if (outw, outh) == (self.render_width, self.render_height) and self.preview.get_pixbuf() is not None:
                self.scale = s
                return
            shown = (self.pb if (outw, outh) == (w, h) else
                     self.pb.scale_simple(outw, outh, GdkPixbuf.InterpType.BILINEAR))
            if shown is None:
                raise RuntimeError('GTK image scaling failed; no visible preview')
            self.preview_base = shown
            self.render_width, self.render_height = outw, outh
            self.scale = s
            self.redraw_preview()
            print(f'ROI_PREVIEW_PIXBUF_SET source={self.current.name if self.current else "unknown"} '
                  f'source_px={w}x{h} displayed_px={outw}x{outh}', flush=True)

        def redraw_preview(self):
            """Native GTK pixbuf overlay: no Cairo callback required."""
            if self.preview_base is None:
                return
            if not self.box:
                self.preview.set_from_pixbuf(self.preview_base)
            else:
                p = self.preview_base.copy()
                w, h = self.pb.get_width(), self.pb.get_height()
                x0, y0, x1, y1 = self.box
                x0 = max(0, min(self.render_width, round(x0*self.render_width/w)))
                y0 = max(0, min(self.render_height, round(y0*self.render_height/h)))
                x1 = max(0, min(self.render_width, round(x1*self.render_width/w)))
                y1 = max(0, min(self.render_height, round(y1*self.render_height/h)))
                thick = max(2, min(5, self.render_width//160))
                green = 0x00FF70FF  # RGBA native-pixbuf fill
                for rx, ry, rw, rh in (
                    (x0, y0, x1-x0, min(thick, y1-y0)),
                    (x0, max(y0,y1-thick), x1-x0, min(thick, y1-y0)),
                    (x0, y0, min(thick,x1-x0), y1-y0),
                    (max(x0,x1-thick), y0, min(thick,x1-x0), y1-y0),
                ):
                    if rw>0 and rh>0:
                        p.new_subpixbuf(rx,ry,rw,rh).fill(green)
                self.preview.set_from_pixbuf(p)

        def on_viewport_allocate(self, _widget, allocation):
            size = (allocation.width, allocation.height)
            if size != self._last_viewport_size:
                self._last_viewport_size = size
                if self.fit_mode and self.pb is not None and min(size) >= 100:
                    GLib.idle_add(self.fit)

        def zoom(self, multiplier):
            if self.pb is None:
                return
            self.fit_mode = False
            self.show_preview(self.scale * multiplier)

        def fit(self):
            """Fit image to actual pane; skip premature <100px initial allocations."""
            if self.pb is None:
                return False
            vw, vh = self.scroller.get_allocated_width(), self.scroller.get_allocated_height()
            if vw < 100 or vh < 100:
                print(f'ROI_FIT_DEFERRED pane={vw}x{vh}', flush=True)
                return False
            self.fit_mode = True
            # Reserve a small margin for scrollbars, rather than using the
            # previous stale 1-pixel viewport allocations.
            scale = min(1.0, (vw - 24)/self.pb.get_width(),
                        (vh - 24)/self.pb.get_height())
            self.show_preview(scale)
            return False

        def clear_box(self):
            self.box = None
            self.redraw_preview()
            self.message('Selection cleared. No saved READY results removed.')

        def point(self, event):
            """Pointer pixels in the GTK overlay to exact canonical source pixels."""
            w, h = self.pb.get_width(), self.pb.get_height()
            if self.render_width < 1 or self.render_height < 1:
                raise RuntimeError('Image not displayed yet')
            def clean(v):
                nearest = round(v)
                return float(nearest) if abs(v-nearest) < 1e-8 else v
            return [max(0.0, min(float(w), clean(event.x*w/self.render_width))),
                    max(0.0, min(float(h), clean(event.y*h/self.render_height)))]

        def bbox(self, a, b):
            return [math.floor(min(a[0], b[0])), math.floor(min(a[1], b[1])),
                    math.ceil(max(a[0], b[0])), math.ceil(max(a[1], b[1]))]

        def on_press(self, _widget, event):
            if self.pb is None or event.button != 1:
                return False
            if (event.x < 0 or event.y < 0 or
                event.x >= self.render_width or event.y >= self.render_height):
                self.message('Click inside the visible drawing to start the selection box.')
                return False
            self.drag_start = self.point(event)
            self.box = None
            self.redraw_preview()
            return True

        def on_motion(self, _widget, event):
            if self.drag_start is not None:
                self.box = self.bbox(self.drag_start, self.point(event))
                self.redraw_preview()
                return True
            return False

        def on_release(self, _widget, event):
            if self.drag_start is not None:
                self.box = self.bbox(self.drag_start, self.point(event))
                self.drag_start = None
                self.redraw_preview()
                x0, y0, x1, y1 = self.box
                if x1-x0 < 10 or y1-y0 < 10:
                    self.box = None
                    self.redraw_preview()
                    self.message('Box too small (minimum 10×10 pixels); drag again.')
                else:
                    self.message(f'Selected [x0,y0,x1,y1] = {self.box} ({x1-x0}×{y1-y0} pixels). '
                                 'Click Save to 02_READY.')
                return True
            return False

        def save_selection(self):
            if not self.current or self.pb is None or not self.box:
                self.message('Choose a drawing and drag a rectangle first.')
                return
            try:
                dest, count = make_ready(self.current, self.pb, self.box, self.meta)
                self.message(f'SAVED: {dest}\nCrop: geometry_input.png; full-size masked: '
                             f'geometry_full_masked.png; full PNG: source_full.png. '
                             f'READY index now includes {count} selections.')
            except Exception as exc:
                self.error('Save failed (original unchanged): ' + str(exc))

        def open_ready(self):
            try:
                Gio.AppInfo.launch_default_for_uri(READY.as_uri(), None)
            except Exception as ex:
                self.message('READY folder: ' + str(READY) + ' (' + str(ex) + ')')

    app = App()
    Gtk.main()


if __name__ == '__main__':
    if '--self-test' in sys.argv:
        try:
            selftest()
        except ImportError:
            # No optional Pillow needed on target; mask parser can still check raw bytes.
            with tempfile.TemporaryDirectory() as td:
                p = Path(td) / 'mask.png'
                mask_png(p, 112, 76, [12, 20, 86, 62])
                b = p.read_bytes()
                assert b[:8] == b'\x89PNG\r\n\x1a\n'
                assert struct.unpack('>II', b[16:24]) == (112, 76)
            print('CORE_SELF_TEST_PASS: standard-library mask and dimensions verified')
    else:
        try:
            run_gui()
        except Exception as e:
            print('STARTUP ERROR:', e, file=sys.stderr)
            sys.exit(1)
