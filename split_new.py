#!/usr/bin/env python3
import xml.etree.ElementTree as ET
import os
import re
import argparse
from copy import deepcopy
from collections import defaultdict

def sanitize_filename(name: str) -> str:
    if not name:
        name = "Unnamed_Layer"
    return re.sub(r'[^\w\-_\.]+', '_', name).strip("_")

def _first_diagram(mxfile_root: ET.Element) -> ET.Element:
    diag = mxfile_root.find('diagram')
    if diag is None:
        raise ValueError("Kein <diagram> gefunden.")
    return diag

def _mxgraphmodel(diagram: ET.Element) -> ET.Element:
    mgm = diagram.find('mxGraphModel')
    if mgm is None:
        mgm = diagram.find('.//mxGraphModel')
    if mgm is None:
        raise ValueError("Kein <mxGraphModel> gefunden.")
    return mgm

def _mxroot(mgm: ET.Element) -> ET.Element:
    mxr = mgm.find('root')
    if mxr is None:
        raise ValueError("Kein <root> unter <mxGraphModel> gefunden.")
    return mxr

def _build_indices(mx_root: ET.Element):
    id_index = {}
    children = defaultdict(list)
    for el in mx_root.iter():
        el_id = el.attrib.get('id')
        if el_id:
            id_index[el_id] = el
        parent = el.attrib.get('parent')
        if parent:
            children[parent].append(el)
    return id_index, children

def _top_layer_id(el: ET.Element, id_index: dict) -> str | None:
    """Verfolge parent-Kette bis parent='0'. Liefere die Top-Layer-ID (direktes Kind von 0)."""
    cur = el
    seen = set()
    while True:
        pid = cur.attrib.get('parent')
        if not pid:
            return None
        if pid == "0":
            return cur.attrib.get('id')  # cur ist Layer
        if pid in seen:  # Sicherheitsnetz gegen Zyklen
            return None
        seen.add(pid)
        parent_el = id_index.get(pid)
        if parent_el is None:
            return None
        cur = parent_el

def _collect_cells_for_layer(layer_id: str, id_index: dict, children: dict):
    """
    Menge aller mxCell, deren Top-ancestor-Layer = layer_id ist (vollständig transitiv).
    """
    result_ids = set()
    queue = [layer_id]
    while queue:
        cur = queue.pop(0)
        if cur in result_ids:
            continue
        result_ids.add(cur)
        for child in children.get(cur, []):
            cid = child.attrib.get('id')
            if cid:
                queue.append(cid)
    return result_ids

def _add_base_cells(mx_root_src: ET.Element, mx_root_dst: ET.Element):
    for base_id in ("0", "1"):
        base = mx_root_src.find(f'.//*[@id="{base_id}"]')
        if base is not None:
            mx_root_dst.append(deepcopy(base))

def _relocate_parent(elem: ET.Element, new_parent_id: str):
    elem = deepcopy(elem)
    elem.attrib['parent'] = new_parent_id
    return elem

def _export_layer(mxfile_root_src: ET.Element,
                  diagram_src: ET.Element,
                  mgm_src: ET.Element,
                  mx_root_src: ET.Element,
                  id_index: dict,
                  children: dict,
                  layer_elem: ET.Element,
                  output_dir: str):
    layer_id = layer_elem.attrib.get('id')
    layer_label = layer_elem.attrib.get('value') or 'Unnamed_Layer'

    # Basismenge: alles mit Top-Ancestor = layer_id
    in_layer_ids = _collect_cells_for_layer(layer_id, id_index, children)

    # Zusatzeinschluss: Kanten (edge="1"), deren source/target in der Basismenge liegen,
    # auch wenn deren parent in einem anderen Layer liegt -> parent nach layer_id umhängen.
    cross_edge_ids = set()
    for el_id, el in id_index.items():
        if el.tag != 'mxCell':
            continue
        if el.attrib.get('edge') != '1':
            continue
        src = el.attrib.get('source')
        tgt = el.attrib.get('target')
        if (src and src in in_layer_ids) or (tgt and tgt in in_layer_ids):
            cross_edge_ids.add(el_id)

    # Auch zugehörige Edge-Labels (parent=edge-id) aufnehmen.
    for edge_id in list(cross_edge_ids):
        for possible_label in children.get(edge_id, []):
            if possible_label.tag == 'mxCell':
                cross_edge_ids.add(possible_label.attrib.get('id'))

    # Zielbaum erzeugen
    new_mxfile = ET.Element('mxfile', attrib={
        'host': mxfile_root_src.attrib.get('host', 'app.diagrams.net'),
        'agent': mxfile_root_src.attrib.get('agent', ''),
        'version': mxfile_root_src.attrib.get('version', '28.0.7')
    })
    new_diagram = ET.SubElement(new_mxfile, 'diagram', attrib={
        'name': layer_label,
        'id': diagram_src.attrib.get('id', 'default_id')
    })
    new_mgm = ET.SubElement(new_diagram, 'mxGraphModel', attrib=mgm_src.attrib)
    new_root = ET.SubElement(new_mgm, 'root')

    _add_base_cells(mx_root_src, new_root)

    # Layer-Zelle selbst
    new_root.append(deepcopy(layer_elem))

    # Bereits eingefügte IDs
    added = {e.attrib.get('id') for e in new_root.findall('.//*') if e.attrib.get('id')}

    # 1) Alle im Layer befindlichen Zellen (inkl. transitiver Nachfahren) kopieren
    for el_id in in_layer_ids:
        if el_id in added:
            continue
        el = id_index.get(el_id)
        if el is None:
            continue
        new_root.append(deepcopy(el))
        added.add(el_id)

    # 2) Cross-Layer-Kanten + Labels hinzufügen und parent umlenken
    for el_id in cross_edge_ids:
        if el_id in added:
            continue
        el = id_index.get(el_id)
        if el is None:
            continue
        # Parent ggf. umhängen, damit der Export eine valide Hierarchie besitzt
        if el.attrib.get('parent') != layer_id:
            el_copy = _relocate_parent(el, layer_id)
        else:
            el_copy = deepcopy(el)
        new_root.append(el_copy)
        added.add(el_id)

    # Datei schreiben
    os.makedirs(output_dir, exist_ok=True)
    out_name = sanitize_filename(layer_label) + '.drawio'
    out_path = os.path.join(output_dir, out_name)
    ET.ElementTree(new_mxfile).write(out_path, encoding='utf-8', xml_declaration=True)
    print(f"Exported layer '{layer_label}' to '{out_path}'")

def export_layers(input_file: str, output_dir: str):
    tree = ET.parse(input_file)
    root = tree.getroot()

    diagram_src = _first_diagram(root)
    mgm_src = _mxgraphmodel(diagram_src)
    mx_root_src = _mxroot(mgm_src)

    id_index, children = _build_indices(mx_root_src)

    # Layer = alle mxCell mit parent="0"
    layers = mx_root_src.findall('.//mxCell[@parent="0"]')
    if not layers:
        raise ValueError("Keine Layer gefunden (mxCell mit parent='0').")

    for layer_elem in layers:
        _export_layer(root, diagram_src, mgm_src, mx_root_src,
                      id_index, children, layer_elem, output_dir)

def main():
    parser = argparse.ArgumentParser(description='Exportiert Layer aus einer .drawio-Datei in einzelne .drawio-Dateien.')
    parser.add_argument('--input_file', required=True, help='Pfad zur Eingabe-.drawio')
    parser.add_argument('--output_dir', required=True, help='Zielordner')
    args = parser.parse_args()
    export_layers(args.input_file, args.output_dir)

if __name__ == '__main__':
    main()
